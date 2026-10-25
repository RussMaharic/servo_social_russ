"""Deployment regressions found during the 2026-10-24 QA pass."""

import io
import urllib.error
import pytest

from t2_bots.connect.app import Companion, DIRECTORY_TIMEOUT


def test_directory_reset_restores_identity_and_retries_once(tmp_path, monkeypatch):
    station = Companion(tmp_path)
    station.store.data.update(directory_url="https://directory.example", username="operator")
    calls = []

    def open_request(request, timeout):
        calls.append((request.method, request.full_url))
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {},
                io.BytesIO(b'{"detail":"Device credential required."}'))
        return io.BytesIO(b'{"username":"operator"}' if request.full_url.endswith('/identity') else b'{"published":true}')

    monkeypatch.setattr("urllib.request.urlopen", open_request)
    assert station.cloud("PUT", "/v1/follower", {"label":"Follower"}) == {"published":True}
    assert [method for method, _ in calls] == ["PUT", "POST", "PUT"]


@pytest.mark.parametrize('conflict', [False, True])
def test_registration_recovery_is_bounded_and_respects_conflicts(tmp_path, monkeypatch, conflict):
    station = Companion(tmp_path)
    station.store.data.update(directory_url="https://directory.example", username="operator")
    calls = []

    def open_request(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith('/identity'):
            if conflict:
                raise urllib.error.HTTPError(request.full_url, 409, 'Conflict', {},
                    io.BytesIO(b'{"detail":"That username is taken. Choose another."}'))
            return io.BytesIO(b'{"username":"operator"}')
        raise urllib.error.HTTPError(request.full_url, 403, 'Forbidden', {},
            io.BytesIO(b'{"detail":"Device credential required."}'))

    monkeypatch.setattr('urllib.request.urlopen', open_request)
    with pytest.raises(ValueError, match='username is taken' if conflict else 'Device credential required'):
        station.cloud('PUT', '/v1/follower', {})
    assert len(calls) == (2 if conflict else 3)


def test_render_directory_request_allows_free_tier_cold_start(tmp_path, monkeypatch):
    # Regression: ISSUE-001 — Render Free woke slower than the old 8 s timeout.
    # Found by /qa on 2026-10-24
    # Report: .gstack/qa-reports/qa-report-play-trydexops-com-2026-10-24.md
    station = Companion(tmp_path)
    station.store.data["directory_url"] = "https://directory.example"
    seen = {}

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def open_request(request, timeout):
        seen["timeout"] = timeout
        return Reply(b'{"followers": []}')

    monkeypatch.setattr("urllib.request.urlopen", open_request)
    assert station.cloud("GET", "/v1/followers") == {"followers": []}
    assert seen["timeout"] == DIRECTORY_TIMEOUT
    assert DIRECTORY_TIMEOUT >= 60
