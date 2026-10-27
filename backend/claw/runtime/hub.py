"""Download model files from Hugging Face, with checks.

- File list, sizes, SHA-256 and licence come from the public API
  (GET /api/models/{repo}?blobs=true), never from hard-coded values.
- Refuses repositories whose licence is not on the allowed list.
- Checks free disk space first, downloads to a .part file (resumable),
  verifies SHA-256 when the API provides it, then renames into place.
- Only https://huggingface.co is used. Tests may point CLAW_HF_BASE at a
  local stand-in server; any non-localhost override is ignored.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from claw.runtime.catalog import ALLOWED_LICENSES, CatalogEntry

HF_BASE = "https://huggingface.co"
DISK_MARGIN_BYTES = 1 * 1024**3


def hub_base() -> str:
    override = os.environ.get("CLAW_HF_BASE", "")
    if override and urlparse(override).hostname in ("127.0.0.1", "localhost"):
        return override.rstrip("/")
    return HF_BASE


class DownloadError(Exception):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass
class RemoteFile:
    name: str
    size: int
    sha256: str | None


@dataclass
class ResolvedModel:
    repo: str
    license: str
    model: RemoteFile
    mmproj: RemoteFile | None

    @property
    def total_bytes(self) -> int:
        return self.model.size + (self.mmproj.size if self.mmproj else 0)


def _license(info: dict) -> str:
    card = info.get("cardData") or {}
    lic = card.get("license")
    if not lic:
        lic = next((t.split(":", 1)[1] for t in info.get("tags", []) if t.startswith("license:")), "")
    return str(lic or "unknown").lower()


def _pick(siblings: list[dict], pattern: str, exclude_mmproj: bool) -> RemoteFile | None:
    rx = re.compile(pattern, re.I)
    found = []
    for s in siblings:
        name = s.get("rfilename", "")
        if exclude_mmproj and "mmproj" in name.lower():
            continue
        if rx.search(name):
            lfs = s.get("lfs") or {}
            found.append(RemoteFile(name, int(s.get("size") or lfs.get("size") or 0), lfs.get("sha256")))
    return min(found, key=lambda f: f.size) if found else None


async def _model_info(repo: str, label: str, client: httpx.AsyncClient | None) -> dict:
    url = f"{hub_base()}/api/models/{repo}?blobs=true"
    own = client is None
    client = client or httpx.AsyncClient(timeout=30, follow_redirects=True)
    try:
        try:
            r = await client.get(url)
        except httpx.HTTPError as exc:
            raise DownloadError("Could not reach the model library (Hugging Face).", "Check the internet connection.") from exc
        if r.status_code == 404:
            raise DownloadError(f"The model library no longer has {repo}.")
        if r.status_code >= 400:
            raise DownloadError(f"The model library answered with an error ({r.status_code}).")
        return r.json()
    finally:
        if own:
            await client.aclose()


async def resolve(entry: CatalogEntry, client: httpx.AsyncClient | None = None) -> ResolvedModel:
    info = await _model_info(entry.repo, entry.name, client)
    lic = _license(info)
    if lic not in ALLOWED_LICENSES:
        raise DownloadError(f"{entry.name} is published under '{lic}', which Claw can't use without permission.")
    siblings = info.get("siblings") or []
    model = _pick(siblings, entry.model_pattern, exclude_mmproj=True)
    if model is None:
        raise DownloadError(f"No suitable model file was found in {entry.repo}.")
    mmproj = _pick(siblings, entry.mmproj_pattern, exclude_mmproj=False) if entry.mmproj_pattern else None
    return ResolvedModel(entry.repo, lic, model, mmproj)


async def resolve_many(repo: str, patterns: dict[str, str], *, label: str,
                       allowed: set[str], client: httpx.AsyncClient | None = None) -> tuple[str, dict[str, RemoteFile]]:
    """Resolve several files from one repository (e.g. a speech model's encoder, decoder and tokens).

    Same rules as resolve(): the file list, sizes, SHA-256 and licence come from
    the public API, and a licence that is not allowed stops the download.
    """
    info = await _model_info(repo, label, client)
    lic = _license(info)
    if lic not in allowed:
        raise DownloadError(f"{label} is published under '{lic}', which Claw can't use without permission.")
    siblings = info.get("siblings") or []
    out: dict[str, RemoteFile] = {}
    for key, pattern in patterns.items():
        found = _pick(siblings, pattern, exclude_mmproj=False)
        if found is None:
            raise DownloadError(f"{label} is incomplete in the model library: no file matching '{pattern}'.")
        out[key] = found
    return lic, out


def check_disk(folder: Path, needed: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(folder).free
    if free < needed + DISK_MARGIN_BYTES:
        raise DownloadError(
            f"Not enough disk space: the brain needs {needed / 1024**3:.1f} GB and only {free / 1024**3:.1f} GB is free.",
            "Free up space on this drive and try again.",
        )


Progress = Callable[[int, int], None]


async def download_file(repo: str, f: RemoteFile, dest: Path, progress: Progress, cancel: asyncio.Event,
                        client: httpx.AsyncClient | None = None) -> bool:
    """Returns True if a checksum was verified. Raises DownloadError on any problem."""
    url = f"{hub_base()}/{repo}/resolve/main/{quote(f.name)}"
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(30, read=120), follow_redirects=True)
    try:
        async with client.stream("GET", url, headers=headers) as r:
            if r.status_code == 416:  # already complete
                pass
            elif r.status_code not in (200, 206):
                raise DownloadError(f"Download failed ({r.status_code}) for {f.name}.")
            else:
                if r.status_code == 200:
                    have = 0  # server ignored the range: start over
                with open(part, "ab" if have else "wb") as fh:
                    async for chunk in r.aiter_bytes(1 << 20):
                        if cancel.is_set():
                            raise DownloadError("Download cancelled. It will continue from here next time.")
                        fh.write(chunk)
                        have += len(chunk)
                        progress(have, f.size)
    except httpx.HTTPError as exc:
        raise DownloadError("The download was interrupted. Try again to continue where it stopped.") from exc
    finally:
        if own:
            await client.aclose()
    if f.size and part.stat().st_size != f.size:
        raise DownloadError(f"{f.name} is incomplete ({part.stat().st_size:,} of {f.size:,} bytes). Try again.")
    verified = False
    if f.sha256:
        digest = await asyncio.to_thread(_sha256, part)
        if digest != f.sha256.lower():
            part.unlink(missing_ok=True)
            raise DownloadError(f"{f.name} failed its integrity check and was deleted. Try downloading again.")
        verified = True
    part.replace(dest)
    return verified


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()
