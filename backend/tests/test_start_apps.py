"""Starting any app in the Start menu, Store apps included (approach from Windows-MCP, MIT)."""

import sys

import pytest

from claw.computer import launcher


def test_store_apps_are_found_and_started_through_the_apps_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "start_menu_dirs", lambda: [tmp_path])
    monkeypatch.setattr(launcher, "start_apps", lambda refresh=False: {
        "WhatsApp": "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
        "Adobe Photoshop 2025": r"{6D809377-6AF0-444B-8957-A3773F02200E}\Adobe\Adobe Photoshop 2025\Photoshop.exe",
        "Windows PowerShell": "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe",
    })
    wa = launcher.choose_app("WhatsApp")
    assert wa.target == r"shell:AppsFolder\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"
    assert launcher.choose_app("photoshop").name == "Adobe Photoshop 2025"
    with pytest.raises(Exception):
        launcher.choose_app("powershell")          # system tools stay refused


@pytest.mark.skipif(sys.platform != "win32", reason="Get-StartApps exists on Windows only")
def test_get_startapps_really_lists_apps_on_windows():
    apps = launcher.start_apps(refresh=True)
    assert len(apps) > 5, apps
