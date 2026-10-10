from app.api.routes.auth import _DUMMY_PASSWORD_HASH
from app.auth.security import is_secure_auth_secret, verify_password


def test_auth_secret_rejects_defaults_and_short_values() -> None:
    assert not is_secure_auth_secret("")
    assert not is_secure_auth_secret("dev-change-me")
    assert not is_secure_auth_secret("change-this-to-a-long-random-string")
    assert not is_secure_auth_secret("short")
    assert is_secure_auth_secret("a" * 32)


def test_dummy_password_hash_is_a_real_pbkdf2_record() -> None:
    algorithm, iterations, salt, digest = _DUMMY_PASSWORD_HASH.split("$", 3)
    assert algorithm == "pbkdf2_sha256"
    assert int(iterations) == 600_000
    assert salt
    assert digest


import pytest


@pytest.mark.asyncio
async def test_dummy_password_hash_executes_the_real_verifier() -> None:
    assert await verify_password("agent-rs-invalid-password-sentinel", _DUMMY_PASSWORD_HASH)


@pytest.mark.parametrize("value", ["", "dev-change-me", "change-this-to-a-long-random-string", "short-private-test-value"])
def test_startup_rejects_weak_auth_without_echoing_secret(value):
    from app.core.settings import Settings
    from app.main import _verify_auth_configuration

    settings = Settings(_env_file=None, auth_enabled=True, auth_secret_key=value)
    with pytest.raises(RuntimeError) as error:
        _verify_auth_configuration(settings)
    if value:
        assert value not in str(error.value)
    assert "AUTH_SECRET_KEY" in str(error.value)


def test_startup_accepts_valid_secret_without_replacing_it():
    from app.core.settings import Settings
    from app.main import _verify_auth_configuration

    value = "synthetic-strong-test-secret-value-for-startup"
    settings = Settings(_env_file=None, auth_enabled=True, auth_secret_key=value)
    _verify_auth_configuration(settings)
    assert settings.auth_secret_key == value
