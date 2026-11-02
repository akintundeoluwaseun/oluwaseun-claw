"""Milestone 3 - data: combine tables, remove duplicate records, total a column across files, chart it.

Built for the jobs on the owner's challenge list (combine ten messy CSV exports, clean duplicate
customers, total sales by branch, a dashboard that updates). Each tool:
  - reads CSV (any delimiter, with or without a BOM) and Excel (.xlsx) the same way,
  - matches column names loosely ("Amount", " amount ", "AMOUNT" are one column),
  - reads money the way people write it ("₦12,000", "$1,250.50", "(300)" for -300),
  - writes a NEW file (never overwrites), reopens it and checks the row count before saying "done".

A brain that names a folder loosely ("the 'Branch sales' folder") gets the folder of that name
inside the authorized folders, as long as exactly one matches.
"""

from __future__ import annotations

import asyncio
import csv
import io
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.permissions.policy import PathNotAuthorized, RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.file_tools import safe_file_name, unique_path

TABLE_EXT = {".csv", ".xlsx", ".xlsm", ".tsv", ".txt"}
MAX_ROWS = 200_000


# ---------- reading ----------
def norm_header(h: Any) -> str:
    return re.sub(r"[\s_]+", " ", str(h or "").strip().lower())


def to_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[₦$£€¥,\s]|NGN|USD|naira", "", s.strip("()"), flags=re.I)
    if s.endswith("-"):
        neg, s = True, s[:-1]
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


def read_table(path: Path) -> tuple[list[str], list[list[Any]]]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl  # noqa: PLC0415

        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True) if any(c not in (None, "") for c in r)]
        wb.close()
    else:
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        return [], []
    head = [str(h).strip() if h not in (None, "") else f"Column {i + 1}" for i, h in enumerate(rows[0])]
    body = rows[1:MAX_ROWS + 1]
    return head, [list(r) + [""] * (len(head) - len(r)) for r in body]


def write_table(path: Path, header: list[str], rows: list[list[Any]], sheet: str = "Data") -> None:
    if path.suffix.lower() == ".csv":
        with open(path, "x", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
        return
    import openpyxl  # noqa: PLC0415
    from openpyxl.styles import Font  # noqa: PLC0415

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet[:31]
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append([_cell(v) for v in r])
    ws.freeze_panes = "A2"
    for i, h in enumerate(header, 1):
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:500] if i - 1 < len(r)])
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = min(48, max(9, width + 2))
    wb.save(path)


def _cell(v: Any) -> Any:
    """Numbers stay numbers in Excel, so sums and charts work."""
    if isinstance(v, (int, float)) or v is None:
        return v
    n = to_number(v)
    s = str(v).strip()
    if n is not None and re.fullmatch(r"[-(]?[₦$£€]?\s?[\d,]+(\.\d+)?\)?", s) and not re.fullmatch(r"0\d{6,}", s.replace(" ", "")):
        return int(n) if n.is_integer() else n
    return s


# ---------- finding folders and files the way people name them ----------
def _authorized(ctx: ToolContext, raw: str, write: bool = False) -> Path:
    try:
        return ctx.policy.check_path(raw, write=write)
    except PathNotAuthorized as exc:
        raise ToolError(str(exc)) from exc


def find_folder(ctx: ToolContext, raw: str | None) -> Path:
    from claw.tools.file_tools import existing_folder  # noqa: PLC0415
    return existing_folder(ctx, raw)


def find_table(ctx: ToolContext, raw: str, near: str | None = None) -> Path:
    # Run 4: path="...\\CRM export" (a folder) and folder="customers.csv" (a file), swapped, five times.
    if near and Path(str(near).replace("\\", "/")).suffix.lower() in TABLE_EXT and not Path(str(raw).replace("\\", "/")).suffix:
        raw, near = near, raw
    try:
        p = ctx.policy.check_path(raw)
        if p.is_file():
            return p
    except PathNotAuthorized:
        pass
    name = Path(raw.replace("\\", "/")).name.lower()
    base = [find_folder(ctx, near)] if near else [Path(r) for r in ctx.settings.permissions.authorized_folders]
    hits = list(dict.fromkeys(q for b in base if b.is_dir() for q in b.rglob("*") if q.is_file() and q.name.lower() == name))
    if len(hits) == 1:
        return _authorized(ctx, str(hits[0]))
    if len(hits) > 1:
        raise ToolError(f"There are {len(hits)} files called '{name}': " + "; ".join(str(h) for h in hits[:5]) + ". Give the full path or the folder.")
    raise ToolError(f"There is no file '{raw}' in the authorized folders.")


