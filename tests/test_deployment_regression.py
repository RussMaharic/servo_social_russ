"""Deployment regressions found during the 2026-10-24 QA pass."""

import io

from t2_bots.connect.app import Companion, DIRECTORY_TIMEOUT


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
