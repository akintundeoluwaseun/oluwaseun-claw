import pytest

from claw.config import ConfigError, Settings, SettingsStore
from claw.permissions.policy import Decision, RiskLevel


def test_defaults_are_local_and_safe():
    s = Settings()
    assert s.model.base_url == "http://127.0.0.1:11434"
    assert s.permissions.modes[RiskLevel.DESTRUCTIVE] == Decision.ASK
    assert s.permissions.modes[RiskLevel.READ_ONLY] == Decision.ALLOW


def test_missing_file_gives_defaults(tmp_path):
    assert SettingsStore(tmp_path).load() == Settings()


def test_save_and_reload_roundtrip(tmp_path):
    store = SettingsStore(tmp_path)
    s = Settings.model_validate({"model": {"model": "qwen2.5:7b"}})
    store.save(s)
    assert store.load().model.model == "qwen2.5:7b"
    assert not list(tmp_path.glob(".settings-*.tmp"))


def test_damaged_json_is_explained(tmp_path):
    (tmp_path / "settings.json").write_text("{ not json")
    with pytest.raises(ConfigError) as exc:
        SettingsStore(tmp_path).load()
    assert "damaged" in exc.value.message
    assert exc.value.problems


def test_remote_model_server_rejected_by_default():
    with pytest.raises(ConfigError) as exc:
        SettingsStore.validate({"model": {"base_url": "http://203.0.113.5:11434"}})
    assert any("not on this computer" in p for p in exc.value.problems)


def test_remote_model_server_allowed_when_opted_in():
    s = SettingsStore.validate({"model": {"base_url": "http://203.0.113.5:11434", "allow_remote_server": True}})
    assert s.model.allow_remote_server


def test_bad_url_message_is_readable():
    with pytest.raises(ConfigError) as exc:
        SettingsStore.validate({"model": {"base_url": "localhost"}})
    assert any("model → base_url" in p and "full address" in p for p in exc.value.problems)


def test_destructive_cannot_be_auto_allowed():
    with pytest.raises(ConfigError) as exc:
        SettingsStore.validate({"permissions": {"modes": {"destructive": "allow"}}})
    assert any("destructive" in p for p in exc.value.problems)


def test_relative_folder_rejected():
    with pytest.raises(ConfigError):
        SettingsStore.validate({"permissions": {"authorized_folders": ["Documents"]}})


def test_windows_style_folder_accepted():
    s = SettingsStore.validate({"permissions": {"authorized_folders": ["C:\\Users\\Seun\\Documents"]}})
    assert s.permissions.authorized_folders == ["C:\\Users\\Seun\\Documents"]


def test_unknown_keys_rejected():
    with pytest.raises(ConfigError):
        SettingsStore.validate({"model": {"provider": "ollama", "api_key": "x"}})
