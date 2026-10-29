"""Text and table work Claw can do by itself, without asking the model.

Counting words, searching a file, merging, sorting, comparing, pulling e-mail
addresses out of text, and arithmetic over a CSV column are all exact jobs with
one right answer. Routing them through a language model makes them slower and
occasionally wrong, so they are plain local code here.

Everything reads through the permission policy, nothing overwrites, and the two
tools that compare or search never touch the files they look at.
"""

from __future__ import annotations

import asyncio
import csv
import difflib
import io
import re
from pathlib import Path

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.documents.readers import read_document
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.file_tools import resolve_folder, safe_file_name, unique_path

MAX_READ_BYTES = 20 * 1024 * 1024
MAX_MATCHES = 200
MAX_COMBINE = 20
# Deliberately narrower than the RFC: it has to match addresses people write, not
# prove that every legal address matches. A permissive pattern pulls in half a URL.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _check(ctx: ToolContext, raw: str, write: bool = False) -> Path:
    try:
        return ctx.policy.check_path(raw, write=write)
    except PathNotAuthorized as exc:
        raise ToolError(str(exc)) from exc


def _read(ctx: ToolContext, raw: str) -> tuple[Path, str]:
    """A file's text, after the policy has agreed Claw may read it."""
    path = _check(ctx, raw)
    if not path.is_file():
        raise ToolError(f"'{path}' is not a file.")
    if path.stat().st_size > MAX_READ_BYTES:
        raise ToolError(f"'{path.name}' is too large for this ({path.stat().st_size / 1024**2:.0f} MB).")
    ctx.memory.note_file(path)
    return path, read_document(path)


def _new_file(ctx: ToolContext, folder: str | None, name: str, ext: str) -> Path:
    path = unique_path(resolve_folder(ctx, folder) / safe_file_name(name, ext))
    ctx.policy.check_path(path, write=True)
    return path


def _save(path: Path, text: str) -> bool:
    with open(path, "x", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path.read_text(encoding="utf-8") == text


# ---------- count_text ----------
class CountArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500, description="The file to count")


async def count_text(args: CountArgs, ctx: ToolContext) -> ToolResult:
    path, text = await asyncio.to_thread(_read, ctx, args.path)
    words = len(text.split())
    lines = len(text.splitlines())
    # str.split() splits on any whitespace, so joining what is left is every
    # non-space character - the same answer as counting them one at a time, and
    # about eight times faster on a megabyte because the work happens in C.
    letters = len("".join(text.split()))
    counts = {"words": words, "characters": len(text),
              "characters_without_spaces": letters, "lines": lines,
              "paragraphs": len([b for b in re.split(r"\n\s*\n", text) if b.strip()])}
    return ToolResult(
        True,
        f"{path.name}: {words:,} words, {len(text):,} characters "
        f"({letters:,} without spaces), {lines:,} lines.",
        {"path": str(path), **counts}, verified=True,
    )


# ---------- search_in_file ----------
class SearchFileArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    query: str = Field(min_length=1, max_length=200, description="The word or phrase to look for")
    match_case: bool = False
    whole_words: bool = Field(default=False, description='"Claw" but not "Claws"')


async def search_in_file(args: SearchFileArgs, ctx: ToolContext) -> ToolResult:
    path, text = await asyncio.to_thread(_read, ctx, args.path)
    # The query is quoted into the pattern, so a query like "a.b" or "(x)" searches
    # for those characters instead of being read as a regular expression.
    pattern = re.escape(args.query)
    if args.whole_words:
        pattern = rf"\b{pattern}\b"
    rx = re.compile(pattern, 0 if args.match_case else re.IGNORECASE)
    matches, total = [], 0
    for n, line in enumerate(text.splitlines(), 1):
        found = len(rx.findall(line))
        if not found:
            continue
        total += found
        if len(matches) < MAX_MATCHES:
            matches.append({"line": n, "text": line.strip()[:300]})
    listing = "\n".join(f"line {m['line']}: {m['text']}" for m in matches)
    return ToolResult(
        True,
        f"'{args.query}' appears {total} time(s) in {path.name}, on {len(matches)} line(s)"
        + (f" (first {MAX_MATCHES} shown)." if total > MAX_MATCHES else "."),
        {"path": str(path), "query": args.query, "occurrences": total,
         "lines": matches, "found": total > 0},
        verified=True, untrusted_text=listing,
    )