def _tables_in(folder: Path, pattern: str) -> list[Path]:
    files = sorted(p for p in folder.glob(pattern or "*") if p.is_file() and p.suffix.lower() in TABLE_EXT and not p.name.startswith("~$"))
    return files


def _out(ctx: ToolContext, folder: Path, name: str, fmt: str) -> Path:
    ext = ".csv" if fmt == "csv" else ".xlsx"
    out = unique_path(folder / safe_file_name(name, ext))
    _authorized(ctx, str(out), write=True)
    return out


def _column(header: list[str], wanted: str | None, rows: list[list[Any]] | None = None, numeric: bool = False) -> int:
    hs = [norm_header(h) for h in header]
    if wanted:
        w = norm_header(wanted)
        for cand in (w, w.rstrip("s"), w + "s"):
            if cand in hs:
                return hs.index(cand)
        close = [i for i, h in enumerate(hs) if w in h or h in w]
        if len(close) == 1:
            return close[0]
        raise ToolError(f"There is no column '{wanted}'. The columns are: {', '.join(header)}.")
    if numeric and rows:
        for name in ("amount", "total", "price", "sales", "revenue", "value", "cost", "qty", "quantity"):
            for i, h in enumerate(hs):
                if name in h and sum(to_number(r[i]) is not None for r in rows) >= max(1, len(rows) // 2):
                    return i
        for i in range(len(header)):
            if sum(to_number(r[i]) is not None for r in rows) >= max(1, len(rows) * 0.8):
                return i
    raise ToolError("Say which column to use. The columns are: " + ", ".join(header) + ".")


def _fmt(n: float) -> str:
    return f"{int(n):,}" if float(n).is_integer() else f"{n:,.2f}"


# ---------- combine_tables ----------
class CombineTablesArgs(ToolArgs):
    folder: str = Field(min_length=1, max_length=500, description="Folder name or path")
    pattern: str = Field(default="*", max_length=100, description="e.g. *.csv")
    file_name: str = Field(default="combined", max_length=100, description="The name the person asked for")
    source_column: str = Field(default="Source", max_length=40, description="Column naming each row's file")
    format: Literal["xlsx", "csv"] = "xlsx"
    save_in: str | None = Field(default=None, max_length=500, description="Default: same folder")


async def combine_tables(args: CombineTablesArgs, ctx: ToolContext) -> ToolResult:
    folder = find_folder(ctx, args.folder)
    made = {str(Path(o["path"])).lower() for o in ctx.memory.outputs if o.get("path")}
    # Never fold an earlier result back in (benchmark, 2 Nov: the second run combined combined.csv too).
    files = [p for p in _tables_in(folder, args.pattern) if str(p).lower() not in made and not p.stem.lower().startswith(("combined", args.file_name.lower()))]
    if len(files) < 1:
        raise ToolError(f"There are no CSV or Excel files matching '{args.pattern}' in {folder}.")

    def work():
        columns: list[str] = []          # first spelling seen, in order
        keys: list[str] = []
        loaded = []
        for p in files:
            head, rows = read_table(p)
            ctx.memory.note_file(p)
            loaded.append((p, head, rows))
            for h in head:
                k = norm_header(h)
                if k not in keys:
                    keys.append(k)
                    columns.append(h.strip().title() if h.strip().islower() else h.strip())
        header = ([args.source_column] if args.source_column else []) + columns
        out_rows = []
        for p, head, rows in loaded:
            idx = {norm_header(h): i for i, h in enumerate(head)}
            label = p.stem.replace("_", " ").replace("-", " ").strip().title()
            for r in rows:
                vals = [r[idx[k]] if k in idx and idx[k] < len(r) else "" for k in keys]
                out_rows.append(([label] if args.source_column else []) + vals)
        out = _out(ctx, find_folder(ctx, args.save_in) if args.save_in else folder, args.file_name, args.format)
        write_table(out, header, out_rows, "Combined")
        back_head, back_rows = read_table(out)
        return out, header, out_rows, back_rows, [(p.name, len(r)) for p, _, r in loaded]

    out, header, rows, back, per_file = await asyncio.to_thread(work)
    ok = len(back) == len(rows) == sum(n for _, n in per_file)
    ctx.memory.outputs.append({"path": str(out), "kind": "spreadsheet", "verified": ok, "note": ""})
    parts = ", ".join(f"{n} ({c} rows)" for n, c in per_file)
    return ToolResult(ok, f"Combined {len(files)} file(s) into {out.name}: {len(rows)} rows, columns {', '.join(header)}. "
                          f"From: {parts}. Reopened and counted {len(back)} rows.",
                      {"path": str(out), "rows": len(rows), "columns": header, "files": per_file}, verified=ok)


# ---------- remove_duplicates ----------
class DedupeArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    folder: str | None = Field(default=None, max_length=500, description="Folder, if only a file name is given")
    match_on: list[str] = Field(default_factory=list, max_length=5,
                                description="Key columns; default email/phone")
    file_name: str = Field(default="", max_length=100)
    format: Literal["same", "xlsx", "csv"] = "same"

    @field_validator("match_on", mode="before")
    @classmethod
    def _one(cls, v):
        return [x.strip() for x in v.split(",") if x.strip()] if isinstance(v, str) else v


def _key_value(header_name: str, v: Any) -> str:
    h, s = norm_header(header_name), str(v or "").strip().lower()
    if "phone" in h or "mobile" in h or "tel" in h:
        d = re.sub(r"\D", "", s)
        return d[-10:] if len(d) >= 10 else d          # 0803... and +234803... are one number
    if "mail" in h:
        return s
    return re.sub(r"\s+", " ", s)


async def remove_duplicates(args: DedupeArgs, ctx: ToolContext) -> ToolResult:
    src = find_table(ctx, args.path, args.folder)

    def work():
        head, rows = read_table(src)
        ctx.memory.note_file(src)
        hs = [norm_header(h) for h in head]
        if args.match_on:
            cols = [_column(head, c) for c in args.match_on]
        else:
            cols = next(([i] for want in ("mail", "phone", "mobile", "name") for i, h in enumerate(hs) if want in h), list(range(len(head))))
        # Two rows are one record when any chosen key matches (same email OR same phone) - people
        # write their name differently far more often than their email or phone.
        seen: dict[tuple[int, str], int] = {}
        keep, dropped = [], []
        for r in rows:
            ks = [(i, _key_value(head[i], r[i])) for i in cols if _key_value(head[i], r[i])]
            if not args.match_on and len(cols) == 1:
                extra = [i for i, h in enumerate(hs) if any(w in h for w in ("mail", "phone", "mobile")) and i not in cols]
                ks += [(i, _key_value(head[i], r[i])) for i in extra if _key_value(head[i], r[i])]
            if any(k in seen for k in ks):
                dropped.append(r)
                continue
            for k in ks:
                seen[k] = len(keep)
            keep.append(r)
        fmt = src.suffix.lower().lstrip(".") if args.format == "same" else args.format
        fmt = "csv" if fmt in ("csv", "tsv", "txt") else "xlsx"
        out = _out(ctx, src.parent, args.file_name or f"{src.stem} clean", fmt)
        write_table(out, head, keep, "Clean")
        _, back = read_table(out)
        return out, head, rows, keep, dropped, back, [head[i] for i in cols]

    out, head, rows, keep, dropped, back, used = await asyncio.to_thread(work)
    ok = len(back) == len(keep)
    ctx.memory.outputs.append({"path": str(out), "kind": "spreadsheet", "verified": ok, "note": ""})
    gone = "; ".join(" ".join(str(c) for c in r[:3]) for r in dropped[:5])
    return ToolResult(ok, f"{len(rows)} rows, {len(dropped)} duplicate(s) removed (matched on {', '.join(used)} - spacing, case and "
                          f"phone formats ignored). Saved {len(keep)} rows to {out.name}; the original is untouched."
                          + (f" Removed: {gone}." if gone else ""),
                      {"path": str(out), "rows_before": len(rows), "rows_after": len(keep), "removed": len(dropped)}, verified=ok)


# ---------- table_totals ----------
class TotalsArgs(ToolArgs):
    folder: str | None = Field(default=None, max_length=500)
    paths: list[str] = Field(default_factory=list, max_length=50, description="Or the files")
    pattern: str = Field(default="*", max_length=100)
    column: str | None = Field(default=None, max_length=80, description="Default: the amount column")
    group_by: str | None = Field(default=None, max_length=80, description="e.g. product")

    @field_validator("paths", mode="before")
    @classmethod
    def _one(cls, v):
        return [v] if isinstance(v, str) else v


async def table_totals(args: TotalsArgs, ctx: ToolContext) -> ToolResult:
    if not args.folder and not args.paths:
        raise ToolError("Give the folder or the files to add up.")

    def work():
        files = [find_table(ctx, p, args.folder) for p in args.paths] if args.paths else _tables_in(find_folder(ctx, args.folder), args.pattern)
        if not files:
            raise ToolError("There are no CSV or Excel files there to add up.")
        grand, count, groups, per_file, skipped = 0.0, 0, {}, [], 0
        col_name = None
        for p in files:
            head, rows = read_table(p)
            ctx.memory.note_file(p)
            ci = _column(head, args.column, rows, numeric=True)
            col_name = col_name or head[ci]
            gi = _column(head, args.group_by) if args.group_by else None
            sub = 0.0
            for r in rows:
                n = to_number(r[ci])
                if n is None:
                    skipped += 1
                    continue
                sub += n
                count += 1
                if gi is not None:
                    g = str(r[gi]).strip().title() or "(blank)"
                    groups[g] = groups.get(g, 0.0) + n
            grand += sub
            per_file.append((p.name, sub))
        return files, grand, count, groups, per_file, skipped, col_name

    files, grand, count, groups, per_file, skipped, col = await asyncio.to_thread(work)
    by_file = "; ".join(f"{n}: {_fmt(s)}" for n, s in per_file)
    by_group = ("; by " + str(args.group_by) + ": " + "; ".join(f"{g} {_fmt(v)}" for g, v in sorted(groups.items(), key=lambda x: -x[1]))) if groups else ""
    note = f" ({skipped} blank or non-number cell(s) skipped)" if skipped else ""
    return ToolResult(True, f"Total of '{col}' across {len(files)} file(s): {_fmt(grand)} from {count} rows{note}. Per file - {by_file}{by_group}.",
                      {"total": grand, "rows": count, "per_file": per_file, "groups": groups, "column": col}, verified=True)


# ---------- add_chart ----------
class ChartArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    folder: str | None = Field(default=None, max_length=500)
    label_column: str = Field(min_length=1, max_length=80, description="e.g. product")
    value_column: str = Field(min_length=1, max_length=80)
    kind: Literal["bar", "line", "pie"] = "bar"
    title: str = Field(default="", max_length=80)
    summarise: bool = Field(default=True, description="Total rows per label")


async def add_chart(args: ChartArgs, ctx: ToolContext) -> ToolResult:
    src = find_table(ctx, args.path, args.folder)

    def work():
        import openpyxl  # noqa: PLC0415
        from openpyxl.chart import BarChart, LineChart, PieChart, Reference  # noqa: PLC0415

        head, rows = read_table(src)
        ctx.memory.note_file(src)
        li, vi = _column(head, args.label_column), _column(head, args.value_column)
        out = _out(ctx, src.parent, f"{src.stem} with chart", "xlsx")
        if src.suffix.lower() in (".xlsx", ".xlsm"):
            wb = openpyxl.load_workbook(src)
        else:
            wb = openpyxl.Workbook()
            ws0 = wb.active
            ws0.title = "Data"
            ws0.append(head)
            for r in rows:
                ws0.append([_cell(v) for v in r])
        ws = wb.create_sheet("Chart")
        ws.append([head[li], head[vi]])
        data_ws = wb.worksheets[0]
        n_data = len(rows)
        if args.summarise:
            # "Rice" and "rice" are one bar (SUMIF ignores case too).
            labels = list({str(r[li]).strip().lower(): str(r[li]).strip() for r in reversed(rows) if str(r[li]).strip()}.values())[::-1]
            L, V = openpyxl.utils.get_column_letter(li + 1), openpyxl.utils.get_column_letter(vi + 1)
            for i, lab in enumerate(labels, 2):
                # Live formulas: the chart follows when rows are added or changed on the data sheet.
                ws.append([lab, f"=SUMIF('{data_ws.title}'!{L}$2:{L}${n_data + 1000},A{i},'{data_ws.title}'!{V}$2:{V}${n_data + 1000})"])
            n = len(labels)
        else:
            for r in rows:
                ws.append([str(r[li]), to_number(r[vi])])
            n = len(rows)
        chart = {"bar": BarChart, "line": LineChart, "pie": PieChart}[args.kind]()
        chart.title = args.title or f"{head[vi]} by {head[li]}"
        chart.add_data(Reference(ws, min_col=2, min_row=1, max_row=n + 1), titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=n + 1))
        chart.width, chart.height = 18, 9
        ws.add_chart(chart, "D2")
        wb.save(out)
        back = openpyxl.load_workbook(out)
        charts = len(back["Chart"]._charts)
        return out, n, charts

    out, n, charts = await asyncio.to_thread(work)
    ok = charts == 1 and n > 0
    ctx.memory.outputs.append({"path": str(out), "kind": "spreadsheet", "verified": ok, "note": ""})
    return ToolResult(ok, f"Saved {out.name} with a {args.kind} chart of {n} {args.label_column} value(s) on a 'Chart' sheet"
                          f"{' (totals are live SUMIF formulas, so the chart updates when the data changes)' if args.summarise else ''}. "
                          f"Reopened: {charts} chart found.",
                      {"path": str(out), "points": n}, verified=ok)


