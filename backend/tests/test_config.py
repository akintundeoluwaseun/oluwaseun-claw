import pytest

from claw.config import ConfigError, Settings, SettingsStore
from claw.permissions.policy import Decision, RiskLevel


def test_defaults_are_local_and_safe():
    s = Settings()
    assert s.model.mode == "builtin" and s.model.base_url == "http://127.0.0.1:8080"
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
        SettingsStore.validate({"model": {"provider": "ollama", "not_a_real_setting": "x"}})
    with pytest.raises(ConfigError):
        SettingsStore.validate({"made_up_section": {}})
    # api_key is a real field now (cloud mode), so it must be accepted.
    assert SettingsStore.validate({"model": {"api_key": "x"}}).model.api_key == "x"


def test_desktop_defaults_and_old_files_still_load(tmp_path):
    (tmp_path / "settings.json").write_text('{"version": 1, "model": {"model": "qwen2.5:7b"}}')
    s = SettingsStore(tmp_path).load()
    assert s.desktop.show_quick_bar and s.desktop.keep_awake_while_running and not s.desktop.start_with_windows


# ---------- cloud mode: a hosted model instead of a brain on this computer ----------
def test_cloud_mode_needs_https_and_a_model():
    ok = SettingsStore.validate({"model": {"mode": "cloud", "base_url": "https://api.example.com/v1",
                                           "model": "some-model", "api_key": "k"}})
    assert ok.model.mode == "cloud" and ok.model.base_url == "https://api.example.com/v1"
    with pytest.raises(ConfigError):  # plain http would send the key in the clear
        SettingsStore.validate({"model": {"mode": "cloud", "base_url": "http://api.example.com", "model": "m"}})
    with pytest.raises(ConfigError):  # which model is not optional
        SettingsStore.validate({"model": {"mode": "cloud", "base_url": "https://api.example.com", "model": "  "}})


def test_cloud_mode_does_not_need_the_developer_switch():
    """Choosing a hosted model is the consent; it should not also demand a hidden toggle."""
    s = SettingsStore.validate({"model": {"mode": "cloud", "base_url": "https://api.example.com",
                                          "model": "m", "api_key": "k"}})
    assert s.model.allow_remote_server is False  # still off, and still irrelevant to cloud


def test_other_modes_stay_on_this_computer():
    with pytest.raises(ConfigError):
        SettingsStore.validate({"model": {"mode": "custom", "base_url": "https://elsewhere.example", "model": "m"}})


def test_an_api_key_is_never_in_the_settings_repr():
    s = SettingsStore.validate({"model": {"mode": "cloud", "base_url": "https://api.example.com",
                                          "model": "m", "api_key": "sk-secret-value-123"}})
    assert "sk-secret-value-123" not in repr(s)
    assert "sk-secret-value-123" not in repr(s.model)


def test_settings_from_0_3_0_still_mean_the_built_in_brain():
    """Those files used 'online' for something else; it must not become cloud mode."""
    for old in ("unset", "online", "offline"):
        assert SettingsStore.validate({"model": {"mode": old}}).model.mode == "builtin"
