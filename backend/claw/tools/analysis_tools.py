"""Looking at a table and answering a question about it.

Sections 7 and 13 of the challenge list are twenty-eight business jobs -
pivot reports, overdue payments, low stock, reconciling a bank statement
against invoices, segmenting customers, spotting odd transactions. They read
as twenty-eight features and they are not: they are four operations with
different nouns in front of them.

  pivot_table        group rows and add something up
  filter_rows        keep the rows that match a condition
  reconcile_tables   line two tables up on a key and report the differences
  find_outliers      point at the values that do not belong

Building one tool per challenge would put twenty-eight descriptions in the
catalogue a small brain has to read, to do work four tools already cover. The
playbook says reuse before building, and this is that applied inside our own
code rather than to somebody else's library.

Everything here is deterministic. No model decides a total, a match or an
average: that is what a spreadsheet is for, and a brain asked to do arithmetic
is the thing the benchmark keeps catching out.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec, as_str_list
from claw.tools.table_tools import (
    _column, _fmt, _out, find_folder, find_table, norm_header, read_table, to_number, write_table,
)

AGGREGATIONS = ("sum", "average", "count", "min", "max")


def _as_date(v: Any) -> date | None:
    """A date from a cell, whatever the spreadsheet put there."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    text = str(v or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _aggregate(how: str, values: list[float]) -> float:
    if not values:
        return 0.0
    if how == "sum":
        return sum(values)
    if how == "average":
        return sum(values) / len(values)
    if how == "count":
        return float(len(values))
    return min(values) if how == "min" else max(values)


# ---------- pivot_table ----------
class PivotArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500, description="The table")
    group_by: str = Field(min_length=1, max_length=80, description="Column to group rows by")
    value_column: str | None = Field(default=None, max_length=80, description="Default: the amount column")
    how: Literal["sum", "average", "count", "min", "max"] = "sum"
    split_by: str | None = Field(default=None, max_length=80, description="A second column, as columns across")
    file_name: str = Field(default="summary", max_length=100)
    format: Literal["xlsx", "csv"] = "xlsx"
    save_in: str | None = Field(default=None, max_length=500)


async def pivot_table(args: PivotArgs, ctx: ToolContext) -> ToolResult:
    def work():
        src = find_table(ctx, args.path)
        head, rows = read_table(src)
        ctx.memory.note_file(src)
        gi = _column(head, args.group_by)
        vi = _column(head, args.value_column, rows, numeric=True) if args.how != "count" else gi
        si = _column(head, args.split_by) if args.split_by else None

        buckets: dict[tuple[str, str], list[float]] = {}
        groups: list[str] = []
        splits: list[str] = []
        for r in rows:
            g = str(r[gi] if gi < len(r) else "").strip() or "(blank)"
            s = (str(r[si]).strip() or "(blank)") if si is not None and si < len(r) else ""
            if g not in groups:
                groups.append(g)
            if s and s not in splits:
                splits.append(s)
            n = 1.0 if args.how == "count" else to_number(r[vi] if vi < len(r) else None)
            if n is None:
                continue
            buckets.setdefault((g, s), []).append(n)

        label = f"{args.how.title()} of {head[vi]}" if args.how != "count" else "Count"
        if si is None:
            out_head = [head[gi], label]
            out_rows = [[g, round(_aggregate(args.how, buckets.get((g, ""), [])), 2)] for g in sorted(groups)]
        else:
            out_head = [head[gi], *sorted(splits), "Total"]
            out_rows = []
            for g in sorted(groups):
                cells = [round(_aggregate(args.how, buckets.get((g, s), [])), 2) for s in sorted(splits)]
                out_rows.append([g, *cells, round(sum(cells), 2)])

        dest = _out(ctx, find_folder(ctx, args.save_in) if args.save_in else src.parent, args.file_name, args.format)
        write_table(dest, out_head, out_rows, sheet="Summary")
        return dest, out_head, out_rows, head[gi], label

    import asyncio
    dest, out_head, out_rows, group_name, label = await asyncio.to_thread(work)
    back_head, back_rows = await asyncio.to_thread(read_table, dest)
    ok = len(back_rows) == len(out_rows) and len(back_head) == len(out_head)
    ctx.memory.outputs.append({"path": str(dest), "kind": "spreadsheet", "verified": ok, "note": f"{len(out_rows)} groups"})
    top = sorted(out_rows, key=lambda r: r[-1] if isinstance(r[-1], (int, float)) else 0, reverse=True)[:3]
    lead = "; ".join(f"{r[0]} {_fmt(float(r[-1]))}" for r in top)
    return ToolResult(True, f"Saved {dest.name}: {label.lower()} by {group_name}, {len(out_rows)} group(s). Largest: {lead}.",
                      {"path": str(dest), "groups": len(out_rows), "columns": out_head,
                       "rows": [list(r) for r in out_rows[:50]]}, verified=ok)