def register_table_tools(reg: ToolRegistry) -> None:
    F, R, W = Capability.DATA, RiskLevel.READ_ONLY, RiskLevel.LOCAL_WRITE
    reg.register(ToolSpec("combine_tables",
                          "Combine a folder's CSV/Excel files into one sheet.", F, W, CombineTablesArgs, combine_tables))
    reg.register(ToolSpec("remove_duplicates",
                          "Save a copy of a table without duplicate records.", F, W, DedupeArgs, remove_duplicates))
    reg.register(ToolSpec("table_totals",
                          "Total a number column across CSV/Excel files, optionally per group.",
                          F, R, TotalsArgs, table_totals))
    reg.register(ToolSpec("add_chart",
                          "Add a chart to a spreadsheet (new .xlsx, live totals).",
                          F, W, ChartArgs, add_chart))


# ---------- build_model: break-even and forecast workbooks with live formulas ----------
class ModelArgs(ToolArgs):
    kind: Literal["break_even", "forecast"]
    fixed_costs: float | None = Field(default=None, ge=0)
    price: float | None = Field(default=None, gt=0)
    variable_cost: float | None = Field(default=None, ge=0)
    history: list[float] = Field(default_factory=list, max_length=120)
    periods: int = Field(default=6, ge=1, le=36)
    source: str | None = Field(default=None, max_length=500)
    column: str | None = Field(default=None, max_length=80)
    file_name: str = Field(default="", max_length=100)
    folder: str | None = Field(default=None, max_length=500)

    @field_validator("history", mode="before")
    @classmethod
    def _nums(cls, v):
        if isinstance(v, str):
            v = re.split(r"[;\s]+|,(?=\s)", v)
        return [n for n in (to_number(x) for x in (v or [])) if n is not None]


