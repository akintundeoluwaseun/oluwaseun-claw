"""Putting a program on the computer, with the person agreeing to it.

Claw could open an app that was already installed and could not install one,
which is a strange limit on something whose job is to work the computer.

What these tests hold it to:
  - it always asks (destructive risk, which the policy will not downgrade);
  - it installs from the official catalogue and refuses a file or a link;
  - it checks afterwards, because the package manager saying "success" and
    the program being on the machine are two different claims.
"""

from __future__ import annotations

import os
import shutil
import sys

import pytest

from claw.agent.schemas import Capability
from claw.permissions.policy import Decision, PermissionPolicy, RiskLevel
from claw.tools.base import ToolError
from claw.tools.install_tools import check_id, parse_winget_table
from claw.tools.registry import build_registry
from tests.test_phase_a import call


# ---------- it must always ask ----------
def test_installing_is_destructive_and_cannot_be_made_silent():
    reg = build_registry()
    spec = reg.get("install_app")
    assert spec.risk is RiskLevel.DESTRUCTIVE, "installing would happen without asking"
    assert spec.capability is Capability.DESKTOP

    # And the policy refuses to let destructive mean "allow", so there is no
    # setting that turns installing into something that happens behind them.
    policy = PermissionPolicy({RiskLevel.DESTRUCTIVE: Decision.ALLOW}, [])
    assert policy.modes[RiskLevel.DESTRUCTIVE] is Decision.ASK


def test_the_approval_card_names_the_exact_package():
    """Not the word the person typed, and not the brain's paraphrase."""
    from claw.tools.install_tools import InstallArgs
    spec = build_registry().get("install_app")
    said = spec.context_for(InstallArgs(package_id="VideoLAN.VLC"), None)
    assert "VideoLAN.VLC" in said
    assert "official" in said


def test_finding_out_what_is_on_offer_installs_nothing():
    spec = build_registry().get("find_app_to_install")
    assert spec.risk is RiskLevel.READ_ONLY


# ---------- what it will and will not accept ----------
def test_an_installer_file_or_a_link_is_refused():
    """"Install this .exe I found" is how a machine gets what it did not want."""
    for bad in ("https://example.com/setup.exe", "setup.exe", "thing.msi",
                "C:/Downloads/installer.msix", "http://example.com/x"):
        with pytest.raises(ToolError, match="(?i)official catalogue|installer"):
            check_id(bad)


def test_a_second_command_cannot_be_smuggled_into_the_name():
    for bad in ("vlc; rm -rf /", "vlc && shutdown", "vlc | more", "vlc`whoami`",
                "vlc $(id)", "../../etc/passwd", "vlc\nshutdown"):
        with pytest.raises(ToolError, match="(?i)not a package name|installer"):
            check_id(bad)


def test_ordinary_package_ids_are_accepted():
    for good in ("vlc", "VideoLAN.VLC", "7zip.7zip", "libreoffice-calc",
                 "Microsoft.PowerToys", "python3.12"):
        assert check_id(good) == good


def test_windows_itself_is_not_something_claw_installs():
    with pytest.raises(ToolError, match="(?i)for you to do yourself"):
        check_id("windows")


# ---------- reading winget's output ----------
def test_wingets_table_is_read_correctly():
    out = (
        "Name               Id                     Version      Source\n"
        "-----------------------------------------------------------------\n"
        "VLC media player   VideoLAN.VLC           3.0.21       winget\n"
        "7-Zip              7zip.7zip              24.09        winget\n")
    rows = parse_winget_table(out)
    assert [r["id"] for r in rows] == ["VideoLAN.VLC", "7zip.7zip"]
    assert rows[0]["name"] == "VLC media player" and rows[0]["version"] == "3.0.21"


def test_no_results_reads_as_no_results():
    assert parse_winget_table("No package found matching input criteria.") == []
    assert parse_winget_table("") == []


# ---------- really installing something, on this machine ----------
@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("apt-get"),
                    reason="needs apt; the Windows path is winget and is exercised on the build runner")
async def test_a_package_already_present_is_not_installed_again(tool_ctx):
    """Reported honestly rather than run again for show."""
    r = await call(tool_ctx, "install_app", package_id="coreutils")
    assert r.ok and r.verified
    assert r.data["already"] is True
    assert "already installed" in r.summary


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("apt-get"),
                    reason="needs apt")
async def test_a_package_that_does_not_exist_fails_honestly(tool_ctx):
    """The package manager's exit code is not the question; the machine is."""
    r = await call(tool_ctx, "install_app", package_id="claw-no-such-package-xyz")
    assert not r.ok and not r.verified
    assert "did NOT install" in r.summary
    assert r.data["installed"] is False


@pytest.mark.skipif(
    not os.environ.get("CLAW_TEST_REAL_INSTALL") or sys.platform == "win32"
    or not shutil.which("apt-get"),
    reason="really installs a package; set CLAW_TEST_REAL_INSTALL=1 to run it")
async def test_a_real_package_really_installs(tool_ctx):
    """The whole path, for real: look it up, install it, confirm it is there.

    Off by default because it changes the machine and needs the network.
    Run deliberately with CLAW_TEST_REAL_INSTALL=1. It was run while this
    was written: cowsay went from absent to /usr/games/cowsay and ran.

    Note for anyone extending this: shutil.which is the WRONG check. cowsay
    installs into /usr/games, which is not on PATH in a service's
    environment, so which() says no while the package is perfectly well
    installed. The tool asks the package manager, which is the thing that
    actually knows.
    """
    package = os.environ.get("CLAW_TEST_REAL_INSTALL_PACKAGE", "sl")
    r = await call(tool_ctx, "install_app", package_id=package)
    assert r.ok and r.verified, r.summary
    assert r.data["installed"] is True

    # And asking again is a no-op that says so, rather than installing twice.
    again = await call(tool_ctx, "install_app", package_id=package)
    assert again.data["already"] is True
