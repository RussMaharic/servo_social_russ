// Regression: ISSUE-002 — downloaded launchers opened an unwanted localhost tab.
// Found by /qa on 2026-10-24
// Report: .gstack/qa-reports/qa-report-play-trydexops-com-2026-10-24.md
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

test('downloaded source launchers keep users in the hosted workspace', () => {
  for (const path of ['scripts/start-connect.ps1', 'scripts/start-connect.sh']) {
    const launcher = fs.readFileSync(path, 'utf8');
    assert.match(launcher, /t2_bots\.connect\.app --no-browser/);
    assert.match(launcher, /Return to your open Dexops browser tab/);
  }
});
