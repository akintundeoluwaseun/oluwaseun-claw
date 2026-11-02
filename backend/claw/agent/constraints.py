"""The limits a person puts in a request, read once, before planning (reuse audit §2.1, challenge 17.06).

"Make a spreadsheet ... but do not create any new files" failed in every benchmark run: the brain
made the file and said nothing. Small brains miss negations, so Claw reads them itself, with plain
patterns, and does three things with what it finds:

  1. Contradictions (asked for a file, forbidden to make files) are put back to the person as a
     question before anything runs - nothing is planned, nothing is touched.
  2. The limits are written into the brain's instructions in plain words.
  3. A step that would break a limit is refused, whatever the brain asks for (see `breaks`).

Everything here is deterministic; nothing depends on the brain noticing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NEG = r"(?:do not|don't|dont|never|without|no need to|must not|mustn't|avoid)"
_NO_FILES = re.compile(rf"\b{_NEG}\s+(?:create|make|save|write|add|creating|making|saving|writing|adding)\s+"
                       r"(?:any\s+|a\s+)?(?:new\s+)?(?:files?|documents?|spreadsheets?|copies|copy)\b", re.I)
_NO_CHANGES = re.compile(rf"\b{_NEG}\s+(?:change|modify|edit|touch|alter|overwrite|changing|modifying|editing|touching)\b"
                         r"(?:\s+(?:any|the|my))?\s*(?:existing\s+)?(?:files?|originals?|documents?|anything)?", re.I)
_NO_DELETE = re.compile(rf"\b{_NEG}\s+(?:delete|remove|erase|deleting|removing)\b", re.I)
_NO_SEND = re.compile(rf"\b{_NEG}\s+(?:send|post|publish|share|email|e-mail|message|sending|posting)\b", re.I)
_KEEP_ORIGINAL = re.compile(r"\b(?:a|an|clean|new|separate|cleaned)\s+(?:\w+\s+)?copy\b|\bkeep (?:the )?original|\boriginals? (?:untouched|unchanged)", re.I)
_JUST_TELL = re.compile(r"\b(?:just|only)\s+(?:tell|show|list|answer|say)\b|\bread[- ]only\b", re.I)
_WANTS_FILE = re.compile(r"\b(?:make|create|save|build|generate|produce|write|export)\b[^.]{0,60}?"
                         r"\b(?:spreadsheet|sheet|workbook|file|report|document|docx|xlsx|csv|pdf|flyer|poster|video|mp4|chart|table)\b", re.I)

from claw.tools.kinds import CHANGES_FILES as CHANGING  # noqa: E402
from claw.tools.kinds import MAKES_FILES as MAKING  # noqa: E402

DELETING = {"delete_file", "delete_files"}
SENDING = {"send_whatsapp_message", "send_message", "send_email"}


@dataclass
class Limits:
    no_new_files: bool = False
    no_changes: bool = False
    no_delete: bool = False
    no_send: bool = False
    answer_only: bool = False
    wants_file: bool = False
    conflicts: list[str] = field(default_factory=list)

    def any(self) -> bool:
        return self.no_new_files or self.no_changes or self.no_delete or self.no_send or self.answer_only

    def for_prompt(self) -> str:
        rules = []
        if self.no_new_files:
            rules.append("Do NOT create any new file or folder.")
        if self.no_changes:
            rules.append("Do NOT change, move, rename or overwrite any existing file.")
        if self.no_delete:
            rules.append("Do NOT delete anything.")
        if self.no_send:
            rules.append("Do NOT send, post or share anything.")
        if self.answer_only:
            rules.append("Only answer in words; do not create or change files.")
        return ("\n\nLimits the person set (Claw enforces these; a step that breaks one is refused):\n- " + "\n- ".join(rules)) if rules else ""


def read_limits(task: str) -> Limits:
    first = task.strip().split("\n")[0]
    lim = Limits(
        no_new_files=bool(_NO_FILES.search(first)),
        # "Save a clean copy" means the original stays as it is (run 5: the brain renamed customers.csv).
        no_changes=bool(_NO_CHANGES.search(first) or _KEEP_ORIGINAL.search(first)),
        no_delete=bool(_NO_DELETE.search(first)),
        no_send=bool(_NO_SEND.search(first)),
        answer_only=bool(_JUST_TELL.search(first)),
    )
    # "Make a spreadsheet ..." with the negated part removed, so "do not create files" is not itself the request.
    positive = _NO_FILES.sub(" ", first)
    lim.wants_file = bool(_WANTS_FILE.search(positive))
    if lim.wants_file and (lim.no_new_files or lim.answer_only):
        lim.conflicts.append("You asked me to make a file, and also not to create any new files. A spreadsheet or "
                             "report is a file, so I can't do both.")
    return lim


def conflict_question(lim: Limits) -> str | None:
    if not lim.conflicts:
        return None
    return (" ".join(lim.conflicts) + " Which do you want: should I show the result here in my answer without saving "
            "anything, or save it as a new file? Nothing has been created or changed.")


def breaks(lim: Limits, tool: str) -> str | None:
    """Why this step is refused under the person's limits, or None."""
    if (lim.no_new_files or lim.answer_only) and tool in MAKING:
        return ("The person said not to create any new files, and this step would create one. Do not create anything: "
                "finish, and give the answer in words, or tell the person about the conflict.")
    if lim.no_changes and tool in CHANGING:
        return "The person said not to change existing files, and this step would. Do not do it; finish and explain."
    if lim.no_delete and tool in DELETING:
        return "The person said not to delete anything. This step is refused."
    if lim.no_send and tool in SENDING:
        return "The person said not to send anything. This step is refused; you can show the draft instead."
    return None
