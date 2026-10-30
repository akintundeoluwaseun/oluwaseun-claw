"""Application settings: schema, validation, and persistence.

Settings live in a JSON file inside the per-user data directory. Every load is
validated with Pydantic and any problem is turned into a plain-English message
that the desktop UI can show directly.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from claw.permissions.policy import DEFAULT_MODES, Decision, RiskLevel

log = logging.getLogger("claw.config")

SETTINGS_FILENAME = "settings.json"
SETTINGS_VERSION = 1

ProviderName = Literal["ollama", "openai_compatible"]

DEFAULT_BASE_URLS: dict[str, str] = {
    "ollama": "http://127.0.0.1:11434",
    # llama.cpp's `llama-server` default address.
    "openai_compatible": "http://127.0.0.1:8080",
}


class ConfigError(Exception):
    """A settings problem described in words a non-developer can act on."""

    def __init__(self, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.problems = problems or []


#: Where settings, task history and downloaded brains live. The product was
#: called "Oluwaseun Claw" before it was called S-CLAW; the old folders are
#: listed so an existing install keeps everything it had.
APP_DIR_WINDOWS = "S-CLAW"
APP_DIR_UNIX = ".s-claw"
LEGACY_DIR_WINDOWS = ("OluwaseunClaw",)
LEGACY_DIR_UNIX = (".oluwaseun-claw",)


def _adopt_old_data(old: Path, new: Path) -> None:
    """Carry a previous version's folder over to the new name.

    A rename is atomic, so either the whole folder arrives or nothing moves.
    When it cannot be renamed - a different drive, a file held open, a
    permission - the contents are copied and **the original is left exactly
    where it is**. Losing someone's task history to a tidier folder name would
    be the worst possible trade.
    """
    try:
        os.replace(old, new)
        log.info("data folder moved from %s to %s", old, new)
        return
    except OSError as exc:
        log.warning("data folder could not be renamed (%s); copying instead", exc)
    try:
        shutil.copytree(old, new, dirs_exist_ok=False)
        (new / "MOVED-FROM.txt").write_text(
            f"Copied from {old} when the app was renamed to S-CLAW.\n"
            "The original folder was left in place; delete it once you are satisfied.\n",
            encoding="utf-8")
        log.info("data folder copied from %s to %s; the original was kept", old, new)
    except OSError as exc:
        # Starting fresh is bad; starting fresh *silently* is worse.
        log.error("data folder at %s could not be carried over (%s); S-CLAW will start "
                  "with empty settings and the old folder is untouched", old, exc)


def default_data_dir() -> Path:
    override = os.environ.get("CLAW_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        name, legacy = APP_DIR_WINDOWS, LEGACY_DIR_WINDOWS
    else:
        base, name, legacy = Path.home(), APP_DIR_UNIX, LEGACY_DIR_UNIX
    new = base / name
    if new.exists():
        return new                     # already on the new name; never merge two folders
    for old_name in legacy:
        old = base / old_name
        if old.is_dir():
            _adopt_old_data(old, new)
            break
    return new


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # How Claw thinks:
    #   builtin — Claw's own brain on this computer; the model is chosen and set up automatically.
    #   service — the Claw service: the hosted brain Claw Online thinks with. Its address and
    #             credential come from the build, so the user types no API key.
    #   cloud   — someone else's hosted model, with the user's own address, model and key.
    #   custom  — developer setting: the provider/address/model below.
    # "cloud", not "online": settings files from 0.3.0 use "online" for something else and
    # are still migrated to builtin below.
    mode: Literal["builtin", "service", "cloud", "custom"] = "builtin"
    selected: str | None = Field(default=None, max_length=80)  # None: Claw picks the best installed brain
    idle_unload_minutes: int = Field(default=10, ge=1, le=240)  # free memory when Claw is quiet

    @field_validator("mode", mode="before")
    @classmethod
    def _old_modes(cls, value):
        # Settings files from 0.3.0 may say unset/online/offline; all of those now mean builtin.
        return "builtin" if value in ("unset", "online", "offline") else value

    # Developer ("custom") settings only. Ollama is an optional adapter, never required.
    provider: ProviderName = "openai_compatible"
    base_url: str = DEFAULT_BASE_URLS["openai_compatible"]
    model: str = Field(default="", max_length=200)
    request_timeout_s: float = Field(default=120.0, ge=5, le=900)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    # Remote model servers are off by default: this app is local-first.
    allow_remote_server: bool = False
    # Cloud mode only. Kept out of logs and masked by the API; it is the user's credential.
    api_key: str = Field(default="", max_length=400, repr=False)

    @model_validator(mode="after")
    def _cloud_needs_an_address_and_model(self) -> "ModelSettings":
        if self.mode == "cloud":
            if urlparse(self.base_url).scheme != "https":
                raise ValueError("an online model needs an https address")
            if not self.model.strip():
                raise ValueError("choose which online model to use")
        return self

    @field_validator("base_url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("must be a full address such as http://127.0.0.1:11434")
        return value

    @field_validator("model")
    @classmethod
    def _check_model(cls, value: str) -> str:
        value = value.strip()
        if any(ch in value for ch in "\r\n\t"):
            raise ValueError("must not contain line breaks or tabs")
        return value

    @model_validator(mode="after")
    def _local_only_unless_allowed(self) -> "ModelSettings":
        host = urlparse(self.base_url).hostname
        # Only "custom" reaches the address in these settings. "builtin" asks the
        # managed brain for an adapter and "service" uses the address compiled into
        # the edition, so for those two this field is never dialled and must not be
        # able to veto a save. It did: someone who had tried an online model still
        # had that provider's address here, the page sent the whole object back when
        # they chose the local brain, and this rule refused it - so the one move that
        # takes a person OFF a remote server was the move it blocked. Choosing
        # "cloud" is itself the decision to use a server elsewhere, so it does not
        # need the developer switch either.
        if self.mode != "custom":
            return self
        if not self.allow_remote_server and not _is_loopback_host(host):
            raise ValueError(
                f"model server address '{self.base_url}' is not on this computer. "
                "Use 127.0.0.1 or localhost, or turn on 'Allow a server on another computer' in Settings → Developer."
            )
        return self


class PermissionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modes: dict[RiskLevel, Decision] = Field(default_factory=lambda: dict(DEFAULT_MODES))
    authorized_folders: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("modes")
    @classmethod
    def _destructive_never_auto(cls, modes: dict[RiskLevel, Decision]) -> dict[RiskLevel, Decision]:
        full = {level: modes.get(level, DEFAULT_MODES[level]) for level in RiskLevel}
        if full[RiskLevel.DESTRUCTIVE] == Decision.ALLOW:
            raise ValueError("destructive actions (deleting, sending, buying) cannot be set to run without asking")
        return full

    @field_validator("authorized_folders")
    @classmethod
    def _absolute_folders(cls, folders: list[str]) -> list[str]:
        cleaned: list[str] = []
        for folder in folders:
            folder = folder.strip()
            if not folder:
                continue
            if not (Path(folder).is_absolute() or _looks_like_windows_absolute(folder)):
                raise ValueError(f"'{folder}' must be a full folder path, e.g. C:\\Users\\You\\Documents")
            if folder not in cleaned:
                cleaned.append(folder)
        return cleaned


def _looks_like_windows_absolute(path: str) -> bool:
    return len(path) >= 3 and path[0].isalpha() and path[1] == ":" and path[2] in "\\/"


BrowserChannel = Literal["msedge", "chrome", "chromium"]
SearchEngine = Literal["duckduckgo", "bing", "searxng", "custom"]


def _default_channel() -> str:
    # Windows 10 ships with Microsoft Edge, so no browser download is needed there.
    return "msedge" if sys.platform == "win32" else "chromium"


class BrowserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: BrowserChannel = Field(default_factory=_default_channel)
    headless: bool = False
    search_engine: SearchEngine = "duckduckgo"
    custom_search_url: str = Field(default="", max_length=500)
    # A SearXNG server the user or their organisation runs. Claw talks to it over
    # HTTP and never bundles it: SearXNG is AGPL-3.0.
    searxng_url: str = Field(default="", max_length=500)
    # Reading the user's own browser history is private: it can be asked for or refused, never automatic.
    history_access: Literal["ask", "deny"] = "ask"
    navigation_timeout_s: float = Field(default=30, ge=5, le=120)

    @model_validator(mode="after")
    def _chosen_engine_has_an_address(self) -> "BrowserSettings":
        if self.search_engine == "custom":
            parsed = urlparse(self.custom_search_url)
            if parsed.scheme not in ("http", "https") or "{query}" not in self.custom_search_url:
                raise ValueError("a custom search address must start with http(s):// and contain {query}")
        if self.search_engine == "searxng":
            parsed = urlparse(self.searxng_url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError("give the address of your SearXNG server, e.g. https://search.example.com")
        return self


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=20, ge=1, le=50)
    step_timeout_s: float = Field(default=60, ge=5, le=600)
    approval_timeout_s: float = Field(default=600, ge=30, le=3600)
    max_consecutive_failures: int = Field(default=3, ge=1, le=10)


class DesktopSettings(BaseModel):
    """How the app behaves on the desktop. Read by the Electron main process."""

    model_config = ConfigDict(extra="forbid")

    start_with_windows: bool = False
    show_quick_bar: bool = True
    keep_awake_while_running: bool = True
    notifications: bool = True
    close_to_tray: bool = True
    #: When to show the morning briefing, as "HH:MM"; empty turns it off. It can
    #: only appear while S-CLAW is running — there is no service behind it, and
    #: a laptop that stayed shut gets no briefing.
    brief_at: str = Field(default="", pattern=r"^$|^([01]?\d|2[0-3]):[0-5]\d$")
    #: "system" follows Windows, which is the right default: most people set
    #: that once and expect every app to respect it.
    theme: Literal["system", "light", "dark"] = "system"
    #: The "what Claw can do" card on the home screen. On until the person has
    #: read it; dismissing it is permanent, because a tour you cannot turn off
    #: stops being a tour and becomes an advert.
    show_tips: bool = True


class DocumentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ocr_language: str = Field(default="eng", pattern=r"^[a-z_]{3,10}(\+[a-z_]{3,10}){0,3}$")


class MessagesSettings(BaseModel):
    """Reading, notifying and sending are separate permissions."""

    model_config = ConfigDict(extra="forbid")

    whatsapp_read: Literal["ask", "allow", "deny"] = "ask"  # tasks that check unread chats
    show_previews: bool = False  # short previews of the last message in unread chats
    check_every_minutes: Literal[0, 15, 30, 60] = 0  # background check (needs whatsapp_read = allow)
    notify: bool = True  # Windows notification when new unread chats appear
    # Sending a message is always a "Deleting, sending, buying" action: it always asks.


class VoiceSettings(BaseModel):
    """The offline command bar. Recognition is local; nothing is uploaded."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False  # off until the user installs a model: no surprise downloads
    model: str | None = Field(default=None, max_length=80)  # None: the one installed model
    # Click-to-record by default. Claw never listens in the background.
    mode: Literal["click", "push_to_talk"] = "click"
    push_to_talk: str = Field(default="Ctrl+Shift+V", max_length=60)
    auto_submit: bool = False  # run the recognised text without a second look
    keep_recordings: bool = False  # opt-in only; off means audio is never written to disk
    input_device: str = Field(default="", max_length=200)  # "" = the system default microphone

    @field_validator("push_to_talk")
    @classmethod
    def _shortcut_shape(cls, v: str) -> str:
        v = v.strip()
        if v and not re.fullmatch(r"(?:(?:Ctrl|Alt|Shift|Super|CommandOrControl)\+){1,3}[A-Za-z0-9]+", v):
            raise ValueError("must look like 'Ctrl+Shift+V'")
        return v


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = SETTINGS_VERSION
    model: ModelSettings = Field(default_factory=ModelSettings)
    permissions: PermissionSettings = Field(default_factory=PermissionSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    desktop: DesktopSettings = Field(default_factory=DesktopSettings)
    documents: DocumentSettings = Field(default_factory=DocumentSettings)
    messages: MessagesSettings = Field(default_factory=MessagesSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)


def describe_validation_error(exc: ValidationError) -> list[str]:
    """Turn a Pydantic error into short, human-readable lines."""
    lines: list[str] = []
    for err in exc.errors():
        where = " → ".join(str(part) for part in err.get("loc", ()) if part != "__root__")
        msg = err.get("msg", "is invalid")
        msg = msg.removeprefix("Value error, ")
        lines.append(f"{where}: {msg}" if where else msg)
    return lines


class SettingsStore:
    """Loads and saves settings atomically in the data directory."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.path = data_dir / SETTINGS_FILENAME

    def load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"The settings file is damaged and could not be read ({self.path}). "
                "Fix it or delete it to start from defaults.",
                [f"line {exc.lineno}, column {exc.colno}: {exc.msg}"],
            ) from exc
        except OSError as exc:
            raise ConfigError(f"The settings file could not be opened ({self.path}): {exc.strerror}") from exc
        return self.validate(raw)

    @staticmethod
    def validate(raw: object) -> Settings:
        try:
            return Settings.model_validate(raw)
        except ValidationError as exc:
            problems = describe_validation_error(exc)
            raise ConfigError("Some settings are not valid.", problems) from exc

    def save(self, settings: Settings) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = settings.model_dump_json(indent=2)
        fd, tmp = tempfile.mkstemp(dir=self.data_dir, prefix=".settings-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