# ---------- filter_rows ----------
class FilterArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    column: str = Field(min_length=1, max_length=80)
    test: Literal["below", "above", "equals", "not equals", "contains", "before", "after", "empty", "not empty"] = "below"
    value: str = Field(default="", max_length=200, description="The number, text or date to compare with")
    file_name: str = Field(default="matching rows", max_length=100)
    format: Literal["xlsx", "csv"] = "xlsx"
    save_in: str | None = Field(default=None, max_length=500)


async def filter_rows(args: FilterArgs, ctx: ToolContext) -> ToolResult:
    def work():
        src = find_table(ctx, args.path)
        head, rows = read_table(src)
        ctx.memory.note_file(src)
        ci = _column(head, args.column)
        want_n = to_number(args.value)
        want_d = _as_date(args.value)
        want_t = args.value.strip().lower()

        def keep(cell: Any) -> bool:
            text = str(cell or "").strip()
            if args.test == "empty":
                return text == ""
            if args.test == "not empty":
                return text != ""
            if args.test in ("below", "above"):
                n = to_number(cell)
                if n is None or want_n is None:
                    return False
                return n < want_n if args.test == "below" else n > want_n
            if args.test in ("before", "after"):
                d = _as_date(cell)
                if d is None or want_d is None:
                    return False
                return d < want_d if args.test == "before" else d > want_d
            if args.test == "contains":
                return want_t in text.lower()
            same = text.lower() == want_t
            # "equals 100" should match the cell holding 100.0
            if not same and want_n is not None:
                n = to_number(cell)
                same = n is not None and n == want_n
            return same if args.test == "equals" else not same

        kept = [r for r in rows if keep(r[ci] if ci < len(r) else None)]
        dest = _out(ctx, find_folder(ctx, args.save_in) if args.save_in else src.parent, args.file_name, args.format)
        write_table(dest, head, kept, sheet="Matching")
        return dest, head, kept, len(rows), head[ci]

    import asyncio
    dest, head, kept, total, col = await asyncio.to_thread(work)
    back_head, back_rows = await asyncio.to_thread(read_table, dest)
    ok = len(back_rows) == len(kept)
    ctx.memory.outputs.append({"path": str(dest), "kind": "spreadsheet", "verified": ok, "note": f"{len(kept)} of {total}"})
    said = f"{col} {args.test} {args.value}".strip()
    return ToolResult(True, f"{len(kept)} of {total} row(s) have {said}. Saved to {dest.name}.",
                      {"path": str(dest), "matched": len(kept), "checked": total,
                       "rows": [list(r) for r in kept[:50]]}, verified=ok)


# ---------- reconcile_tables ----------
class ReconcileArgs(ToolArgs):
    left: str = Field(min_length=1, max_length=500, description="The first table, e.g. the invoices")
    right: str = Field(min_length=1, max_length=500, description="The second, e.g. the bank statement")
    key: str = Field(min_length=1, max_length=80, description="The column that identifies a record in both")
    amount: str | None = Field(default=None, max_length=80, description="A number column to compare as well")
    tolerance: float = Field(default=0.01, ge=0, le=1000, description="How far two amounts may differ and still match")
    file_name: str = Field(default="reconciliation", max_length=100)
    format: Literal["xlsx", "csv"] = "xlsx"
    save_in: str | None = Field(default=None, max_length=500)


