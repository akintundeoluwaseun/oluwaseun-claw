"""Plugins: teaching Claw to drive one particular program.

Claw can work a window it has never seen - look at the controls, click, type.
That is guessing, and guessing is why driving a big program like Photoshop
by eye is a coin flip: twenty steps at 95% each finishes 36% of the time.

A plugin replaces the guessing with knowing. It is written by somebody who
actually uses the program, and it says: this is the app, this is how to tell
it is installed, this is the door into it, and here is how to do the jobs
people ask for.

THE DOOR IS THE POINT. A plugin's first job is not "where to click" - it is
"does this program have a scripting way in". Blender takes Python, Photoshop
has its own scripting engine, Word and Excel have COM. Driving a program
through its own script engine is near certain and fast; driving it by moving
the mouse is neither. A plugin names the door, and the mouse is the fallback
for programs that have none.

PLUGINS CARRY NO CODE. A plugin is text: instructions, shortcuts, and the
name of a door Claw already knows how to open. That is a deliberate limit,
not an oversight. If a plugin downloaded from a website could run a program,
the website becomes a way to put malware on every machine that trusts it,
and one bad plugin ends the product. Installing refuses any file that can
execute, and the test suite checks it with a plugin that tries.

The format is the SKILL.md one Claw already reads, with a few more fields,
so every existing skill is already a valid plugin and nothing had to be
rewritten to start this.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

#: S-CLAW's own plugin format. A plugin declares which version it was
#: written against, so a pack built for a later S-CLAW can say so plainly
#: instead of half-working. Bumped only when a change would break old packs.
FORMAT_NAME = "sclaw-plugin"
FORMAT = 1
FORMAT_ID = f"{FORMAT_NAME}/{FORMAT}"

#: Anything that can be executed, or that drags code in. Refused on install
#: whatever the manifest says, because the manifest is written by the same
#: person as the file.
EXECUTABLE = {
    ".exe", ".dll", ".com", ".scr", ".msi", ".msix", ".appx", ".bat", ".cmd",
    ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta",
    ".py", ".pyc", ".pyo", ".pyw", ".sh", ".bash", ".zsh", ".pl", ".rb",
    ".jar", ".class", ".so", ".dylib", ".scpt", ".applescript", ".lnk", ".url",
}
#: What a plugin MAY contain. Text and pictures, nothing that runs.
ALLOWED = {".md", ".txt", ".json", ".yaml", ".yml", ".png", ".jpg", ".jpeg", ".svg", ".webp", ""}

MAX_FILES = 60
MAX_BYTES = 8 * 1024 * 1024
#: Enough to place a plugin in a list, not enough to claim every shelf in it.
MAX_CATEGORIES = 6
#: Example things to say. A handful helps; a page of them is a plugin trying
#: to be the whole menu, and they are shown to people.
MAX_PROMPTS = 8


class PluginRefused(Exception):
    """Why a plugin was not installed. Always says what to do about it."""


@dataclass
class Plugin:
    name: str
    description: str
    body: str
    path: Path
    app: str = ""                      # the program it drives, e.g. "Photoshop"
    programs: list[str] = field(default_factory=list)   # how to tell it is installed
    door: str = ""                     # "python", "comtypes", "jsx", "keys", "mouse"
    version: str = ""
    author: str = ""
    triggers: list[str] = field(default_factory=list)
    #: Where this belongs in a list of plugins - "design", "office", "3d".
    #: Free text on purpose: a fixed vocabulary would mean a new S-CLAW
    #: release every time somebody writes a plugin for a kind of program
    #: nobody thought of, which is the opposite of what plugins are for.
    categories: list[str] = field(default_factory=list)
    #: Things a person could actually say to use this plugin, written by
    #: whoever wrote it. Two jobs: the list of plugins can show them, so
    #: "what do I type?" has an answer that is not guesswork; and they go
    #: into the matching, so the recipe is found by the words people really
    #: use rather than only the ones in its description.
    prompts: list[str] = field(default_factory=list)
    #: Which S-CLAW plugin format it was written against. Blank means a
    #: plugin from before the format was named - still valid, since the
    #: shape has not changed, and it would be rude to break the eleven
    #: recipes that already shipped.
    format: str = ""

    def installed_here(self) -> bool:
        """Is the program this plugin drives actually on this computer?

        A plugin for software the person does not own should not be offered:
        it would send the brain confidently down a road that ends in "that
        program is not installed", several steps later.
        """
        if not self.programs:
            return True
        return any(shutil.which(p) or Path(p).exists() for p in self.programs)


def _front(text: str) -> tuple[str, str] | None:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    return (m.group(1), m.group(2).strip()) if m else None


def _one(front: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.+)$", front, re.M)
    return m.group(1).strip().strip("\"'") if m else ""


def _many(front: str, key: str) -> list[str]:
    raw = _one(front, key)
    return [x.strip() for x in re.split(r"[,;]", raw.strip("[]")) if x.strip()] if raw else []


def read_lines(front: str, key: str) -> list[str]:
    """A list whose items are sentences, so they cannot be split on commas.

    Written the way a list is normally written:

        prompts:
          - Make a 3D model of a cup
          - Render it to a PNG, then open it

    An inline `prompts: [one, two]` is read too, for whoever writes it that
    way, accepting that a comma inside an inline item ends it.
    """
    block = re.search(rf"^{key}:[ \t]*\n((?:[ \t]*-[ \t]*.+\n?)+)", front, re.M)
    if block:
        return [m.group(1).strip().strip("\"'")
                for m in re.finditer(r"^[ \t]*-[ \t]*(.+)$", block.group(1), re.M)
                if m.group(1).strip()]
    inline = re.search(rf"^{key}:[ \t]*(\S.*)$", front, re.M)
    return _many(inline.group(0), key) if inline else []


def parse(text: str, path: Path) -> Plugin:
    parts = _front(text)
    if parts is None:
        raise PluginRefused(
            f"{path.name} has no settings block at the top. A plugin starts with --- , then "
            "name: and description: , then --- , then the instructions.")
    front, body = parts
    name, description = _one(front, "name"), _one(front, "description")
    if not name:
        raise PluginRefused(f"{path.name} does not say name:.")
    if not description:
        raise PluginRefused(f"{path.name} does not say description:. That is the line Claw reads "
                            "to decide whether the plugin fits what was asked.")
    if not body:
        raise PluginRefused(f"{path.name} has settings but no instructions under them.")

    declared = _one(front, "format")
    if declared:
        name_part, _, number = declared.partition("/")
        if name_part.strip().lower() != FORMAT_NAME:
            raise PluginRefused(
                f"{path.name} says it is a '{declared}' plugin. This is S-CLAW, which reads "
                f"{FORMAT_ID} plugins.")
        try:
            wanted = int(number)
        except ValueError:
            raise PluginRefused(f"{path.name} does not say which version of the format it uses "
                                f"(expected something like {FORMAT_ID}).") from None
        if wanted > FORMAT:
            raise PluginRefused(
                f"{path.name} was written for {FORMAT_NAME} format {wanted}, and this S-CLAW "
                f"reads up to {FORMAT}. Update S-CLAW to use this plugin.")

    return Plugin(
        name=name[:60], description=description[:300], body=body, path=path,
        app=_one(front, "app")[:60], programs=_many(front, "programs"),
        door=_one(front, "door")[:30].lower(), version=_one(front, "version")[:20],
        author=_one(front, "author")[:60], triggers=_many(front, "triggers"),
        categories=[c.lower()[:30] for c in _many(front, "categories")[:MAX_CATEGORIES]],
        prompts=[p[:120] for p in read_lines(front, "prompts")[:MAX_PROMPTS]],
        format=declared)


def check_contents(folder: Path) -> list[Path]:
    """Every file a plugin folder may keep, or an error naming the offender."""
    files = [p for p in sorted(folder.rglob("*")) if p.is_file()]
    if not files:
        raise PluginRefused("That plugin is empty.")
    if len(files) > MAX_FILES:
        raise PluginRefused(f"That plugin holds {len(files)} files, more than a plugin should need.")
    total = 0
    for f in files:
        suffix = f.suffix.lower()
        total += f.stat().st_size
        if suffix in EXECUTABLE or suffix not in ALLOWED:
            raise PluginRefused(
                f"'{f.name}' is not something a plugin may contain. A plugin is written "
                "instructions, not a program: Claw will not install anything that can run. "
                "If the job needs a program, say so in the instructions and let the person "
                "approve it when it happens.")
    if total > MAX_BYTES:
        raise PluginRefused(f"That plugin is {total / 2**20:.1f} MB, which is more than a set of "
                            "instructions should be.")
    if not any(f.name.upper() in ("SKILL.MD", "PLUGIN.MD") for f in files):
        raise PluginRefused("A plugin needs a PLUGIN.md (or SKILL.md) holding its instructions.")
    return files


def read_folder(folder: Path) -> Plugin:
    files = check_contents(folder)
    main = next(f for f in files if f.name.upper() in ("PLUGIN.MD", "SKILL.MD"))
    plugin = parse(main.read_text(encoding="utf-8-sig")[:40000], main)
    # The FOLDER, not the .md inside it. install() already set it that way and
    # this did not, so remove() was handed a file path and deleted nothing
    # while reporting success.
    plugin.path = folder
    return plugin


def safe_member(name: str) -> str:
    """A path inside the zip that cannot climb out of where it is unpacked."""
    cleaned = name.replace("\\", "/")
    if cleaned.startswith("/") or (len(cleaned) > 1 and cleaned[1] == ":"):
        raise PluginRefused(f"That plugin contains an absolute path ('{name[:60]}').")
    if any(part == ".." for part in cleaned.split("/")):
        raise PluginRefused(f"That plugin contains a path that climbs out of its folder "
                            f"('{name[:60]}').")
    return cleaned


def install(source: Path, into: Path) -> Plugin:
    """Unpack and check a plugin, then keep it. Nothing runs at any point."""
    into.mkdir(parents=True, exist_ok=True)
    staging = into / ".unpacking"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    try:
        if source.is_dir():
            shutil.copytree(source, staging, dirs_exist_ok=True)
        elif zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as z:
                names = [safe_member(i.filename) for i in z.infolist() if not i.is_dir()]
                if len(names) > MAX_FILES:
                    raise PluginRefused(f"That plugin holds {len(names)} files.")
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    target = staging / safe_member(info.filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out, 1024 * 64)
        else:
            raise PluginRefused(f"{source.name} is not a plugin folder or a .zip.")

        # A zip with one folder inside it is the usual shape.
        inner = [p for p in staging.iterdir()]
        root = inner[0] if len(inner) == 1 and inner[0].is_dir() else staging
        plugin = read_folder(root)

        destination = into / re.sub(r"[^A-Za-z0-9._-]+", "-", plugin.name).strip("-").lower()
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(root), str(destination))
        plugin.path = destination
        return plugin
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def installed(folder: Path) -> list[Plugin]:
    """Every plugin kept here, skipping any that has gone bad."""
    out: list[Plugin] = []
    if not folder or not folder.is_dir():
        return out
    for child in sorted(folder.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            out.append(read_folder(child))
        except (PluginRefused, OSError):
            continue
    return out


def remove(folder: Path, name: str) -> bool:
    for plugin in installed(folder):
        if plugin.name.lower() == name.lower():
            shutil.rmtree(plugin.path, ignore_errors=True)
            return True
    return False