# ---------- extract_emails ----------
class ExtractEmailArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    save_as: str | None = Field(default=None, max_length=100,
                                description="Optional file name to save the list in")
    folder: str | None = Field(default=None, max_length=500)


def check_extract_emails(args: ExtractEmailArgs, ctx: ToolContext) -> None:
    _check(ctx, args.path)
    if args.save_as:
        resolve_folder(ctx, args.folder)


async def extract_emails(args: ExtractEmailArgs, ctx: ToolContext) -> ToolResult:
    path, text = await asyncio.to_thread(_read, ctx, args.path)
    seen: dict[str, str] = {}
    for hit in EMAIL_RE.findall(text):
        seen.setdefault(hit.lower(), hit)      # one entry per address, first spelling kept
    addresses = list(seen.values())
    data: dict[str, object] = {"path": str(path), "count": len(addresses), "emails": addresses}
    note = ""
    if args.save_as and addresses:
        out = _new_file(ctx, args.folder, args.save_as, ".txt")
        ok = await asyncio.to_thread(_save, out, "\n".join(addresses) + "\n")
        data["saved_to"] = str(out)
        ctx.memory.note_file(out)
        note = f" Saved to {out.name}." if ok else " The list could not be saved."
    return ToolResult(True, f"Found {len(addresses)} e-mail address(es) in {path.name}.{note}",
                      data, verified=True, untrusted_text="\n".join(addresses))


# ---------- combine_files ----------
class CombineArgs(ToolArgs):
    paths: list[str] = Field(min_length=2, max_length=MAX_COMBINE,
                             description="Two or more files to join, in order")
    file_name: str = Field(min_length=1, max_length=100, description="The new file, e.g. combined.txt")
    folder: str | None = Field(default=None, max_length=500)
    divider: str = Field(default="", max_length=200,
                         description='Optional text on its own line between the files, e.g. "---"')
    add_headings: bool = Field(default=False, description="Put each file's name above its contents")

    @field_validator("paths")
    @classmethod
    def _each_short(cls, v: list[str]) -> list[str]:
        for p in v:
            if not p.strip() or len(p) > 500:
                raise ValueError("each path must be a non-empty path under 500 characters")
        return v


def check_combine(args: CombineArgs, ctx: ToolContext) -> None:
    for raw in args.paths:
        _check(ctx, raw)
    resolve_folder(ctx, args.folder)


async def combine_files(args: CombineArgs, ctx: ToolContext) -> ToolResult:
    def work() -> tuple[Path, list[dict[str, object]], bool, int]:
        parts, sources = [], []
        for raw in args.paths:
            path, text = _read(ctx, raw)
            sources.append({"path": str(path), "characters": len(text)})
            parts.append(f"## {path.name}\n\n{text}" if args.add_headings else text)
        # Tool arguments arrive with their whitespace stripped, so a separator cannot
        # be a newline the caller passes in. The joining is done here instead: one blank
        # line between files, with the divider on its own line when there is one.
        glue = f"\n\n{args.divider}\n\n" if args.divider else "\n\n"
        joined = glue.join(part.rstrip("\n") for part in parts) + "\n"
        out = _new_file(ctx, args.folder, args.file_name, Path(args.file_name).suffix.lower() or ".txt")
        return out, sources, _save(out, joined), len(joined)

    out, sources, ok, size = await asyncio.to_thread(work)
    ctx.memory.note_file(out)
    return ToolResult(
        ok,
        f"Combined {len(sources)} file(s) into {out.name} ({size:,} characters). The originals are unchanged."
        if ok else f"Wrote {out.name}, but its contents could not be verified.",
        {"path": str(out), "sources": sources, "characters": size}, verified=ok,
    )


# ---------- compare_files ----------
class CompareArgs(ToolArgs):
    first: str = Field(min_length=1, max_length=500)
    second: str = Field(min_length=1, max_length=500)
    ignore_whitespace: bool = False


