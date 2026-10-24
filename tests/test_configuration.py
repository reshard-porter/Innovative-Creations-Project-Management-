import pytest

from innovative import create_app


def test_sqlite_data_and_generated_key_survive_restart(tmp_path):
    config = {
        "TESTING": True,
        "SECRET_KEY": None,
        "DATABASE_BACKEND": "sqlite",
        "INSTANCE_PATH": str(tmp_path),
        "DATABASE": str(tmp_path / "persistent.sqlite3"),
    }
    first = create_app(config)
    record = first.extensions["store"].create(
        "users", {"email_key": "persist@example.test", "username_key": "persist"}
    )
    second = create_app(config)
    assert second.config["SECRET_KEY"] == first.config["SECRET_KEY"]
    assert (
        second.extensions["store"].get("users", record["id"])["email_key"] == "persist@example.test"
    )
    assert len(second.config["SECRET_KEY"]) >= 32


def test_production_configuration_fails_early_without_required_settings(tmp_path):
    with pytest.raises(ValueError, match="SECRET_KEY"):
        create_app({"APP_ENV": "production", "SECRET_KEY": None, "INSTANCE_PATH": str(tmp_path)})


def test_production_uses_https_cookie_and_hsts(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "production",
            "SECRET_KEY": "a-random-production-test-value-1234567890",
            "APP_BASE_URL": "https://creations.example.test",
            "AUTH_MAIL_MODE": "smtp",
            "SMTP_HOST": "mail.example.test",
            "SMTP_FROM": "hello@example.test",
            "DATABASE_BACKEND": "sqlite",
            "INSTANCE_PATH": str(tmp_path),
            "DATABASE": str(tmp_path / "prod.sqlite3"),
        }
    )
    response = app.test_client().get("/login")
    assert "Secure" in response.headers["Set-Cookie"]
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000"
