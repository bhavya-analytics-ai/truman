import os
import sqlite3
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Isolated SQLite DB per test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("truman.storage.db.DB_PATH", db_path)
    import truman.storage.db as _db
    _db._initialized = False
    _db.init()
    yield db_path
    _db._initialized = False


@pytest.fixture
def mock_nim_embed(monkeypatch):
    """Mock NVIDIA NIM embedding API. Returns deterministic 8-dim vector."""
    def fake_embed(text):
        # Deterministic hash-based fake embedding
        import hashlib
        h = hashlib.md5(text.encode()).digest()
        return [b / 255.0 for b in h[:8]]
    monkeypatch.setattr("truman.brain.tool_retrieval._embed", fake_embed)
    return fake_embed


@pytest.fixture
def fake_railway(monkeypatch):
    """Pretend we're on Railway."""
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")


@pytest.fixture
def fake_local(monkeypatch):
    """Pretend we're local."""
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