async def compare_files(args: CompareArgs, ctx: ToolContext) -> ToolResult:
    def work() -> tuple[Path, Path, list[str], int, int]:
        p1, t1 = _read(ctx, args.first)
        p2, t2 = _read(ctx, args.second)
        a, b = t1.splitlines(), t2.splitlines()
        if args.ignore_whitespace:
            a = [" ".join(x.split()) for x in a]
            b = [" ".join(x.split()) for x in b]
        diff = list(difflib.unified_diff(a, b, p1.name, p2.name, lineterm="", n=2))
        added = sum(1 for d in diff[2:] if d.startswith("+"))
        removed = sum(1 for d in diff[2:] if d.startswith("-"))
        return p1, p2, diff, added, removed

    p1, p2, diff, added, removed = await asyncio.to_thread(work)
    same = not diff
    shown = diff[:400]
    return ToolResult(
        True,
        f"{p1.name} and {p2.name} are identical." if same else
        f"{p1.name} and {p2.name} differ: {removed} line(s) removed, {added} added. Neither file was changed.",
        {"first": str(p1), "second": str(p2), "identical": same,
         "lines_added": added, "lines_removed": removed, "truncated": len(diff) > len(shown)},
        verified=True, untrusted_text="\n".join(shown),
    )


# ---------- sort_lines ----------
class SortArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    file_name: str = Field(min_length=1, max_length=100, description="The new sorted file")
    folder: str | None = Field(default=None, max_length=500)
    descending: bool = False
    remove_duplicates: bool = False
    skip_first_line: bool = Field(default=False, description="Keep a header row where it is")


def check_sort(args: SortArgs, ctx: ToolContext) -> None:
    _check(ctx, args.path)
    resolve_folder(ctx, args.folder)


async def sort_lines(args: SortArgs, ctx: ToolContext) -> ToolResult:
    def work() -> tuple[Path, Path, int, int, bool]:
        path, text = _read(ctx, args.path)
        lines = text.splitlines()
        header = lines[:1] if args.skip_first_line else []
        body = [ln for ln in lines[len(header):] if ln.strip()]
        before = len(body)
        if args.remove_duplicates:
            body = list(dict.fromkeys(body))
        # Case-insensitive, because a reader sorting names does not expect "adebayo"
        # after "Yusuf"; the tie-break keeps the order stable and repeatable.
        body.sort(key=lambda s: (s.strip().lower(), s), reverse=args.descending)
        out = _new_file(ctx, args.folder, args.file_name,
                        Path(args.file_name).suffix.lower() or path.suffix.lower() or ".txt")
        return path, out, before, len(body), _save(out, "\n".join(header + body) + "\n")

    path, out, before, after, ok = await asyncio.to_thread(work)
    dropped = before - after
    return ToolResult(
        ok,
        f"Sorted {after} line(s) from {path.name} into {out.name}"
        + (f", dropping {dropped} duplicate(s)" if dropped else "")
        + ". The original is unchanged." if ok else f"Wrote {out.name}, but it could not be verified.",
        {"path": str(out), "source": str(path), "lines": after, "duplicates_removed": dropped},
        verified=ok,
    )


# ---------- CSV helpers ----------
def _read_csv(ctx: ToolContext, raw: str) -> tuple[Path, list[str], list[dict[str, str]]]:
    path = _check(ctx, raw)
    if not path.is_file():
        raise ToolError(f"'{path}' is not a file.")
    if path.suffix.lower() != ".csv":
        raise ToolError(f"'{path.name}' is not a .csv file.")
    if path.stat().st_size > MAX_READ_BYTES:
        raise ToolError(f"'{path.name}' is too large for this.")
    # utf-8-sig: create_spreadsheet writes the byte-order mark Excel wants, and
    # without this the first column name comes back with it still attached.
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        columns = list(reader.fieldnames or [])
        rows = [r for r in reader]
    if not columns:
        raise ToolError(f"'{path.name}' has no header row, so its columns cannot be named.")
    ctx.memory.note_file(path)
    return path, columns, rows


def _pick(column: str, columns: list[str]) -> str:
    for c in columns:
        if c.strip().lower() == column.strip().lower():
            return c
    raise ToolError(f"There is no column called '{column}'. The columns are: {', '.join(columns)}.")


def _number(value: str) -> float | None:
    """The number in a cell like "₦1,500.00" or "12 kg", or None if there isn't one."""
    m = NUMBER_RE.search(str(value).replace(",", ""))
    return float(m.group()) if m else None


def _tidy(x: float) -> float | int:
    return int(x) if float(x).is_integer() else round(x, 6)


# ---------- summarize_column ----------
class ColumnArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500, description="A .csv file with a header row")
    column: str = Field(min_length=1, max_length=100, description="The column name")


