"""Directory storage is the current SQLite implementation, without cloud keys."""
from unittest.mock import Mock

from fastapi.testclient import TestClient
from t2_bots.connect.directory import create_app, sqlite_directory_path


def test_default_storage_is_sqlite(monkeypatch):
    monkeypatch.delenv("T2_DIRECTORY_DB", raising=False)
    assert sqlite_directory_path() == "directory.sqlite3"


def test_explicit_persistent_path_is_respected(monkeypatch, tmp_path):
    database = tmp_path / "directory.sqlite3"
    monkeypatch.setenv("T2_DIRECTORY_DB", str(database))
    assert sqlite_directory_path() == str(database)
    with TestClient(create_app()) as client:
        assert client.get("/healthz").json()["status"] == "ok"
    assert database.is_file()


def test_database_health_failure_is_not_reported_as_healthy(tmp_path):
    app = create_app(tmp_path / "directory.sqlite3")
    app.state.directory.check = Mock(side_effect=RuntimeError("private storage diagnostics"))
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 503
        assert "private storage diagnostics" not in response.text
