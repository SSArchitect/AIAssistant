const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const bridgeSource = fs.readFileSync(path.join(__dirname, '../mobile/android-bridge.js'), 'utf8')
  .replace(/^import .*;\n/gm, '');

function createApp({ build = '3', embeddedBuild = 6, latestBuild = 6, nativeFiles = false,
  infoFails = false, downloadFails = false, apkUrl = 'https://www.architect8.cn/downloads/agent-assistant-0.4.1-debug.apk', ota = null } = {}) {
  const notices = [];
  const opened = [];
  const downloads = [];
  const requests = [];
  let permissionChecks = 0;
  function element(tag) {
    return { tag, children: [], listeners: {}, textContent: '',
      appendChild(child) { this.children.push(child); },
      addEventListener(name, callback) { this.listeners[name] = callback; },
      setAttribute() {}, remove() { this.removed = true; } };
  }
  const context = vm.createContext({
    URL, console, setTimeout, clearTimeout,
    AGENT_ASSISTANT_CONFIG: { apiBase: 'https://www.architect8.cn', appVersionCode: embeddedBuild, otaSequence: 13 },
    Capacitor: { getPlatform: () => 'android', isPluginAvailable: (name) => name !== 'NativeFiles' || nativeFiles },
    App: { getInfo: async () => { if (infoFails) throw new Error('unavailable'); return { build }; },
      addListener() {} },
    Browser: { open: async ({ url }) => opened.push(url) },
    Share: {}, nativeFilePayload: { blobToNativeFilePayload: async () => ({}) },
    registerPlugin: (name) => name === 'AppUpdater' ? {
      addListener() {},
      canInstallPackages: async () => { permissionChecks += 1; return { granted: true }; },
      downloadAndInstall: async (payload) => { downloads.push(payload); if (downloadFails) throw new Error('download failed'); },
    } : { copyImage: async () => ({}), saveFile: async () => ({}) },
    CapacitorUpdater: { notifyAppReady() {}, getFailedUpdate: async () => ({}),
      current: async () => ({}), getNextBundle: async () => ({ version: ota?.version }) },
    localStorage: { getItem: () => null },
    document: { documentElement: { classList: { add() {} } },
      getElementById: () => notices.findLast((notice) => !notice.removed),
      createElement: element, body: { appendChild: (notice) => notices.push(notice) }, addEventListener() {} },
    window: { addEventListener() {}, location: { href: 'https://localhost/' } },
    fetch: async (url) => { requests.push(String(url)); return { ok: true, json: async () => ({ android: {
      latest_version_code: latestBuild, latest_version_name: '0.4.1', apk_url: apkUrl,
      apk_sha256: 'a'.repeat(64), apk_size: 7819190, package_name: 'com.aan.agentassistant', ota,
    } }) }; },
  });
  vm.runInContext(bridgeSource, context);
  return { context, opened, downloads, requests, permissionChecks: () => permissionChecks,
    check: () => context.AgentAssistantNative.checkForUpdate(),
    notice: () => notices.findLast((notice) => !notice.removed),
    action: () => notices.findLast((notice) => !notice.removed)?.children.find((child) => child.className === 'native-update-action'),
  };
}

test('old APK uses a browser update button even when the OTA embeds a newer version', async () => {
  for (const build of ['3', '5']) {
    const app = createApp({ build, embeddedBuild: 6 });
    await app.check();
    assert.equal(app.action()?.textContent, '浏览器下载更新');
    await app.action().listeners.click();
    assert.equal(app.opened.length, 1);
    assert.match(app.opened[0], /agent-assistant-0\.4\.1-debug\.apk$/);
    assert.equal(app.permissionChecks(), 0);
    assert.equal(app.downloads.length, 0);
    assert.equal(new URL(app.requests[0]).searchParams.get('version_code'), build);
  }
});

test('fixed APK returns to native download for later releases', async () => {
  const app = createApp({ build: '6', latestBuild: 7, nativeFiles: true });
  await app.check();
  assert.equal(app.action().textContent, '更新');
  await app.action().listeners.click();
  assert.equal(app.downloads.length, 1);
  assert.equal(app.downloads[0].versionCode, 7);
  assert.equal(app.opened.length, 0);
});

test('OTA metadata cannot make a current APK display a false upgrade', async () => {
  const app = createApp({ build: '6', embeddedBuild: 3 });
  await app.check();
  assert.equal(app.notice(), undefined);
});

test('unknown installed version safely offers a browser instead of the broken updater', async () => {
  const app = createApp({ infoFails: true });
  await app.check();
  assert.equal(app.action()?.textContent, '浏览器下载更新');
  await app.action().listeners.click();
  assert.equal(app.opened.length, 1);
  assert.equal(app.permissionChecks(), 0);
});

test('recovery OTA does not expose file actions absent from older APKs', () => {
  const oldApp = createApp();
  assert.equal(oldApp.context.AgentAssistantNative.downloadBlob, undefined);
  assert.equal(oldApp.context.AgentAssistantNative.copyImage, undefined);
  const newApp = createApp({ nativeFiles: true });
  assert.equal(typeof newApp.context.AgentAssistantNative.downloadBlob, 'function');
  assert.equal(typeof newApp.context.AgentAssistantNative.copyImage, 'function');
});

test('invalid APK download URLs do not produce an update action', async () => {
  const app = createApp({ apkUrl: 'http://insecure.example/update.apk' });
  await app.check();
  assert.equal(app.action(), undefined);
  assert.equal(app.opened.length, 0);
});

test('native download failure offers a browser fallback', async () => {
  const app = createApp({ build: '6', latestBuild: 7, downloadFails: true });
  await app.check();
  await app.action().listeners.click();
  assert.equal(app.action().textContent, '浏览器下载更新');
  await app.action().listeners.click();
  assert.equal(app.opened.length, 1);
});

test('OTA readiness cannot replace the required APK browser update button', async () => {
  const ota = { version: 'recovery.1', sequence: 14, min_native_version_code: 3,
    manifest: [{ file_name: 'index.html', file_hash: 'a'.repeat(64), download_url: '/updates/android/recovery.1/files/index.html' }] };
  const app = createApp({ build: '3', embeddedBuild: 3, ota });
  await app.check();
  assert.equal(app.action().textContent, '浏览器下载更新');
});

test('current APK can still apply OTA content updates normally', async () => {
  const ota = { version: 'recovery.1', sequence: 14, min_native_version_code: 3,
    manifest: [{ file_name: 'index.html', file_hash: 'a'.repeat(64), download_url: '/updates/android/recovery.1/files/index.html' }] };
  const app = createApp({ build: '6', latestBuild: 6, ota });
  await app.check();
  assert.equal(app.action().textContent, '立即应用');
});
