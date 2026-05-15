"""Tests for DB engine singleton lifecycle and pool configuration."""
from unittest.mock import patch, MagicMock

from app.config import Settings


def test_get_async_engine_returns_singleton():
    """get_async_engine() must return the same engine object on every call."""
    from app.db.base import get_async_engine

    get_async_engine.cache_clear()

    settings = Settings()
    with patch("app.db.base.get_settings", return_value=settings):
        engine_a = get_async_engine()
        engine_b = get_async_engine()

    assert engine_a is engine_b
    get_async_engine.cache_clear()


def test_get_async_engine_applies_pool_limits():
    """Engine must be created with the configured pool parameters."""
    from app.db.base import get_async_engine

    get_async_engine.cache_clear()

    settings = Settings(
        db_pool_size=5,
        db_max_overflow=3,
        db_pool_timeout=15,
        db_pool_recycle=900,
    )
    with patch("app.db.base.get_settings", return_value=settings):
        with patch("app.db.base.create_async_engine") as mock_create:
            mock_create.return_value = MagicMock()
            get_async_engine()

    mock_create.assert_called_once()
    kwargs = mock_create.call_args.kwargs
    assert kwargs["pool_size"] == 5
    assert kwargs["max_overflow"] == 3
    assert kwargs["pool_timeout"] == 15
    assert kwargs["pool_recycle"] == 900
    assert kwargs["pool_pre_ping"] is True

    get_async_engine.cache_clear()


def test_session_factory_uses_cached_engine():
    """get_async_session_factory() must use the cached singleton engine."""
    from app.db.base import get_async_engine, get_async_session_factory

    get_async_engine.cache_clear()

    settings = Settings()
    with patch("app.db.base.get_settings", return_value=settings):
        engine = get_async_engine()
        factory = get_async_session_factory()

    assert factory.kw["bind"] is engine
    get_async_engine.cache_clear()
