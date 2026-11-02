"""File tools. All paths go through the permission policy's folder check."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from claw.agent.schemas import Capability
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec

_SAFE_NAME = re.compile(r"[^A-Za-z0-9 ._-]+")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def safe_file_name(name: str, extension: str) -> str:
    stem = Path(name).stem if Path(name).suffix.lower() == extension else Path(name).name
    stem = _SAFE_NAME.sub("-", stem).strip(" .-")[:80] or "links"
    if stem.lower() in _RESERVED:
        stem = f"{stem}-file"
    return stem + extension


def unique_path(path: Path) -> Path:
    """Never overwrite: add (2), (3)… when a file already exists."""
    if not path.exists():
        return path
    for i in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise ToolError("Too many files with that name already exist.")


def folder_named(ctx: ToolContext, raw: str) -> Path | None:
    """The one folder called like the last part of `raw` inside the authorized folders, or None.

    Baseline benchmark, 2 Nov: brains wrote "S-CLAW Bench/Flyers", "Documents\\Flyers" or just
    "Flyers" for Documents\\S-CLAW Bench\\Flyers and were refused, then saved elsewhere or gave up.
    Raises when two folders share the name rather than guess between them.
    """
    name = re.split(r"[\\/]+", str(raw).strip().strip("'\"").rstrip("\\/"))[-1].lower()
    if not name:
        return None
    hits: list[Path] = []
    for root in (Path(r) for r in ctx.settings.permissions.authorized_folders):
        if root.name.lower() == name and root.is_dir():
            hits.append(root)
        if root.is_dir():
            for pattern in ("*", "*/*", "*/*/*", "*/*/*/*"):
                hits += [d for d in root.glob(pattern) if d.is_dir() and d.name.lower() == name]
    hits = list(dict.fromkeys(hits))
    if len(hits) > 1:
        # Prefer the one whose path contains the other parts the brain wrote ("S-CLAW Bench/Flyers").
        parts = [p.lower() for p in re.split(r"[\\/]+", str(raw)) if p][:-1]
        narrowed = [h for h in hits if all(p in str(h).lower() for p in parts if p not in ("documents", "desktop", "downloads"))]
        if len(narrowed) == 1:
            return narrowed[0]
        raise ToolError(f"There are {len(hits)} folders called '{name}': " + "; ".join(str(h) for h in hits[:5]) + ". Give the full path.")
    return hits[0] if hits else None


def existing_folder(ctx: ToolContext, raw: str | None, write: bool = False) -> Path:
    """An authorized folder that exists: the path given, else the folder of that name (see folder_named)."""
    roots = ctx.settings.permissions.authorized_folders
    if not roots:
        raise ToolError("No folders are authorized. Add a folder in Settings so the agent can save files.")
    refused: PathNotAuthorized | None = None
    try:
        target = ctx.policy.check_path(raw or roots[0], write=write)
        if target.is_dir():
            return target
    except PathNotAuthorized as exc:
        refused, target = exc, None
    found = folder_named(ctx, raw) if raw else None
    if found is not None:
        try:
            return ctx.policy.check_path(str(found), write=write)
        except PathNotAuthorized as exc:
            raise ToolError(str(exc)) from exc
    if refused is not None:
        raise ToolError(str(refused)) from refused
    raise ToolError(f"The folder '{target}' does not exist.")


def resolve_folder(ctx: ToolContext, folder: str | None) -> Path:
    return existing_folder(ctx, folder, write=True)


class Link(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=8, max_length=2048)
    note: str = Field(default="", max_length=500)


class SaveLinksArgs(ToolArgs):
    file_name: str = Field(min_length=1, max_length=100)
    heading: str = Field(default="Saved links", max_length=200)
    links: list[Link] = Field(min_length=1, max_length=100)
    folder: str | None = Field(default=None, max_length=500, description="An authorized folder; defaults to the first one")


def check_save_links(args: SaveLinksArgs, ctx: ToolContext) -> None:
    unseen = [l.url for l in args.links if l.url not in ctx.browser.seen_urls]
    if unseen:
        raise ToolError(
            "These addresses were not seen during this task, so they were not saved: " + ", ".join(unseen[:5])
        )
    resolve_folder(ctx, args.folder)


async def save_links(args: SaveLinksArgs, ctx: ToolContext) -> ToolResult:
    check_save_links(args, ctx)
    folder = resolve_folder(ctx, args.folder)
    path = unique_path(folder / safe_file_name(args.file_name, ".md"))
    ctx.policy.check_path(path, write=True)  # re-check the final path
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# {args.heading}", "", f"_Saved by S-CLAW on {stamp}_", ""]
    for l in args.links:
        title = l.title.replace("[", "(").replace("]", ")")
        lines.append(f"- [{title}]({l.url})" + (f" — {l.note}" if l.note else ""))
    content = "\n".join(lines) + "\n"
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as fh:  # "x": fail rather than overwrite
            fh.write(content)
    except OSError as exc:
        raise ToolError(f"The file could not be written: {exc.strerror}") from exc
    written = path.read_text(encoding="utf-8")
    saved = sum(1 for l in args.links if l.url in written)
    ctx.memory.outputs.append({"path": str(path), "kind": "links", "verified": saved == len(args.links), "note": ""})
    return ToolResult(
        saved == len(args.links),
        f"Saved {saved} link(s) to {path}",
        {"path": str(path), "count": saved},
        verified=saved == len(args.links),
    )


def register_file_tools(reg: ToolRegistry) -> None:
    reg.register(
        ToolSpec(
            "save_links",
            "Save a list of links (only ones seen during this task) to a Markdown file in an authorized folder.",
            Capability.FILES,
            RiskLevel.LOCAL_WRITE,
            SaveLinksArgs,
            save_links,
            precheck=check_save_links,
        )
    )

