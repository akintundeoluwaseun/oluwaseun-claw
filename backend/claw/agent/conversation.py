"""Telling a chat apart from a job, before any of the machinery starts.

Every message used to go the same way: wake the brain, send it the whole tool
catalogue, ask it to plan, then run the plan. For "make me a flyer" that is the
work. For "hi" it is eighty-six tool descriptions and a planning call so the
brain can decide that hello needs no tools - which on a laptop brain is most of
a minute to say one word back.

So this runs first. Two tiers:

  quick_reply()   the unmistakable ones - hello, thanks, ok, bye - answered from
                  here with no model call at all. Instant, and the same every
                  time, which is what a greeting should be.

  is_conversation()  everything else that is plainly talk rather than work: short,
                  no imperative, nothing that names a file, an app or a place on
                  disk. Those get ONE short model call with no tools, instead of
                  planning and executing.

The bias is deliberate and one-sided. Treating a job as chat would answer "I
can do that" and do nothing, which is the false completion this project keeps
measuring. Treating chat as a job only costs the slowness we already had. So
anything carrying the faintest smell of work goes the old way, and the rules
below say what counts as work rather than trying to say what counts as talk.
"""

from __future__ import annotations

import re

# Anything here means work, and ends the conversation check immediately.
# Verbs are matched anywhere, not only at the start: "could you open Notepad"
# and "now save it" are both jobs.
_TASK_VERB = re.compile(
    r"\b(?:make|create|build|generate|design|draw|write|draft|compose|"
    r"open|launch|start|run|close|quit|"
    r"find|search|look\s+up|locate|list|show\s+me|check|compare|count|"
    r"read|scan|extract|summari[sz]e|translate|"
    r"save|store|export|download|upload|install|uninstall|"
    r"send|email|e-mail|message|whatsapp|post|share|reply\s+to|forward|"
    r"copy|move|rename|delete|remove|clean|organi[sz]e|sort|archive|zip|"
    r"edit|change|update|fix|convert|resize|crop|trim|cut|merge|combine|split|"
    r"add|put|set|schedule|remind|book|cancel|plan\s+my|"
    r"type|click|press|fill|select|scroll|record|play|print|"
    r"tell\s+me|give\s+me|how\s+(?:long|many|much|big)|what(?:'s| is| was)\s+(?:the|in|it)|"
    r"remember|forget|calculate|work\s+out|total|sum)\b", re.I)

# Nouns that mean a computer, a file or an app is involved.
_TASK_NOUN = re.compile(
    r"\b(?:file|files|folder|folders|directory|document|documents|pdf|docx?|xlsx?|csv|txt|png|jpe?g|mp4|pptx?|"
    r"spreadsheet|workbook|sheet|slide|slides|deck|presentation|report|invoice|receipt|flyer|poster|logo|"
    r"e-?mail|inbox|whatsapp|calendar|meeting|appointment|reminder|"
    r"browser|chrome|edge|firefox|website|web|page|url|link|tab|"
    r"notepad|word|excel|powerpoint|photoshop|blender|calculator|explorer|app|application|program|"
    r"screenshot|screen|window|desktop|downloads?|documents\s+folder|"
    r"video|audio|image|picture|photo|song|track)\b", re.I)

# A path, an extension, a drive letter, or a quoted name: all mean a real thing on disk.
_LOOKS_LIKE_PATH = re.compile(r"[A-Za-z]:\\|[\\/][\w .-]+[\\/]|\.\w{2,4}\b|“[^”]+”|\"[^\"]+\"")

# Plain talk. Anchored whole-message so "hi" is a greeting and "hide the bar" is not.
# A greeting may be addressed: "hello there", "hi claw". Anything longer is not
# a greeting any more, it is a sentence that opens with one - and those are
# jobs ("hi, can you open my calendar?").
_GREETING = re.compile(
    r"^(?:hi|hii+|hey+|hello+|yo|sup|whats?\s*up|good\s+(?:morning|afternoon|evening|day)|"
    r"howdy|hiya|greetings|salut|hola)"
    r"(?:\s+(?:there|again|claw|s-?claw|mate|buddy))?\b[\s!.,?]*$", re.I)
#: Nobody types the bare word. "thank you so much", "thanks a lot", "thank u",
#: "ok thanks" are all the same sentence, and each one that misses costs a
#: model call - which on a small brain is a long wait to be told "you're
#: welcome".
_THANKS = re.compile(
    r"^(?:thanks?|thank\s*(?:you|u)|thx|thnx|tnx|ty|tysm|cheers|much\s+appreciated|"
    r"nice\s+one|well\s+done|good\s+job|great\s+job|good\s+work|perfect\s+thanks)"
    r"(?:\s+(?:so|very)?\s*much|\s+a\s+lot|\s+a\s+million|\s+again)?"
    r"(?:\s+(?:man|boss|sir|ma|madam|claw|s-?claw|mate|buddy|o+))?"
    r"(?:\s+for\s+(?:the\s+|your\s+)?(?:help|that|this|it|everything|the\s+work))?"
    r"\b[\s!.,?😊🙏👍]*$", re.I)
