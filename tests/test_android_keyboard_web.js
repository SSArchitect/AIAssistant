const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');
const config = JSON.parse(fs.readFileSync(path.join(root, 'capacitor.config.json'), 'utf8'));
const manifest = fs.readFileSync(path.join(root, 'android/app/src/main/AndroidManifest.xml'), 'utf8');

test('Android enables the Capacitor handler that resizes the WebView for IME insets', () => {
    // In Capacitor 8, disabling SystemBars insets also skips its keyboard
    // listener. Full-height chat layouts then remain behind the keyboard.
    assert.equal(config.plugins.SystemBars.insetsHandling, 'css');
});

test('MainActivity explicitly resizes for the keyboard instead of relying on system pan heuristics', () => {
    const activity = [...manifest.matchAll(/<activity\b[^>]*>/g)]
        .map(([tag]) => tag)
        .find((tag) => /android:name="\.MainActivity"/.test(tag));
    assert.ok(activity, 'MainActivity must be declared');
    const modes = activity.match(/android:windowSoftInputMode="([^"]+)"/)?.[1].split('|') || [];
    assert.ok(modes.includes('adjustResize'), 'older Android versions also need explicit resize behavior');
    assert.ok(!modes.includes('adjustPan') && !modes.includes('adjustNothing'));
});
