// Regression: ISSUE-003 — macOS had no double-click launcher and Windows used old branding.
// Found by /qa on 2026-10-24
// Report: .gstack/qa-reports/qa-report-play-trydexops-com-2026-10-24.md
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

test('source package and onboarding expose Dexops launchers for Windows and macOS', () => {
  const builder = fs.readFileSync('scripts/build-connect-release.py', 'utf8');
  const checker = fs.readFileSync('scripts/check-connect-release.py', 'utf8');
  const frontend = fs.readFileSync('src/t2_bots/connect/static/app.js', 'utf8');
  for (const launcher of ['Start Dexops.cmd', 'Start Dexops.command']) {
    assert.ok(fs.existsSync(launcher));
    assert.match(builder, new RegExp(launcher.replace('.', '\\.')));
    assert.match(checker, new RegExp(launcher.replace('.', '\\.')));
    assert.match(frontend, new RegExp(launcher.replace('.', '\\.')));
  }
  assert.match(fs.readFileSync('Start Dexops.command', 'utf8'), /scripts\/start-connect\.sh/);
});
