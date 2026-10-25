"""Application settings: schema, validation, and persistence.

Settings live in a JSON file inside the per-user data directory. Every load is
validated with Pydantic and any problem is turned into a plain-English message
that the desktop UI can show directly.
"""

from __future__ import annotations

import ipaddress
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from claw.permissions.policy import DEFAULT_MODES, Decision, RiskLevel

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


def default_data_dir() -> Path:
    override = os.environ.get("CLAW_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "OluwaseunClaw"
    return Path.home() / ".oluwaseun-claw"


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

    # Automatic: Claw measures the computer, picks models by role, and downloads them itself.
    # Turning this off (Settings → Advanced) uses the provider/model chosen below.
    auto: bool = True
    provider: ProviderName = "ollama"
    base_url: str = DEFAULT_BASE_URLS["ollama"]
    model: str = Field(default="", max_length=200)
    request_timeout_s: float = Field(default=120.0, ge=5, le=900)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    # Remote model servers are off by default: this app is local-first.
    allow_remote_server: bool = False

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
        if not self.allow_remote_server and not _is_loopback_host(host):
            raise ValueError(
                f"model server address '{self.base_url}' is not on this computer. "
                "Use 127.0.0.1/localhost, or turn on 'Allow remote model server' in Settings."
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
SearchEngine = Literal["duckduckgo", "bing", "custom"]


def _default_channel() -> str:
    # Windows 10 ships with Microsoft Edge, so no browser download is needed there.
    return "msedge" if sys.platform == "win32" else "chromium"


class BrowserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: BrowserChannel = Field(default_factory=_default_channel)
    headless: bool = False
    search_engine: SearchEngine = "duckduckgo"
    custom_search_url: str = Field(default="", max_length=500)
    # Reading the user's own browser history is private: it can be asked for or refused, never automatic.
    history_access: Literal["ask", "deny"] = "ask"
    navigation_timeout_s: float = Field(default=30, ge=5, le=120)

    @model_validator(mode="after")
    def _custom_needs_url(self) -> "BrowserSettings":
        if self.search_engine == "custom":
            parsed = urlparse(self.custom_search_url)
            if parsed.scheme not in ("http", "https") or "{query}" not in self.custom_search_url:
                raise ValueError("a custom search address must start with http(s):// and contain {query}")
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


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = SETTINGS_VERSION
    model: ModelSettings = Field(default_factory=ModelSettings)
    permissions: PermissionSettings = Field(default_factory=PermissionSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    desktop: DesktopSettings = Field(default_factory=DesktopSettings)


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