def _linear(ys: list[float]) -> tuple[float, float]:
    n = len(ys)
    xs = list(range(1, n + 1))
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    return slope, my - slope * mx


async def build_model(args: ModelArgs, ctx: ToolContext) -> ToolResult:
    import openpyxl  # noqa: PLC0415
    from openpyxl.chart import LineChart, Reference  # noqa: PLC0415
    from openpyxl.styles import Font  # noqa: PLC0415

    folder = find_folder(ctx, args.folder)
    if args.kind == "break_even":
        if args.fixed_costs is None or args.price is None or args.variable_cost is None:
            raise ToolError("A break-even model needs fixed_costs, price and variable_cost.")
        if args.price <= args.variable_cost:
            raise ToolError("The price must be higher than the variable cost per unit, or there is no break-even point.")
        units = args.fixed_costs / (args.price - args.variable_cost)

        def work():
            out = _out(ctx, folder, args.file_name or "break-even model", "xlsx")
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Break-even"
            rows = [("Fixed costs", args.fixed_costs), ("Price per unit", args.price), ("Variable cost per unit", args.variable_cost),
                    ("Contribution per unit", "=B3-B4"), ("Break-even units", "=B2/B5"), ("Break-even sales", "=B6*B3")]
            ws.append(["Input / result", "Value"])
            for r in rows:
                ws.append(list(r))
            for c in ws[1]:
                c.font = Font(bold=True)
            ws.append([])
            ws.append(["Units sold", "Revenue", "Total cost", "Profit"])
            top = max(10, int(units * 2))
            step = max(1, top // 10)
            first = ws.max_row + 1
            for i, q in enumerate(range(0, top + 1, step)):
                r = first + i
                ws.append([q, f"=A{r}*$B$3", f"=$B$2+A{r}*$B$4", f"=B{r}-C{r}"])
            last = ws.max_row
            ch = LineChart()
            ch.title = "Revenue and cost"
            ch.add_data(Reference(ws, min_col=2, max_col=3, min_row=first - 1, max_row=last), titles_from_data=True)
            ch.set_categories(Reference(ws, min_col=1, min_row=first, max_row=last))
            ws.add_chart(ch, "F2")
            ws.column_dimensions["A"].width = 24
            wb.save(out)
            back = openpyxl.load_workbook(out)["Break-even"]
            return out, back["B6"].value == "=B2/B5"

        out, ok = await asyncio.to_thread(work)
        ctx.memory.outputs.append({"path": str(out), "kind": "spreadsheet", "verified": ok, "note": ""})
        return ToolResult(ok, f"Saved {out.name}. Break-even at {_fmt(round(units, 2))} units, i.e. sales of "
                              f"{_fmt(round(units * args.price, 2))} (fixed {_fmt(args.fixed_costs)} ÷ contribution "
                              f"{_fmt(args.price - args.variable_cost)} per unit). The workbook uses live formulas - change an input and "
                              f"the results and chart follow.", {"path": str(out), "units": units, "sales": units * args.price}, verified=ok)

    ys = list(args.history)
    if args.source:
        src = find_table(ctx, args.source, args.folder)
        head, rows = read_table(src)
        ctx.memory.note_file(src)
        ci = _column(head, args.column, rows, numeric=True)
        ys = [n for n in (to_number(r[ci]) for r in rows) if n is not None]
    if len(ys) < 3:
        raise ToolError("A forecast needs at least three past values (give history, or a source file and column).")
    slope, icpt = _linear(ys)
    ahead = [icpt + slope * (len(ys) + k) for k in range(1, args.periods + 1)]

    def work():
        out = _out(ctx, folder, args.file_name or "forecast", "xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Forecast"
        ws.append(["Period", "Actual", "Forecast"])
        for c in ws[1]:
            c.font = Font(bold=True)
        n = len(ys)
        for i, y in enumerate(ys, 1):
            ws.append([i, y, None])
        for k in range(1, args.periods + 1):
            r = n + k + 1
            # Excel's own FORECAST.LINEAR over the actuals: add actuals and the forecast moves with them.
            ws.append([n + k, None, f"=FORECAST.LINEAR(A{r},$B$2:$B${n + 1},$A$2:$A${n + 1})"])
        ch = LineChart()
        ch.title = "Actual and forecast"
        ch.add_data(Reference(ws, min_col=2, max_col=3, min_row=1, max_row=n + args.periods + 1), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=n + args.periods + 1))
        ws.add_chart(ch, "E2")
        wb.save(out)
        return out

    out = await asyncio.to_thread(work)
    ctx.memory.outputs.append({"path": str(out), "kind": "spreadsheet", "verified": True, "note": ""})
    trend = "rising" if slope > 0 else "falling" if slope < 0 else "flat"
    return ToolResult(True, f"Saved {out.name}: a straight-line trend over {len(ys)} past values ({trend}, {_fmt(round(slope, 2))} per period). "
                            f"Next {args.periods}: " + ", ".join(_fmt(round(v, 2)) for v in ahead)
                            + ". The sheet uses Excel's FORECAST.LINEAR, so it updates with new actuals. A trend line is a guide, not a promise.",
                      {"path": str(out), "forecast": ahead, "slope": slope}, verified=True)


def register_model_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec("build_model", "Make a break-even or forecast workbook.",
                          Capability.DATA, RiskLevel.LOCAL_WRITE, ModelArgs, build_model))
