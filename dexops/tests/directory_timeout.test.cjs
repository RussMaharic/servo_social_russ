// Regression: ISSUE-001 — follower discovery aborted before Render Free woke.
// Found by /qa on 2026-10-24
// Report: .gstack/qa-reports/qa-report-play-trydexops-com-2026-10-24.md
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const source = fs.readFileSync('src/t2_bots/connect/static/app.js', 'utf8');

test('follower discovery waits through a Render Free cold start', () => {
  assert.match(source, /AbortSignal\.timeout\(path==='followers'\?75000:12000\)/);
});
