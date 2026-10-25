// Regression: ISSUE-002 — downloaded launchers opened an unwanted localhost tab.
// Found by /qa on 2026-10-24
// Report: .gstack/qa-reports/qa-report-play-trydexops-com-2026-10-24.md
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

test('downloaded source launchers open the hosted workspace instead of localhost', () => {
  for (const path of ['scripts/start-connect.ps1', 'scripts/start-connect.sh']) {
    const launcher = fs.readFileSync(path, 'utf8');
    assert.match(launcher, /setup-dexops\.py/);
    assert.doesNotMatch(launcher, /pip install/);
    assert.doesNotMatch(launcher, /--workspace-url\s+["']?http:\/\/127\.0\.0\.1/);
  }
  const setup = fs.readFileSync('scripts/setup-dexops.py', 'utf8');
  assert.match(setup, /https:\/\/servosocialruss\.vercel\.app/);
  assert.match(setup, /install_local/);
});
