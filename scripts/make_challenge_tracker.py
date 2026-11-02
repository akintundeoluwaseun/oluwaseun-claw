"""Number every challenge in the owner's list and track its status. Writes docs/CHALLENGES.md.

    python scripts/make_challenge_tracker.py

Statuses: PASSED (real brain, clean Windows, objective check) · BUILT (code and tests here, no real-brain pass yet)
· PLANNED (milestone named) · OUT (needs a paid app or a far bigger brain; S-CLAW says so instead of faking it).
Edit STATUS below as results come in; the numbers never change.
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "docs" / "challenge-list-source.txt"
OUT = Path(__file__).resolve().parents[1] / "docs" / "CHALLENGES.md"

MILESTONE = {1: "M8", 2: "M7", 3: "M8", 4: "M8", 5: "—", 6: "M9", 7: "M3", 8: "M5", 9: "M6", 10: "—", 11: "—",
             12: "M10", 13: "M3", 14: "M7", 15: "M4", 16: "M11", 17: "M2"}
# Whole sections that need paid apps or accounts we cannot test, or a far bigger brain.
NOTE = {2: " (S-CLAW's own video tools; Premiere is paid)", 12: " (free tools: FreeCAD, KiCad, Python)",
        14: " (S-CLAW's own audio tools)", 1: " (Photoshop by script when installed, else the built-in editor)"}
OUT_SECTIONS = {5: "Figma needs an account; UI design needs a far bigger brain",
                10: "needs your e-mail/Slack accounts", 11: "needs Notion/Trello accounts"}

# Exact results so far, by challenge number. Evidence: TEST_RESULTS.md and ci-evidence.
STATUS = {
    # 15. Files
    "15.02": ("PASSED", "benchmark: files-duplicates"),
    "15.03": ("PASSED", "benchmark files-largest: PASS in runs 1 and 3"),
    "15.04": ("PASSED", "benchmark files-organize: PASS in runs 1 and 3 (sort_into_folders)"),
    "15.11": ("PASSED", "benchmark: files-date-range"),
    "15.12": ("PASSED", "benchmark: files-compare"),
    "15.05": ("BUILT", "find_broken_shortcuts"),
    "15.06": ("BUILT", "list_startup_apps (registry Run keys + Startup folders)"),
    "15.08": ("BUILT", "top_memory"),
    "15.13": ("BUILT", "rename_many (numbering, dates, never overwrites)"),
    "15.15": ("BUILT", "archive_folder (zip reopened and CRC-checked)"),
    # 7. Excel
    "7.01": ("PASSED", "benchmark data-combine-csv: PASS in run 3 (combine_tables)"),
    "7.02": ("PASSED", "benchmark: data-dedupe"),
    "7.03": ("BUILT", "add_chart with live totals (data-chart passed; a full dashboard not yet tested)"),
    "7.20": ("PASSED", "benchmark data-chart: PASS run 4 (add_chart, live SUMIF)"),
    "7.04": ("BUILT", "build_model forecast (FORECAST.LINEAR, chart)"),
    "7.15": ("BUILT", "build_model forecast reports the trend; table_totals per group"),
    "7.16": ("BUILT", "build_model break_even (live formulas, chart)"),
    # 8/10 documents
    "4.07": ("BUILT", "make_3d_render turntable with Blender: rendered and checked with real Blender 5.2.3 (bpy) here"),
    "4.15": ("BUILT", "make_3d_render: Blender renders frames, S-CLAW encodes and checks the MP4"),
    "8.02": ("BUILT", "save_report contents=True: a real Word TOC field (no list of figures yet)"),
    "8.06": ("BUILT", "save_report: headings, real bullet/numbered lists, page numbers"),
    "8.08": ("BUILT", "make_presentation (slides, notes, charts; reopened and checked)"),
    "8.13": ("BUILT", "make_presentation speaker notes, checked on reopen"),
    "8.14": ("BUILT", "make_presentation chart slides from numbers"),
    "8.15": ("BUILT", "export_pdf / pdf=True through LibreOffice when installed; page count checked"),
    # 3. After Effects / motion
    "3.14": ("PASSED", "built-in maker: 10 s promo video, release check + benchmark (After Effects itself not tested)"),
    # 1. Photoshop
    "1.06": ("BUILT", "make_flyer; Photoshop path never run"),
    # 13. Accounting
    "13.11": ("PASSED", "remove_duplicates - same check as benchmark data-dedupe (7.02)"),
    # 17. Stress
    "17.01": ("PASSED", "benchmark: stress-missing-info (baseline PASS, run 2 partial)"),
    "17.04": ("BUILT", "Carry on from where it stopped (resume)"),
    "17.06": ("PASSED", "stress-conflict: PASS run 4 (failed runs 1-3); limits check now asks before running"),
    "17.07": ("PASSED", "stress-wrong-path: PASS runs 1, 2 and 4 (run 3 failed; fixed)"),
    "17.08": ("FLAKY", "stress-contradiction: PASS runs 2-3, FAIL 1 and 4; document totals now checked"),
    "17.09": ("PASSED", "infeasible-missing-app: PASS run 4 (run 3 timed out)"),
    "17.10": ("PASSED", "benchmark docs-five-files: PASS in run 3"),
    "17.17": ("BUILT", "four-part report tracks done/left"),
    "17.20": ("BUILT", "four-part final report on every task"),
}
OUT_ITEMS = {  # single items beyond a small local brain or needing paid apps
    "1.01", "1.04", "1.08", "1.11", "1.16", "2.13", "3.09", "3.10", "4.01", "4.03", "4.04", "4.09",
    "4.11", "12.01", "12.02", "12.03", "12.04", "12.05", "12.06", "12.07",
}


def parse():
    sections, sec, title = [], None, ""
    lines = SRC.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^### (\d+)\\?\. (.+)", line)
        if m:
            sec, title = int(m.group(1)), m.group(2).strip()
            if sec <= 17:
                sections.append([sec, title, []])
            continue
        if sec is None or sec > 17:
            continue
        if sec == 16:
            mm = re.match(r"^Mission (\d+) — (.+)", line.strip())
            if mm:
                instr = next((l.strip().strip('"') for l in lines[i + 1:i + 6] if l.strip().startswith('"')), "")
                sections[-1][2].append(f"Mission {mm.group(1)}: {mm.group(2)} — {instr}")
        elif line.startswith("* "):
            sections[-1][2].append(line[2:].strip())
    return sections


def main():
    sections = parse()
    rows, counts = [], {}
    for sec, title, items in sections:
        rows.append(f"\n## {sec}. {title}  ·  milestone {MILESTONE.get(sec, '—')}\n")
        rows.append("| # | Challenge | Status | Evidence / note |")
        rows.append("|---|---|---|---|")
        for n, text in enumerate(items, 1):
            cid = f"{sec}.{n:02d}"
            if cid in STATUS:
                st, note = STATUS[cid]
            elif sec in OUT_SECTIONS:
                st, note = "OUT", OUT_SECTIONS[sec]
            elif cid in OUT_ITEMS:
                st, note = "OUT", "needs a paid app or a far bigger brain"
            else:
                st, note = "PLANNED", f"milestone {MILESTONE.get(sec, '—')}" + NOTE.get(sec, "")
            counts[st] = counts.get(st, 0) + 1
            rows.append(f"| {cid} | {text.replace('|', '/')} | {st} | {note} |")
    total = sum(counts.values())
    head = ["# The challenge list, numbered and tracked", "",
            "Every challenge from the owner's list (docs/challenge-list-source.txt), numbered section.item. "
            "Generated by `scripts/make_challenge_tracker.py`; statuses change only on evidence (TEST_RESULTS.md).", "",
            f"**{total} challenges:** " + " · ".join(f"{k} {v}" for k, v in sorted(counts.items())), "",
            "- **PASSED** — done by a real brain on a clean Windows PC, checked objectively.",
            "- **BUILT** — the capability exists and passes its tests here; no real-brain pass yet.",
            "- **PLANNED** — scheduled in the milestone shown (docs/ROADMAP.md).",
            "- **FAIL** — tried with a real brain and failed.",
            "- **FLAKY** — passed some real runs, failed others.",
            "- **OUT** — needs a paid app/account or a far bigger brain; S-CLAW says so rather than fake it."]
    OUT.write_text("\n".join(head + rows) + "\n", encoding="utf-8")
    print(total, counts)


if __name__ == "__main__":
    main()
