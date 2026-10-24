// Regression: ISSUE-002 — downloaded launchers opened an unwanted localhost tab.
// Found by /qa on 2026-10-24
// Report: .gstack/qa-reports/qa-report-play-trydexops-com-2026-10-24.md
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

test('downloaded source launchers open the hosted workspace instead of localhost', () => {
  for (const path of ['scripts/start-connect.ps1', 'scripts/start-connect.sh']) {
    const launcher = fs.readFileSync(path, 'utf8');
    assert.match(launcher, /t2_bots\.connect\.app --workspace-url/);
    assert.match(launcher, /https:\/\/servosocialruss\.vercel\.app\//);
    assert.doesNotMatch(launcher, /--workspace-url\s+["']?http:\/\/127\.0\.0\.1/);
  }
  assert.match(fs.readFileSync('scripts/start-connect.ps1', 'utf8'), /Dexops\\bin[\s\S]*dexops\.cmd/);
  assert.match(fs.readFileSync('scripts/start-connect.sh', 'utf8'), /\.local\/bin[\s\S]*COMMAND_DIR\/dexops/);
});
