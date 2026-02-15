import pytest

from app.config import ProductionGuardError, Settings

_SAFE_JWT = "a-real-production-secret-abc123"
_SAFE_AGENT = "a-real-production-agent-key-xyz"
_DEV_JWT = "dev-secret-key-change-in-production"
_DEV_AGENT = "dev-agent-key-change-in-production"


def test_ocr_search_defaults() -> None:
    settings = Settings()
    assert settings.ocr_search_enabled is True
    assert settings.ocr_bm25_boost == 0.6


class TestProductionGuards:

    def test_development_allows_all_defaults(self) -> None:
        settings = Settings(environment="development")
        settings.validate_production_guards()

    def test_production_with_proper_values_passes(self) -> None:
        settings = Settings(
            environment="production",
            jwt_secret_key=_SAFE_JWT,
            agent_api_key=_SAFE_AGENT,
            auth0_enabled=True,
        )
        settings.validate_production_guards()

    def test_production_rejects_dev_jwt_secret(self) -> None:
        settings = Settings(
            environment="production",
            jwt_secret_key=_DEV_JWT,
            agent_api_key=_SAFE_AGENT,
            auth0_enabled=True,
        )
        with pytest.raises(ProductionGuardError, match="JWT_SECRET_KEY"):
            settings.validate_production_guards()

    def test_production_rejects_dev_agent_key(self) -> None:
        settings = Settings(
            environment="production",
            jwt_secret_key=_SAFE_JWT,
            agent_api_key=_DEV_AGENT,
            auth0_enabled=True,
        )
        with pytest.raises(ProductionGuardError, match="AGENT_API_KEY"):
            settings.validate_production_guards()

    def test_production_rejects_auth0_disabled(self) -> None:
        settings = Settings(
            environment="production",
            jwt_secret_key=_SAFE_JWT,
            agent_api_key=_SAFE_AGENT,
            auth0_enabled=False,
        )
        with pytest.raises(ProductionGuardError, match="AUTH0_ENABLED"):
            settings.validate_production_guards()

    def test_staging_applies_same_guards(self) -> None:
        settings = Settings(
            environment="staging",
            jwt_secret_key=_DEV_JWT,
            agent_api_key=_SAFE_AGENT,
            auth0_enabled=True,
        )
        with pytest.raises(ProductionGuardError, match="JWT_SECRET_KEY"):
            settings.validate_production_guards()

    def test_error_lists_all_failures_not_just_first(self) -> None:
        settings = Settings(
            environment="production",
            jwt_secret_key=_DEV_JWT,
            agent_api_key=_DEV_AGENT,
            auth0_enabled=False,
        )
        with pytest.raises(ProductionGuardError) as exc_info:
            settings.validate_production_guards()

        error_msg = str(exc_info.value)
        assert "JWT_SECRET_KEY" in error_msg
        assert "AGENT_API_KEY" in error_msg
        assert "AUTH0_ENABLED" in error_msg
        assert "3 issue(s)" in error_msg

    def test_error_includes_remediation_hints(self) -> None:
        settings = Settings(
            environment="production",
            jwt_secret_key=_DEV_JWT,
            agent_api_key=_SAFE_AGENT,
            auth0_enabled=True,
        )
        with pytest.raises(ProductionGuardError, match="openssl rand"):
            settings.validate_production_guards()

    def test_partial_failure_only_reports_failing_checks(self) -> None:
        settings = Settings(
            environment="production",
            jwt_secret_key=_DEV_JWT,
            agent_api_key=_SAFE_AGENT,
            auth0_enabled=True,
        )
        with pytest.raises(ProductionGuardError) as exc_info:
            settings.validate_production_guards()

        error_msg = str(exc_info.value)
        assert "JWT_SECRET_KEY" in error_msg
        assert "AGENT_API_KEY" not in error_msg
        assert "AUTH0_ENABLED" not in error_msg
        assert "1 issue(s)" in error_msg
