// Regression: deployed users had to reconnect manually after starting the companion.
// Found by /qa on 2026-10-24
// Report: .gstack/qa-reports/qa-report-play-trydexops-com-2026-10-24.md
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const source = fs.readFileSync('src/t2_bots/connect/static/app.js', 'utf8');

test('a returning calibrated station automatically enters the dashboard', () => {
  assert.match(source, /!wasOnline&&!pinned&&setupReady\(\)&&state\.username/);
  assert.match(source, /Object\.values\(state\.arms\|\|\{\}\)\.some\(arm=>arm\.calibrated\)/);
  assert.match(source, /route='dashboard';step=4;setTimeout\(\(\)=>loadDirectory\(\),0\)/);
});
