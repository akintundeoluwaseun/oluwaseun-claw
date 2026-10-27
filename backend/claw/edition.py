"""Which edition of Claw this install is, and what that edition is allowed to do.

There is one application. The two editions differ only in what the installer
carries and what the running app may therefore do:

  Claw Online  no model weights, no inference engine. Thinking happens on the
               Claw service; this computer validates and executes every action.
               Needs internet. The user supplies no API key: the service address
               is written into the build.

  Claw Local   carries the llama.cpp engine and one model, and thinks on this
               computer. Works with the network switched off.

The edition is read from resources/edition.json, written by the packaging
profile. A source checkout has no such file and is treated as Local, because a
checkout can build and run the engine.

Nothing here invents a service address. A Claw Online build whose profile
carries no service_url says so plainly and refuses to think, rather than
quietly falling back to a local brain it does not have or to a key the user
never gave.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("claw.edition")

ONLINE, LOCAL = "online", "local"


@dataclass(frozen=True)
class Edition:
    id: str = LOCAL
    name: str = "Claw Local"
    #: may run llama-server on this computer and download model weights
    local_inference: bool = True
    #: the Claw service this build talks to; empty means none was configured
    service_url: str = ""
    #: a token written into the build by whoever operates the service; never typed by the user
    service_token: str = field(default="", repr=False)
    #: the model id the installer carries (Local only)
    bundled_model: str = ""

    @property
    def online(self) -> bool:
        return self.id == ONLINE

    @property
    def default_mode(self) -> str:
        return "service" if self.online else "builtin"

    @property
    def service_configured(self) -> bool:
        return bool(self.service_url)

    def allows_mode(self, mode: str) -> tuple[bool, str]:
        """Whether this edition may think in that mode, and why not when it may not."""
        if mode == "builtin" and not self.local_inference:
            return False, ("Claw Online does not include a brain for this computer. "
                           "Install Claw Local if you want Claw to think offline.")
        if mode == "service" and not self.service_configured:
            return False, ("This copy of Claw was built without a Claw service address, "
                           "so it cannot use the hosted brain. Reinstall Claw Online from a "
                           "build that has one, or choose a different way for Claw to think.")
        return True, ""

    def as_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "online": self.online,
            "local_inference": self.local_inference,
            "service_configured": self.service_configured,
            # The address is shown; the token never leaves the backend.
            "service_url": self.service_url,
            "bundled_model": self.bundled_model,
            "default_mode": self.default_mode,
        }


def _profile_path() -> Path | None:
    if os.environ.get("CLAW_EDITION_FILE"):
        return Path(os.environ["CLAW_EDITION_FILE"])
    if os.environ.get("CLAW_RESOURCES"):
        return Path(os.environ["CLAW_RESOURCES"]) / "edition.json"
    root = Path(__file__).resolve().parents[2]
    for c in (root / "resources" / "edition.json", root / "build" / "edition.json"):
        if c.is_file():
            return c
    return None


def _from_dict(raw: dict) -> Edition:
    kind = str(raw.get("id", LOCAL)).strip().lower()
    if kind not in (ONLINE, LOCAL):
        raise ValueError(f"unknown edition {kind!r}")
    url = str(raw.get("service_url", "")).strip().rstrip("/")
    if url and urlparse(url).scheme != "https":
        # A hosted brain reached over plain http would carry the user's instructions,
        # their documents and the service token in the clear.
        raise ValueError("the Claw service address must be https")
    local_inference = bool(raw.get("local_inference", kind == LOCAL))
    return Edition(
        id=kind,
        name=str(raw.get("name") or ("Claw Online" if kind == ONLINE else "Claw Local"))[:60],
        local_inference=local_inference,
        service_url=url,
        service_token=str(raw.get("service_token", "")),
        bundled_model=str(raw.get("bundled_model", ""))[:80],
    )


@lru_cache(maxsize=1)
def current() -> Edition:
    path = _profile_path()
    if path is None:
        return Edition()                      # a source checkout: the full, local thing
    try:
        return _from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        # A damaged profile must not silently become the other edition.
        log.error("edition profile at %s could not be read (%s); treating this as Claw Local", path, exc)
        return Edition()


def reset_cache() -> None:
    """Tests and the settings reload path; the file does not change while running."""
    current.cache_clear()
