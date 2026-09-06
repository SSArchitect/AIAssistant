const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');
const appSource = fs.readFileSync(path.join(root, 'web/static/js/app.js'), 'utf8');
const cssSource = fs.readFileSync(path.join(root, 'web/static/css/style.css'), 'utf8');
const bridgeSource = fs.readFileSync(path.join(root, 'mobile/android-bridge.js'), 'utf8');
const fitnessSource = fs.readFileSync(path.join(root, 'web/static/js/fitness.js'), 'utf8');
const capacitorConfig = JSON.parse(fs.readFileSync(path.join(root, 'capacitor.config.json'), 'utf8'));
const appUpdaterSource = fs.readFileSync(
    path.join(root, 'android/app/src/main/java/com/aan/agentassistant/AppUpdaterPlugin.java'),
    'utf8',
);
const nativeFilesSource = fs.readFileSync(
    path.join(root, 'android/app/src/main/java/com/aan/agentassistant/NativeFilesPlugin.java'),
    'utf8',
);
const mainActivitySource = fs.readFileSync(
    path.join(root, 'android/app/src/main/java/com/aan/agentassistant/MainActivity.java'),
    'utf8',
);
const androidManifest = fs.readFileSync(path.join(root, 'android/app/src/main/AndroidManifest.xml'), 'utf8');
const filePaths = fs.readFileSync(path.join(root, 'android/app/src/main/res/xml/file_paths.xml'), 'utf8');
const androidBuildScript = fs.readFileSync(path.join(root, 'scripts/build_android_web.mjs'), 'utf8');

function loadDriveShareUrl(apiBase, location) {
    const source = appSource.match(/function driveShareUrl\(item\) \{[\s\S]*?\n\}/)?.[0];
    assert.ok(source, 'driveShareUrl function should exist');
    return Function('API_BASE', 'window', `${source}; return driveShareUrl;`)(
        apiBase,
        { location },
    );
}

function loadMediaDownloadUrl(apiBase) {
    const source = appSource.match(/function mediaDownloadUrl\(url, filename\) \{[\s\S]*?\n\}/)?.[0];
    assert.ok(source, 'mediaDownloadUrl function should exist');
    return Function('API_BASE', `${source}; return mediaDownloadUrl;`)(apiBase);
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

test('Android image downloads resolve both proxy and server paths against the configured API origin', () => {
    const mobileDownloadUrl = loadMediaDownloadUrl('https://www.architect8.cn');
    assert.equal(
        mobileDownloadUrl('https://cdn.example.com/image 1.png', '回答.png'),
        'https://www.architect8.cn/api/media/download?url=https%3A%2F%2Fcdn.example.com%2Fimage%201.png&filename=%E5%9B%9E%E7%AD%94.png',
    );
    assert.equal(
        mobileDownloadUrl('/static/generated/image.png', 'image.png'),
        'https://www.architect8.cn/static/generated/image.png',
    );

    const browserDownloadUrl = loadMediaDownloadUrl('');
    assert.equal(browserDownloadUrl('/static/generated/image.png', 'image.png'), '/static/generated/image.png');
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

test('Android web builds default to the APK versionCode instead of reporting version 1', () => {
    assert.match(androidBuildScript, /androidBuildGradle\.match\(\/\\bversionCode/);
    assert.match(androidBuildScript, /AGENT_ASSISTANT_ANDROID_VERSION_CODE \|\| gradleVersionCode/);
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

test('Android answer images use a native clipboard URI before the browser fallback', () => {
    assert.match(bridgeSource, /registerPlugin\('NativeFiles'\)/);
    assert.match(bridgeSource, /NativeFiles\.copyImage\(payload\)/);
    assert.match(mainActivitySource, /registerPlugin\(NativeFilesPlugin\.class\)/);
    assert.match(nativeFilesSource, /ClipboardManager/);
    assert.match(nativeFilesSource, /ClipData\.newUri/);
    assert.match(nativeFilesSource, /FileProvider\.getUriForFile/);
});

test('Android downloads save into the system Downloads collection with legacy permission fallback', () => {
    assert.match(bridgeSource, /NativeFiles\.saveFile\(payload\)/);
    assert.match(appSource, /FileActions\?\.hasNativeDownload\(\)/);
    assert.match(appSource, /FileActions\.downloadBlob/);
    assert.match(nativeFilesSource, /MediaStore\.Downloads\.getContentUri/);
    assert.match(nativeFilesSource, /MediaStore\.MediaColumns\.IS_PENDING/);
    assert.match(nativeFilesSource, /Environment\.getExternalStoragePublicDirectory/);
    assert.match(androidManifest, /WRITE_EXTERNAL_STORAGE" android:maxSdkVersion="28"/);
});

test('all user-facing Blob downloads route through the shared mobile adapter', () => {
    assert.match(appSource, /async function downloadDriveItem[\s\S]*?FileActions\.downloadBlob/);
    assert.match(appSource, /async function downloadShareCardImage[\s\S]*?FileActions\.downloadBlob/);
    assert.match(appSource, /async function saveImageFromUrl[\s\S]*?FileActions\.downloadBlob/);
    assert.match(fitnessSource, /async function exportData[\s\S]*?FileActions\.downloadBlob/);
});