_OK = re.compile(r"^(?:ok(?:ay)?|k|kk|cool|nice|great|good|fine|alright|sure|got\s+it|understood|perfect|lovely|yes|yeah|yep|no|nope|nah)\b[\s!.,?]*$", re.I)
_BYE = re.compile(r"^(?:bye+|goodbye|good\s*night|see\s+you|see\s+ya|later|cya|that(?:'s| is)\s+all|done\s+for\s+now)\b[\s!.,?]*$", re.I)
_HOW_ARE_YOU = re.compile(r"^(?:how\s+(?:are|r)\s+(?:you|u)|how'?s\s+it\s+going|you\s+(?:there|ok|okay|alright)|are\s+you\s+(?:there|awake|ready|working))\b[\s!.,?]*$", re.I)
#: "What can you do?" in the shapes people actually type it. The first thing
#: anyone asks a new assistant, and the one question it must never need the
#: brain to answer: a tester on a light brain asked exactly this and the app
#: sat there.
_CAPABILITY = re.compile(
    r"^(?:what\s+(?:can|could)\s+(?:you|claw|s-?claw|it|i)\s+(?:do|ask|say)"
    r"|what\s+(?:else\s+)?can\s+you\s+(?:do|help\s+(?:me\s+)?with)"
    r"|what\s+(?:do|does)\s+(?:you|claw|s-?claw|it)\s+do"
    r"|what\s+are\s+you(?:\s+able)?(?:\s+to)?(?:\s+do)?"
    r"|what\s+are\s+you\s+for|who\s+are\s+you"
    r"|help|what\s+now|what\s+next"
    r"|how\s+(?:do|does)\s+(?:this|it|you)\s+work)\b[\s!.,?]*$", re.I)

#: A greeting at the FRONT of a longer message, with whatever separates it from
#: the rest. "Hi, what can you do?" is a greeting and then plain talk, and it
#: was getting neither answer: the greeting pattern is anchored to the whole
#: message, so the comma defeated it, and the capability pattern never saw a
#: string beginning with "what". It fell through to a model call instead - two
#: words of small talk costing a 2B brain its whole thinking time, which is
#: precisely what the fast path exists to prevent.
_LEADING_FILLER = re.compile(
    r"^(?:hi|hii+|hey+|hello+|yo|sup|whats?\s*up|good\s+(?:morning|afternoon|evening|day)|"
    r"howdy|hiya|greetings|salut|hola|ok(?:ay)?|alright|right|so|well|wow|cool|nice|great)"
    r"(?:\s+(?:there|again|claw|s-?claw|mate|buddy|sir|ma|madam|please))?"
    r"(?:\s*[,!.;:–—-]+\s*|\s+)", re.I)

#: "Thanks for opening Notepad." Gratitude that names the job it is grateful
#: for, which every tester types and which smells exactly like the job itself -
#: so it went to the planner, and the planner opened Notepad a second time.
#: Being thanked is not an instruction to do it again.
#:
#: Guarded hard, because "thanks, now close it" is an instruction wearing the
#: same coat: the message has to be nothing but "thanks for <something>", with
#: no clause break and no word that starts a new request.
_THANKS_FOR = re.compile(
    r"^(?:thanks?|thank\s*(?:you|u)|thx|cheers)\s+for\s+(?:the\s+|your\s+)?[\w\s'.-]{1,60}$", re.I)
#: Words that turn gratitude back into a request.
_THEN_A_REQUEST = re.compile(r"\b(?:now|then|next|also|again|after\s+that|could\s+you|can\s+you|please)\b", re.I)

#: Calling it off. "forget it" reads as work only because "forget" is a verb
#: Claw has a tool for, so it went to the planner, which then had to plan how
#: to forget something. Checked before the work guard for that reason, and
#: anchored to the whole message so "forget the invoice I asked you to
#: remember" still reaches the planner, where it belongs.
_NEVER_MIND = re.compile(
    r"^(?:never\s*mind|nevermind|forget\s+(?:it|that|about\s+it)|"
    r"don'?t\s+(?:worry|bother)(?:\s+about\s+it)?|skip\s+it|leave\s+it|cancel\s+that|it'?s\s+fine)"
    r"\b[\s!.,?]*$", re.I)