async def summarize_column(args: ColumnArgs, ctx: ToolContext) -> ToolResult:
    path, columns, rows = await asyncio.to_thread(_read_csv, ctx, args.path)
    name = _pick(args.column, columns)
    values = [v for v in (_number(r.get(name) or "") for r in rows) if v is not None]
    skipped = len(rows) - len(values)
    if not values:
        raise ToolError(f"No numbers were found in the '{name}' column of {path.name}.")
    stats = {"count": len(values), "sum": _tidy(sum(values)),
             "average": _tidy(sum(values) / len(values)),
             "minimum": _tidy(min(values)), "maximum": _tidy(max(values))}
    return ToolResult(
        True,
        f"{name} in {path.name}: {stats['count']} number(s), total {stats['sum']:,}, "
        f"average {stats['average']:,}, lowest {stats['minimum']:,}, highest {stats['maximum']:,}"
        + (f"; {skipped} row(s) had no number." if skipped else "."),
        {"path": str(path), "column": name, "rows_without_a_number": skipped, **stats},
        verified=True,
    )


# ---------- add_computed_column ----------
class ComputeArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500, description="A .csv file with a header row")
    first_column: str = Field(min_length=1, max_length=100)
    operation: str = Field(description="multiply, divide, add or subtract")
    second_column: str | None = Field(default=None, max_length=100,
                                      description="The other column, if not using a fixed number")
    number: float | None = Field(default=None, description="A fixed number instead of a second column")
    new_column: str = Field(min_length=1, max_length=100, description='e.g. "Total value"')
    file_name: str = Field(min_length=1, max_length=100, description="The new .csv to write")
    folder: str | None = Field(default=None, max_length=500)

    @field_validator("operation")
    @classmethod
    def _known(cls, v: str) -> str:
        if v.strip().lower() not in ("multiply", "divide", "add", "subtract"):
            raise ValueError("operation must be multiply, divide, add or subtract")
        return v.strip().lower()


def check_compute(args: ComputeArgs, ctx: ToolContext) -> None:
    _check(ctx, args.path)
    resolve_folder(ctx, args.folder)
    if (args.second_column is None) == (args.number is None):
        raise ToolError("Give either a second column or a fixed number, not both and not neither.")


# Fixed operations, named. There is no expression to evaluate here on purpose: a
# formula field would be a way to run arbitrary code through a spreadsheet tool.
OPS = {"multiply": lambda a, b: a * b, "divide": lambda a, b: a / b,
       "add": lambda a, b: a + b, "subtract": lambda a, b: a - b}


