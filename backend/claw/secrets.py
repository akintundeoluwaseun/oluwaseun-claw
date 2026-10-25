"""Store small secrets (the user's AI key) outside settings.json.

On Windows the value is encrypted with DPAPI (CryptProtectData), which ties it
to the signed-in Windows user: another account, or a copy of the file on
another computer, cannot decrypt it. On other systems (development only) the
file is written with owner-only permissions.

Secrets are never logged and never returned by the local API.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
import tempfile
from pathlib import Path

from claw.logging_setup import register_secret

FILENAME = "secrets.bin"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    buf = ctypes.create_string_buffer(data, len(data))
    src = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(out))  # CRYPTPROTECT_UI_FORBIDDEN
    if not ok:
        raise OSError("Windows could not protect the stored key.")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


class SecretStore:
    def __init__(self, data_dir: Path):
        self.path = data_dir / FILENAME
        self._cache: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
        if self._cache is not None:
            return self._cache
        values: dict[str, str] = {}
        if self.path.exists():
            raw = self.path.read_bytes()
            try:
                if sys.platform == "win32":
                    raw = _dpapi(raw, protect=False)
                else:
                    raw = base64.b64decode(raw)
                values = json.loads(raw.decode("utf-8"))
            except (OSError, ValueError):
                values = {}  # unreadable (e.g. copied from another user): treat as empty
        for v in values.values():
            register_secret(v)
        self._cache = values
        return values

    def get(self, name: str) -> str | None:
        return self._load().get(name)

    def set(self, name: str, value: str | None) -> None:
        values = dict(self._load())
        if value:
            values[name] = value
            register_secret(value)
        else:
            values.pop(name, None)
        payload = json.dumps(values).encode("utf-8")
        payload = _dpapi(payload, protect=True) if sys.platform == "win32" else base64.b64encode(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".secrets-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
            if sys.platform != "win32":
                os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self._cache = values


def hint(value: str | None) -> str | None:
    """Show only the last 4 characters, e.g. '••••a1B2'."""
    if not value:
        return None
    return "••••" + value[-4:]
