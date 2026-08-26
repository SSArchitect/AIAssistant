const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');
const appSource = fs.readFileSync(path.join(root, 'web/static/js/app.js'), 'utf8');
const cssSource = fs.readFileSync(path.join(root, 'web/static/css/style.css'), 'utf8');
const bridgeSource = fs.readFileSync(path.join(root, 'mobile/android-bridge.js'), 'utf8');
const capacitorConfig = JSON.parse(fs.readFileSync(path.join(root, 'capacitor.config.json'), 'utf8'));
const appUpdaterSource = fs.readFileSync(
    path.join(root, 'android/app/src/main/java/com/aan/agentassistant/AppUpdaterPlugin.java'),
    'utf8',
);
const mainActivitySource = fs.readFileSync(
    path.join(root, 'android/app/src/main/java/com/aan/agentassistant/MainActivity.java'),
    'utf8',
);
const androidManifest = fs.readFileSync(path.join(root, 'android/app/src/main/AndroidManifest.xml'), 'utf8');
const filePaths = fs.readFileSync(path.join(root, 'android/app/src/main/res/xml/file_paths.xml'), 'utf8');

function loadDriveShareUrl(apiBase, location) {
    const source = appSource.match(/function driveShareUrl\(item\) \{[\s\S]*?\n\}/)?.[0];
    assert.ok(source, 'driveShareUrl function should exist');
    return Function('API_BASE', 'window', `${source}; return driveShareUrl;`)(
        apiBase,
        { location },
    );
}

test('mobile Drive uses mutually exclusive library and detail panes', () => {
    assert.match(appSource, /data-mobile-drive-pane="library"/);
    assert.match(appSource, /data-mobile-drive-pane="detail"/);
    assert.match(cssSource, /data-mobile-pane="library"\]\s+\.project-map-panel/);
    assert.match(cssSource, /data-mobile-pane="detail"\]\s+\.project-library-panel/);
});

test('Android back returns from Drive detail to the file list first', () => {
    assert.match(bridgeSource, /mobile-drive-tab\[data-mobile-drive-pane="detail"\]\.active/);
    assert.match(bridgeSource, /driveLibraryTab\.click\(\)/);
});

test('Android keeps the standard WebView input connection for voice IMEs', () => {
    assert.equal(capacitorConfig.android.captureInput, false);
});

test('Super Chat renders its welcome prompt before asynchronous app startup', () => {
    assert.match(
        appSource,
        /renderHealth\(\);\s*updateSendState\(\);\s*showWelcome\(\);\s*appBootPromise = bootApp\(\)/,
    );
    assert.match(appSource, /prompt: '把问题或任务发给我就好。'/);
});

test('Android Drive share links use the configured public API origin', () => {
    const driveShareUrl = loadDriveShareUrl('https://www.architect8.cn', {
        href: 'https://localhost/projects',
        origin: 'https://localhost',
    });

    assert.equal(
        driveShareUrl({ share_enabled: true, share_token: 'token/with space' }),
        'https://www.architect8.cn/share/drive/token%2Fwith%20space',
    );
});

test('browser Drive share links remain on the current origin without an API base', () => {
    const driveShareUrl = loadDriveShareUrl('', {
        href: 'https://workbench.example/projects',
        origin: 'https://workbench.example',
    });

    assert.equal(
        driveShareUrl({ share_enabled: true, share_token: 'token-1' }),
        'https://workbench.example/share/drive/token-1',
    );
    assert.equal(driveShareUrl({ share_enabled: false, share_token: 'token-1' }), '');
});

test('remote Android version discovery requires HTTPS', () => {
    assert.match(bridgeSource, /url\.protocol !== 'https:'/);
    assert.match(bridgeSource, /latest_version_code/);
});

test('Android OTA verifies a file manifest and confirms app readiness', () => {
    assert.match(bridgeSource, /CapacitorUpdater\.notifyAppReady\(\)/);
    assert.match(bridgeSource, /\^\[0-9a-f\]\{64\}\$/);
    assert.match(bridgeSource, /CapacitorUpdater\.download/);
    assert.match(bridgeSource, /CapacitorUpdater\.next/);
    assert.match(bridgeSource, /CapacitorUpdater\.getFailedUpdate/);
    assert.match(bridgeSource, /failedOTAVersions\.has\(version\)/);
});

test('Android native updates require verified metadata and use the in-app updater', () => {
    assert.match(bridgeSource, /registerPlugin\('AppUpdater'\)/);
    assert.match(bridgeSource, /AppUpdater\.downloadAndInstall/);
    assert.match(bridgeSource, /apk_sha256/);
    assert.match(bridgeSource, /apk_size/);
    assert.match(bridgeSource, /package_name/);
    assert.match(bridgeSource, /downloadProgress/);
});

test('Android updater verifies HTTPS, checksum, package, version, and signing identity', () => {
    assert.match(mainActivitySource, /registerPlugin\(AppUpdaterPlugin\.class\)/);
    assert.match(androidManifest, /android\.permission\.REQUEST_INSTALL_PACKAGES/);
    assert.match(filePaths, /<files-path name="app_updates" path="updates\/"/);
    assert.match(appUpdaterSource, /"https"\.equalsIgnoreCase/);
    assert.match(appUpdaterSource, /MessageDigest\.getInstance\("SHA-256"\)/);
    assert.match(appUpdaterSource, /expectedPackage\.equals\(archiveInfo\.packageName\)/);
    assert.match(appUpdaterSource, /archiveVersionCode != expectedVersionCode/);
    assert.match(appUpdaterSource, /signatureDigests\(archiveInfo\)\.equals\(signatureDigests\(installedInfo\)\)/);
    assert.match(appUpdaterSource, /FileProvider\.getUriForFile/);
});