async def reconcile_tables(args: ReconcileArgs, ctx: ToolContext) -> ToolResult:
    def work():
        lp, rp = find_table(ctx, args.left), find_table(ctx, args.right)
        lh, lr = read_table(lp)
        rh, rr = read_table(rp)
        ctx.memory.note_file(lp)
        ctx.memory.note_file(rp)
        lk, rk = _column(lh, args.key), _column(rh, args.key)
        la = _column(lh, args.amount, lr, numeric=True) if args.amount else None
        ra = _column(rh, args.amount, rr, numeric=True) if args.amount else None

        def index(rows, ki):
            out: dict[str, list] = {}
            for r in rows:
                k = str(r[ki] if ki < len(r) else "").strip().lower()
                if k:
                    out.setdefault(k, []).append(r)
            return out

        left, right = index(lr, lk), index(rr, rk)
        out_rows, matched, differing = [], 0, 0
        for k in sorted(set(left) | set(right)):
            l_rows, r_rows = left.get(k, []), right.get(k, [])
            if l_rows and not r_rows:
                out_rows.append([l_rows[0][lk], "only in the first", "", "", ""])
            elif r_rows and not l_rows:
                out_rows.append([r_rows[0][rk], "only in the second", "", "", ""])
            elif la is not None and ra is not None:
                ln = sum(to_number(r[la]) or 0 for r in l_rows)
                rn = sum(to_number(r[ra]) or 0 for r in r_rows)
                if abs(ln - rn) > args.tolerance:
                    out_rows.append([l_rows[0][lk], "amounts differ", ln, rn, round(ln - rn, 2)])
                    differing += 1
                else:
                    matched += 1
            else:
                matched += 1

        head = [args.key, "Finding", "First", "Second", "Difference"]
        dest = _out(ctx, find_folder(ctx, args.save_in) if args.save_in else lp.parent, args.file_name, args.format)
        write_table(dest, head, out_rows, sheet="Reconciliation")
        return dest, out_rows, matched, differing, len(left), len(right)

    import asyncio
    dest, out_rows, matched, differing, nl, nr = await asyncio.to_thread(work)
    _, back = await asyncio.to_thread(read_table, dest)
    ok = len(back) == len(out_rows)
    only_left = sum(1 for r in out_rows if r[1] == "only in the first")
    only_right = sum(1 for r in out_rows if r[1] == "only in the second")
    ctx.memory.outputs.append({"path": str(dest), "kind": "spreadsheet", "verified": ok,
                               "note": f"{matched} matched, {len(out_rows)} to look at"})
    return ToolResult(
        True,
        f"{matched} matched. {only_left} only in the first, {only_right} only in the second"
        + (f", {differing} where the amounts differ" if differing else "")
        + f". Saved to {dest.name}.",
        {"path": str(dest), "matched": matched, "only_in_first": only_left, "only_in_second": only_right,
         "amounts_differ": differing, "rows": [list(r) for r in out_rows[:50]]}, verified=ok)


# ---------- find_outliers ----------
class OutlierArgs(ToolArgs):
    path: str = Field(min_length=1, max_length=500)
    column: str | None = Field(default=None, max_length=80, description="Default: the amount column")
    sensitivity: float = Field(default=3.5, ge=1.5, le=10, description="Lower finds more")
    file_name: str = Field(default="unusual rows", max_length=100)
    format: Literal["xlsx", "csv"] = "xlsx"
    save_in: str | None = Field(default=None, max_length=500)


async def find_outliers(args: OutlierArgs, ctx: ToolContext) -> ToolResult:
    def work():
        src = find_table(ctx, args.path)
        head, rows = read_table(src)
        ctx.memory.note_file(src)
        ci = _column(head, args.column, rows, numeric=True)
        pairs = [(r, to_number(r[ci] if ci < len(r) else None)) for r in rows]
        values = [n for _, n in pairs if n is not None]
        if len(values) < 4:
            raise ToolError(f"There are only {len(values)} numbers in {head[ci]}; that is too few to call anything unusual.")

        # Median and median absolute deviation, not mean and standard deviation:
        # one enormous transaction drags a mean far enough to hide itself, which
        # is exactly the row being looked for.
        mid = statistics.median(values)
        mad = statistics.median([abs(v - mid) for v in values]) or 1e-9
        flagged = []
        for r, n in pairs:
            if n is None:
                continue
            score = 0.6745 * abs(n - mid) / mad
            if score >= args.sensitivity:
                flagged.append([*r, round(score, 2), "far above" if n > mid else "far below"])

        dest = _out(ctx, find_folder(ctx, args.save_in) if args.save_in else src.parent, args.file_name, args.format)
        write_table(dest, [*head, "How unusual", "Direction"], flagged, sheet="Unusual")
        return dest, flagged, head[ci], mid, len(values)

    import asyncio
    dest, flagged, col, mid, n = await asyncio.to_thread(work)
    _, back = await asyncio.to_thread(read_table, dest)
    ok = len(back) == len(flagged)
    ctx.memory.outputs.append({"path": str(dest), "kind": "spreadsheet", "verified": ok, "note": f"{len(flagged)} unusual"})
    return ToolResult(True, f"{len(flagged)} unusual value(s) in {col} out of {n}; the typical value is {_fmt(mid)}. Saved to {dest.name}.",
                      {"path": str(dest), "unusual": len(flagged), "checked": n, "typical": mid,
                       "rows": [list(r) for r in flagged[:50]]}, verified=ok)


def register_analysis_tools(reg: ToolRegistry) -> None:
    D, W = Capability.DATA, RiskLevel.LOCAL_WRITE
    reg.register(ToolSpec("pivot_table", "Group a table by a column and total, average or count another; saves a summary sheet.",
                          D, W, PivotArgs, pivot_table))
    reg.register(ToolSpec("filter_rows", "Keep the rows where a column is below/above/equals/contains a value, or before/after a date.",
                          D, W, FilterArgs, filter_rows))
    reg.register(ToolSpec("reconcile_tables", "Match two tables on a key column and report what is missing or differs.",
                          D, W, ReconcileArgs, reconcile_tables))
    reg.register(ToolSpec("find_outliers", "Point at the unusually large or small numbers in a column.",
                          D, W, OutlierArgs, find_outliers))