#: Typing noise. Four of the eight failed chats in the screenshot someone sent
#: were "sdddsss", "sdddsss", "44y" and "sdddsss" - a hand on a keyboard, or a
#: test. They went to the planner and came back "Failed", which is a harsh
#: answer to a slip of the hand, and a slow one.
#:
#: Deliberately narrow: one token, no spaces, and one of three shapes that a
#: real word does not have. A one-word job - "screenshot", "shutdown",
#: "backup" - has vowels, no tripled letter and no stray digits, so it goes to
#: the planner as before. Anything with a space in it is a sentence and is
#: never touched.
_ONE_TOKEN = re.compile(r"^[A-Za-z0-9]{2,14}$")
_TRIPLED = re.compile(r"([A-Za-z])\1{2,}")
_VOWEL = re.compile(r"[aeiouy]", re.I)
_DIGITS_THEN_LETTER = re.compile(r"^\d{1,4}[A-Za-z]{1,2}$")


def looks_like_typing_noise(text: str) -> bool:
    """One token that is not a word anyone meant."""
    t = _first_line(text)
    if not _ONE_TOKEN.match(t):
        return False
    return bool(_TRIPLED.search(t)
                or (len(t) >= 4 and t.isalpha() and not _VOWEL.search(t))
                or _DIGITS_THEN_LETTER.match(t))


_EMOJI_ONLY = re.compile(r"^[\W_]+$", re.U)

# Long enough to be a brief, whatever else it looks like.
_MAX_CHAT_WORDS = 12


def _first_line(text: str) -> str:
    return (text or "").strip().split("\n")[0].strip()


def smells_like_work(text: str) -> bool:
    """True when the message names an action, a thing on the computer, or a path.

    This is the guard the whole module leans on: when it is true, nothing else
    here applies and the request goes to the planner exactly as before.
    """
    t = _first_line(text)
    return bool(_TASK_VERB.search(t) or _TASK_NOUN.search(t) or _LOOKS_LIKE_PATH.search(t))


def quick_reply(text: str, name: str = "S-CLAW", standalone: bool = True) -> str | None:
    """A canned answer for plain talk, or None. No model call, no waiting.

    `standalone` is False when earlier messages exist in this chat. That
    narrows what counts as talk, because mid-conversation the short words stop
    being social and start being answers: "ok" after Claw has asked something
    means do it, "yes" means yes to the question, "no" means stop. Only the
    purely social ones survive a thread.
    """
    t = _first_line(text)
    if not t or len(t) > 60:
        return None
    # Checked before the work guard, and only this one is: "thanks for opening
    # Notepad" names a job on purpose. Everything else that smells of work is
    # still a job.
    if _THANKS_FOR.match(t) and not _THEN_A_REQUEST.search(t) and "," not in t:
        return "Any time."
    if _NEVER_MIND.match(t):
        return "Right - nothing done."
    if smells_like_work(t):
        return None
    answer = _canned(t, name, standalone)
    if answer is not None:
        return answer
    # "Hi, what can you do?" - an opener, then plain talk. Strip the opener and
    # ask again. Greetings and acknowledgements both count: "ok thanks" and
    # "so, what can you do" are the same shape. Nothing that smells of work can
    # reach here, so what follows is either more talk or nothing we answer.
    rest = _LEADING_FILLER.sub("", t, count=1)
    if rest != t and rest:
        return _canned(rest, name, standalone)
    return None


def _canned(t: str, name: str, standalone: bool) -> str | None:
    """The table itself, run against a whole message or against what follows a greeting."""
    if _GREETING.match(t):
        return "Hi. What would you like done?"
    if _THANKS.match(t):
        return "Any time."
    if _BYE.match(t):
        return "Bye."
    if _HOW_ARE_YOU.match(t):
        return "Running, and ready. What's the job?"
    if standalone and _OK.match(t):
        return "Right."
    if _CAPABILITY.match(t):
        return (f"{name} works your computer for you: files and folders, PDFs and scans, spreadsheets and "
                "documents, the browser, and apps like Notepad and Calculator. Describe the result you want "
                "and I'll plan it, ask before anything that changes or sends something, and check the work.")
    if _EMOJI_ONLY.match(t):
        return "Hi. What would you like done?"
    if looks_like_typing_noise(t):
        return "I didn't catch that. What would you like done?"
    return None


def is_conversation(text: str, standalone: bool = True) -> bool:
    """True when the message is talk rather than work, but has no canned answer.

    These get one short model call with no tools. Deliberately narrow: short,
    no work smell, not an instruction, and never inside an existing chat -
    "now tell me how long it was" is short and names nothing, but it is asking
    about work already done, and answering it from a chat prompt with no access
    to that work is how a model invents an answer.
    """
    t = _first_line(text)
    if not standalone or not t or smells_like_work(t):
        return False
    if len(t.split()) > _MAX_CHAT_WORDS:
        return False
    return True


CHAT_SYSTEM = (
    "You are {name}, talking to the person who uses you. This message is conversation, "
    "not a job: answer it in one or two short sentences and stop. Do not describe steps, "
    "do not claim to have done anything, and do not offer a list of what you can do unless "
    "you are asked. If they seem to want work done but have not said what, ask what they want."
)
