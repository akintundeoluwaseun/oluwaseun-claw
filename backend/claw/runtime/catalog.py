"""Brains Claw can set up by itself.

Each entry names a public Hugging Face repository, not a file URL: the exact
file names, sizes, SHA-256 checksums and licence are read from Hugging Face's
API at download time, so nothing here is guessed. A model is only offered if
the repository's own licence tag is in ALLOWED_LICENSES.

Both entries are Qwen3-VL "Instruct" models (text + screenshots in one model),
which llama.cpp supports (PROJECTOR_TYPE_QWEN3VL). Sizes and memory needs are
estimates for Q4_K_M weights plus the F16 vision projector.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from claw.models.hardware import Hardware

ALLOWED_LICENSES = {"apache-2.0", "mit"}


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    name: str
    edition: str
    repo: str
    model_pattern: str  # regex on file names (case-insensitive)
    mmproj_pattern: str | None
    approx_download_gb: float
    min_ram_gb: float  # system memory for CPU use
    min_vram_gb: float  # or GPU memory
    description: str

    def as_dict(self) -> dict:
        return asdict(self)


CATALOG = [
    CatalogEntry(
        id="qwen3-vl-4b",
        name="Standard brain",
        edition="Standard",
        repo="Qwen/Qwen3-VL-4B-Instruct-GGUF",
        model_pattern=r"q4_k_m\.gguf$",
        mmproj_pattern=r"mmproj[^/]*f16\.gguf$",
        approx_download_gb=3.3,
        min_ram_gb=8,
        min_vram_gb=4,
        description="For everyday laptops with 8 GB of memory or more. Reads screenshots.",
    ),
    CatalogEntry(
        id="qwen3-vl-8b",
        name="Pro brain",
        edition="Pro",
        repo="Qwen/Qwen3-VL-8B-Instruct-GGUF",
        model_pattern=r"q4_k_m\.gguf$",
        mmproj_pattern=r"mmproj[^/]*f16\.gguf$",
        approx_download_gb=6.2,
        min_ram_gb=14,
        min_vram_gb=8,
        description="Smarter and slower. For computers with 16 GB of memory or a graphics card with 8 GB.",
    ),
]


def get(entry_id: str) -> CatalogEntry | None:
    return next((e for e in CATALOG if e.id == entry_id), None)


def fits(entry: CatalogEntry, hw: Hardware) -> bool:
    if hw.gpu_vram_gb is not None and hw.gpu_vram_gb >= entry.min_vram_gb:
        return True
    # Windows reports an "8 GB" laptop as ~7.7–7.9 GB after reserved memory, so allow half a GB.
    return (hw.total_ram_gb if hw.total_ram_gb is not None else 8.0) + 0.5 >= entry.min_ram_gb


def recommended(hw: Hardware) -> CatalogEntry:
    """The largest brain that fits; the Standard brain if nothing clearly fits."""
    fitting = [e for e in CATALOG if fits(e, hw)]
    return max(fitting, key=lambda e: e.min_ram_gb) if fitting else CATALOG[0]
