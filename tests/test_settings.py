import pytest

from src.config.settings import Settings, SettingsError


def test_settings_use_safe_defaults() -> None:
    settings = Settings.from_env({})

    assert settings.app_env == "development"
    assert settings.dry_run is True
    assert settings.log_level == "INFO"


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "FALSE"])
def test_settings_accept_false_values(value: str) -> None:
    assert Settings.from_env({"DRY_RUN": value}).dry_run is False


def test_settings_reject_invalid_dry_run() -> None:
    with pytest.raises(SettingsError, match="DRY_RUN"):
        Settings.from_env({"DRY_RUN": "talvez"})


def test_settings_reject_invalid_log_level() -> None:
    with pytest.raises(SettingsError, match="LOG_LEVEL"):
        Settings.from_env({"LOG_LEVEL": "TRACE"})


def test_settings_load_worker_credentials() -> None:
    settings = Settings.from_env(
        {
            "POSTGRES_URL": "postgresql://example",
            "FIREBASE_PROJECT_ID": "astro-example",
            "FIREBASE_CREDENTIALS_BASE64": "encoded-value",
        }
    )

    assert settings.postgres_url == "postgresql://example"
    assert settings.firebase_project_id == "astro-example"
    assert settings.firebase_credentials_base64 == "encoded-value"


def test_settings_require_rejects_missing_worker_configuration() -> None:
    with pytest.raises(SettingsError, match="POSTGRES_URL"):
        Settings.require(None, "POSTGRES_URL")
