from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from t2_bots.connect.directory import create_app, sqlite_directory_path
from t2_bots.connect.postgres_directory import PostgresDirectory, PostgresQueries


def test_hosted_directory_refuses_silent_sqlite_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("T2_DATABASE_URL", raising=False)
    monkeypatch.setenv("T2_DIRECTORY_REQUIRE_POSTGRES", "1")
    with pytest.raises(RuntimeError, match="T2_DATABASE_URL"):
        create_app()
    # Explicit isolated test/development stores still work.
    with TestClient(create_app(tmp_path / "dev.sqlite3")) as client:
        assert client.get("/healthz").status_code == 200


def test_railway_volume_is_used_without_extra_database_variable(monkeypatch, tmp_path):
    monkeypatch.delenv("T2_DIRECTORY_DB", raising=False)
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path))
    assert sqlite_directory_path() == str(tmp_path / "t2-directory.sqlite3")


def test_explicit_sqlite_path_overrides_railway_volume(monkeypatch, tmp_path):
    configured = tmp_path / "custom.sqlite3"
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path / "volume"))
    monkeypatch.setenv("T2_DIRECTORY_DB", str(configured))
    assert sqlite_directory_path() == str(configured)


@pytest.mark.parametrize("url", [
    "https://fwamzeswdfhqtabakaib.supabase.co",
    "postgresql://postgres:private@db.fwamzeswdfhqtabakaib.supabase.co/postgres",
    "postgresql://t2_directory_app.wrong:private@pooler.supabase.com/postgres",
])
def test_private_connection_rejects_project_url_admin_role_and_wrong_project(url):
    with pytest.raises(ValueError):
        PostgresDirectory(url, "fwamzeswdfhqtabakaib")


def test_database_health_failure_is_not_reported_as_healthy(tmp_path):
    app=create_app(tmp_path / "test.sqlite3")
    app.state.directory.check=Mock(side_effect=RuntimeError("private database diagnostics"))
    with TestClient(app) as client:
        response=client.get("/healthz")
        assert response.status_code == 503
        assert "private database diagnostics" not in response.text


def test_queries_bind_untrusted_values_and_use_transaction_locking():
    connection=Mock()
    queries=PostgresQueries(connection)
    malicious="name?'; DROP TABLE devices; --"
    queries.execute("SELECT * FROM devices WHERE username=?", (malicious,))
    connection.execute.assert_called_once_with("SELECT * FROM devices WHERE username=%s", (malicious,))
    queries.execute(PostgresDirectory.reservation_query, ("follower",))
    assert "FOR UPDATE" in connection.execute.call_args.args[0]
