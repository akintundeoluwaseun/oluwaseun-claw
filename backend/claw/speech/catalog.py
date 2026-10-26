"""Voice models Claw can set up by itself.

Like the brain catalog, an entry names a public Hugging Face repository rather
than file URLs: the exact names, sizes, SHA-256 checksums and licence are read
from the API at download time (claw.runtime.hub), so no checksum is written
here and a wrong or relicensed repository fails with a clear message instead of
installing something unexpected.

All three are Whisper weights exported for sherpa-onnx. Whisper is MIT and the
sherpa-onnx runtime is Apache-2.0; the licence is still checked at download.

Accuracy note: these are general English/multilingual models. None of them is
tuned for Nigerian English, and Claw does not claim a figure for it --
docs/VOICE_NIGERIAN_ENGLISH.md holds the measurement plan.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

ALLOWED_LICENSES = {"apache-2.0", "mit"}

# The files sherpa-onnx needs for a Whisper export. Quantised (.int8) weights are
# preferred: _pick() takes the smallest match, which is the int8 one when present.
WHISPER_FILES = {
    "encoder": r"encoder.*\.onnx$",
    "decoder": r"decoder.*\.onnx$",
    "tokens": r"tokens\.txt$",
}


@dataclass(frozen=True)
class VoiceModel:
    id: str
    name: str
    engine: str  # which SpeechEngine can run it
    repo: str
    files: dict[str, str]  # role -> regex on file names
    languages: list[str]
    approx_download_mb: int
    min_ram_gb: float
    speed: str  # plain words, shown in Settings
    description: str

    def as_dict(self) -> dict:
        return asdict(self)


CATALOG: list[VoiceModel] = [
    VoiceModel(
        id="whisper-tiny-en",
        name="Quick (English)",
        engine="sherpa-onnx",
        repo="csukuangfj/sherpa-onnx-whisper-tiny.en",
        files=WHISPER_FILES,
        languages=["en"],
        approx_download_mb=120,
        min_ram_gb=2,
        speed="Fastest, least accurate",
        description="Short English commands on any laptop. Struggles with names and noise.",
    ),
    VoiceModel(
        id="whisper-base",
        name="Balanced",
        engine="sherpa-onnx",
        repo="csukuangfj/sherpa-onnx-whisper-base",
        files=WHISPER_FILES,
        languages=["en", "multilingual"],
        approx_download_mb=250,
        min_ram_gb=4,
        speed="Fast",
        description="The usual choice: handles everyday instructions and most names.",
    ),
    VoiceModel(
        id="whisper-small",
        name="Most accurate",
        engine="sherpa-onnx",
        repo="csukuangfj/sherpa-onnx-whisper-small",
        files=WHISPER_FILES,
        languages=["en", "multilingual"],
        approx_download_mb=900,
        min_ram_gb=6,
        speed="Slower, a second or two per command",
        description="Best with accents, product names and background noise. Needs more memory.",
    ),
]

DEFAULT_ID = "whisper-base"


def get(model_id: str) -> VoiceModel | None:
    return next((m for m in CATALOG if m.id == model_id), None)


def fits(model: VoiceModel, total_ram_gb: float | None) -> bool:
    # Windows reports an "8 GB" laptop as ~7.7 GB after reserved memory, so allow half a GB.
    return (total_ram_gb if total_ram_gb is not None else 8.0) + 0.5 >= model.min_ram_gb


def recommended(total_ram_gb: float | None) -> VoiceModel:
    """The default if it fits, otherwise the largest that does."""
    default = get(DEFAULT_ID)
    if default and fits(default, total_ram_gb):
        return default
    fitting = [m for m in CATALOG if fits(m, total_ram_gb)]
    return max(fitting, key=lambda m: m.min_ram_gb) if fitting else CATALOG[0]
