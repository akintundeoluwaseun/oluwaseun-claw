"""Which brain Claw picks, and what that costs.

Section 5 of the audit. Two of its questions are answered by measurement here;
one cannot be answered on this machine at all, and says so.

Measured (research/performance-audit/):

    choosing and starting a model   0.00 s   (phase timings, warm engine)
    loading a 1.2 GB GGUF           1-2 s    (llama.cpp mmaps it, so "loading"
                                              does not read the file; pages
                                              fault in during inference)

So neither selection nor loading is a latency contributor beside a ~20 s
planning call. What these tests pin is that the CHOICE stays sensible.
"""

import pytest

from claw.models.hardware import Hardware
from claw.runtime.catalog import CATALOG, fits, recommended


def machine(ram=None, vram=None, cores=4):
    return Hardware(total_ram_gb=ram, available_ram_gb=ram, cpu_cores=cores,
                    gpu_name="gpu" if vram else None, gpu_vram_gb=vram)


@pytest.mark.parametrize("ram,vram,edition", [
    (4, None, "Light"),
    (8, None, "Standard"),
    (16, None, "Standard"),
    (32, None, "Pro"),
    (16, 8, "Pro"),
    (64, 24, "Pro"),
])
def test_the_brain_chosen_fits_the_machine(ram, vram, edition):
    hw = machine(ram, vram)
    chosen = recommended(hw)
    assert chosen.edition == edition
    assert fits(chosen, hw), "a brain that does not fit must never be recommended"


def test_size_alone_does_not_decide():
    """Pro fits 16 GB of RAM on paper and is still not recommended without a
    GPU, because each reply takes minutes on a laptop processor - which feels
    broken rather than slow. The brief asks for exactly this."""
    assert recommended(machine(16, None)).edition == "Standard"
    assert recommended(machine(16, 8)).edition == "Pro", "a big enough GPU changes it"


def test_an_unknown_machine_is_not_given_the_biggest_brain():
    """RAM detection can fail. Guessing high would hand someone a brain their
    computer cannot run."""
    assert recommended(machine(None, None)).edition == "Standard"


def test_the_tiny_brain_is_never_recommended():
    """It exists so a person can find out that offline thinking runs at all.
    Handing it to someone on a small machine would give them the worst brain
    in the catalogue and call it the best their computer can manage."""
    tiny = next(e for e in CATALOG if e.edition == "Tiny")
    assert tiny.recommendable is False
    for ram in (2, 4, 8, 16, 32):
        assert recommended(machine(ram)).edition != "Tiny"


def test_a_machine_too_small_for_anything_is_a_known_limitation():
    """2 GB fits nothing recommendable, so the smallest recommendable brain is
    returned even though it does not fit. That is deliberate - see
    recommended() - and fits() still reports the truth, so a caller can warn.
    Pinned so the behaviour cannot change silently."""
    hw = machine(2)
    chosen = recommended(hw)
    assert chosen.edition == "Light"
    assert not fits(chosen, hw), "fits() must still say it does not fit"


def test_every_catalogue_entry_is_licensed_for_use():
    from claw.runtime.catalog import ALLOWED_LICENSES
    assert ALLOWED_LICENSES == {"apache-2.0", "mit"}
    assert all(e.repo and e.model_pattern for e in CATALOG)


def test_the_catalogue_is_ordered_by_what_it_needs():
    needs = [e.min_ram_gb for e in CATALOG]
    assert needs == sorted(needs), "a catalogue out of order makes recommended() hard to reason about"
