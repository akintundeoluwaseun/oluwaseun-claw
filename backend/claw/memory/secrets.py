"""Refusing to remember the things that must not be remembered.

This is the first thing memory does, not the last. A filter applied when
showing a memory would already be too late — the secret would be on disk.

What is refused, and why each one:

  credentials     a password, PIN, OTP or API key. S-CLAW never needs one: when
                  something asks for a credential it calls `pause_for_me` and
                  the person types it themselves.
  card numbers    checked with the Luhn algorithm, so an order number or a
                  Nigerian phone number is not mistaken for a card.
  private keys    an SSH or PEM block is unmistakable and catastrophic.
  long random     a 24-character string with no words in it is a token, whatever
                  the sentence around it claims.

What is deliberately *not* refused: phone numbers, e-mail addresses, birthdays,
addresses. Those are what "remember my contacts" means, and a memory that
cannot hold them is not worth having.
"""

from __future__ import annotations

import re

#: Words that make the thing next to them a credential rather than a fact.
CREDENTIAL_WORDS = re.compile(
    r"\b(password|passwd|passcode|pass\s?phrase|pin\s?code|otp|one[-\s]?time\s?(code|password)|"
    r"cvv|cvc|api[-\s]?key|secret\s?key|access\s?token|refresh\s?token|bearer|"
    r"private\s?key|seed\s?phrase|recovery\s?phrase|mnemonic)\b", re.I)
#: A credential word followed by something that looks like its value.
CREDENTIAL_VALUE = re.compile(
    r"(?:password|passwd|passcode|pin|otp|cvv|cvc|key|token|secret)\b\W{0,4}(?:is|:|=|-)?\s*[\"']?(\S{3,})",
    re.I)
KEY_BLOCK = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
#: A run of digits long enough to be a card. Separators are allowed.
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
#: No vowels, no spaces, long: a token wearing a sentence as a disguise.
RANDOM = re.compile(r"\b(?=[A-Za-z0-9+/_=-]{24,})(?=\S*\d)(?=\S*[A-Za-z])\S{24,}\b")
WORDY = re.compile(r"^[A-Za-z][a-z]+([ -][A-Za-z][a-z]+)+$")


def _luhn(digits: str) -> bool:
    total, odd = 0, False
    for ch in reversed(digits):
        n = int(ch)
        if odd:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        odd = not odd
    return total % 10 == 0


def looks_like_secret(text: str) -> str | None:
    """Why this must not be stored, or None if it may be.

    The answer is a sentence for the person, not a code: they are about to be
    told that S-CLAW will not remember something, and they deserve the reason.
    """
    if not text:
        return None
    if KEY_BLOCK.search(text):
        return "that is a private key"
    if CREDENTIAL_WORDS.search(text) and CREDENTIAL_VALUE.search(text):
        return "it looks like a password, a code or a key"
    for match in CARD.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return "it looks like a card number"
    for match in RANDOM.finditer(text):
        if not WORDY.match(match.group(0)):
            return "it contains something that looks like a token or a key"
    return None