async def add_computed_column(args: ComputeArgs, ctx: ToolContext) -> ToolResult:
    check_compute(args, ctx)

    def work() -> tuple[Path, Path, str, int, int, bool]:
        path, columns, rows = _read_csv(ctx, args.path)
        first = _pick(args.first_column, columns)
        second = _pick(args.second_column, columns) if args.second_column else None
        if args.new_column in columns:
            raise ToolError(f"'{args.new_column}' is already a column in {path.name}.")
        op = OPS[args.operation]
        filled = 0
        for row in rows:
            a = _number(row.get(first) or "")
            b = _number(row.get(second) or "") if second else args.number
            if a is None or b is None or (args.operation == "divide" and b == 0):
                row[args.new_column] = ""      # an unanswerable row is left blank, not guessed
                continue
            row[args.new_column] = str(_tidy(op(a, b)))
            filled += 1
        out = _new_file(ctx, args.folder, args.file_name, ".csv")
        buf = io.StringIO(newline="")
        writer = csv.DictWriter(buf, fieldnames=columns + [args.new_column], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        text = buf.getvalue()
        with open(out, "x", encoding="utf-8-sig", newline="") as fh:
            fh.write(text)
        ok = out.read_text(encoding="utf-8-sig") == text
        return path, out, first, filled, len(rows), ok

    path, out, first, filled, total, ok = await asyncio.to_thread(work)
    ctx.memory.note_file(out)
    other = f"'{args.second_column}'" if args.second_column else str(args.number)
    return ToolResult(
        ok,
        f"Added '{args.new_column}' ({first} {args.operation} {other}) for {filled} of {total} row(s) "
        f"and saved {out.name}. {path.name} is unchanged."
        if ok else f"Wrote {out.name}, but its contents could not be verified.",
        {"path": str(out), "source": str(path), "new_column": args.new_column,
         "rows": total, "rows_computed": filled}, verified=ok,
    )


# ---------- list_to_table ----------
class TableArgs(ToolArgs):
    text: str = Field(min_length=1, max_length=200_000,
                      description="A plain list, one record per line")
    columns: list[str] = Field(min_length=1, max_length=30, description="Column names for the table")
    file_name: str = Field(min_length=1, max_length=100, description="The new .csv")
    folder: str | None = Field(default=None, max_length=500)
    separator: str | None = Field(default=None, max_length=10,
                                  description='What splits each line - a character, or the word '
                                              '"tab"; worked out from the text if left out')


def check_table(args: TableArgs, ctx: ToolContext) -> None:
    resolve_folder(ctx, args.folder)


# A tab or a space-padded bar cannot arrive as itself: tool arguments are stripped.
SEPARATOR_WORDS = {"tab": "\t", "comma": ",", "semicolon": ";", "pipe": "|", "bar": "|", "dash": "-"}


def _split_lines(text: str, columns: int, sep: str | None) -> tuple[list[list[str]], str]:
    sep = SEPARATOR_WORDS.get((sep or "").lower(), sep) or None
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Strip the bullets and numbering people paste in, so "1. Riverside" is one field.
    lines = [re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", ln) for ln in lines]
    candidates = [sep] if sep else ["\t", " | ", "|", ";", ",", " - "]
    best, used = None, ""
    for cand in candidates:
        if not cand:
            continue
        split = [[c.strip() for c in ln.split(cand)] for ln in lines]
        exact = sum(1 for row in split if len(row) == columns)
        if best is None or exact > best[0]:
            best, used = (exact, split), cand
        if exact == len(lines):
            break
    rows = best[1] if best else [[ln] for ln in lines]
    return [row[:columns] + [""] * (columns - len(row)) for row in rows], used


async def list_to_table(args: TableArgs, ctx: ToolContext) -> ToolResult:
    def work() -> tuple[Path, int, str, bool]:
        rows, used = _split_lines(args.text, len(args.columns), args.separator)
        out = _new_file(ctx, args.folder, args.file_name, ".csv")
        buf = io.StringIO(newline="")
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(args.columns)
        writer.writerows(rows)
        text = buf.getvalue()
        with open(out, "x", encoding="utf-8-sig", newline="") as fh:
            fh.write(text)
        return out, len(rows), used, out.read_text(encoding="utf-8-sig") == text

    out, count, used, ok = await asyncio.to_thread(work)
    ctx.memory.note_file(out)
    return ToolResult(
        ok,
        f"Turned {count} line(s) into {out.name} with {len(args.columns)} column(s)"
        + (f", split on '{used}'" if used and len(args.columns) > 1 else "") + "."
        if ok else f"Wrote {out.name}, but its contents could not be verified.",
        {"path": str(out), "rows": count, "columns": args.columns, "separator": used}, verified=ok,
    )


def register_text_tools(reg: ToolRegistry) -> None:
    F, R, W = Capability.FILES, RiskLevel.READ_ONLY, RiskLevel.LOCAL_WRITE
    reg.register(ToolSpec("count_text", "Count the words, characters and lines in a file.",
                          F, R, CountArgs, count_text))
    reg.register(ToolSpec("search_in_file", "Find every line of a file containing a word or phrase.",
                          F, R, SearchFileArgs, search_in_file))
    reg.register(ToolSpec("extract_emails", "List the e-mail addresses in a file, optionally saving them.",
                          F, W, ExtractEmailArgs, extract_emails, precheck=check_extract_emails))
    reg.register(ToolSpec("combine_files", "Join two or more files into one new file; the originals are untouched.",
                          F, W, CombineArgs, combine_files, precheck=check_combine))
    reg.register(ToolSpec("compare_files", "Report the differences between two files, changing neither.",
                          F, R, CompareArgs, compare_files))
    reg.register(ToolSpec("sort_lines", "Sort a file's lines into a new file; the original is untouched.",
                          F, W, SortArgs, sort_lines, precheck=check_sort))
    reg.register(ToolSpec("summarize_column", "Total, average, lowest and highest of a column in a .csv file.",
                          F, R, ColumnArgs, summarize_column))
    reg.register(ToolSpec("add_computed_column",
                          "Work out a new column from existing ones (e.g. price x quantity) into a new .csv.",
                          F, W, ComputeArgs, add_computed_column, precheck=check_compute))
    reg.register(ToolSpec("list_to_table", "Turn a plain list into a .csv table with named columns.",
                          F, W, TableArgs, list_to_table, precheck=check_table))
