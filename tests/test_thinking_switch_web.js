'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '..');
const appSource = fs.readFileSync(path.join(root, 'web/static/js/app.js'), 'utf8');
const htmlSource = fs.readFileSync(path.join(root, 'web/index.html'), 'utf8');
const cssSource = fs.readFileSync(path.join(root, 'web/static/css/style.css'), 'utf8');

test('DGX model exposes a persisted thinking parameter switch', () => {
    assert.match(htmlSource, /id="btn-thinking-toggle"/);
    assert.match(appSource, /selectedModelProviderKey\(\) === 'dgx'/);
    assert.match(appSource, /thinking_enabled:\s*Boolean\(thinkingEnabled\)/);
    assert.match(appSource, /\.\.\.thinkingRequestPayload\(\)/);
    assert.match(appSource, /saveThinkingEnabled\(\)/);
    assert.match(cssSource, /\.thinking-toggle\[hidden\]\s*\{\s*display:\s*none;/);
    assert.match(cssSource, /\.thinking-toggle\s*\{\s*width:\s*auto;\s*min-width:\s*68px;\s*flex:\s*0 0 auto;/);
    assert.match(cssSource, /\.thinking-toggle\s*\{[^}]*white-space:\s*nowrap;/);
    assert.doesNotMatch(cssSource, /\.thinking-toggle span\s*\{\s*display:\s*none;/);
});

test('reasoning SSE is merged into the execution process and restored from saved messages', () => {
    assert.match(appSource, /event === 'reasoning'/);
    assert.match(appSource, /streamView\.setReasoning\(streamedReasoning\)/);
    assert.match(appSource, /renderProcessPanel\(traceEvents, \{ expanded: false, reasoning \}\)/);
    assert.match(appSource, /kind: 'reasoning'/);
    assert.match(appSource, /msg\.reasoning \|\| ''/);
    assert.match(cssSource, /\.process-item\.reasoning/);
    assert.doesNotMatch(appSource, /renderReasoningPanel/);
});

test('intermediate model output is moved from answer text into the execution process', () => {
    assert.match(appSource, /event === 'intermediate'/);
    assert.match(appSource, /streamView\.moveContentToProcess\(data\)/);
    assert.match(appSource, /type === 'model\.intermediate'/);
});
