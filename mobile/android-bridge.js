import { Capacitor, registerPlugin } from '@capacitor/core';
import { App } from '@capacitor/app';
import { Browser } from '@capacitor/browser';
import { Share } from '@capacitor/share';
import { CapacitorUpdater } from '@capgo/capacitor-updater';

const AppUpdater = registerPlugin('AppUpdater');

if (Capacitor.getPlatform() === 'android') {
  document.documentElement.classList.add('native-android');

  const runtimeConfig = globalThis.AGENT_ASSISTANT_CONFIG || {};
  const failedOTAVersionsStorageKey = 'agent-assistant.failed-ota-versions';
  const failedOTAVersions = new Set();
  let lastVersionCheckAt = 0;
  let otaUpdatePromise = null;
  let nativeUpdateInProgress = false;
  let pendingNativeRelease = null;

  // This must happen before any network work. A downloaded bundle that cannot
  // execute this line is automatically rolled back by the native updater.
  void CapacitorUpdater.notifyAppReady();

  function loadFailedOTAVersions() {
    try {
      const stored = JSON.parse(localStorage.getItem(failedOTAVersionsStorageKey) || '[]');
      if (Array.isArray(stored)) {
        stored.slice(-10).forEach((version) => failedOTAVersions.add(String(version)));
      }
    } catch {
      // A damaged preference must not interfere with startup.
    }
  }

  async function rememberLastFailedOTA() {
    loadFailedOTAVersions();
    try {
      const failed = await CapacitorUpdater.getFailedUpdate();
      const version = String(failed?.bundle?.version || '').trim();
      if (!version) return;
      failedOTAVersions.add(version);
      const recent = Array.from(failedOTAVersions).slice(-10);
      localStorage.setItem(failedOTAVersionsStorageKey, JSON.stringify(recent));
    } catch {
      // Failure telemetry is best effort; OTA checks can still continue.
    }
  }

  const failedOTAReadyPromise = rememberLastFailedOTA();

  function dismissUpdateNotice() {
    document.getElementById('native-update-notice')?.remove();
  }

  function showUpdateNotice({ message, actionText = '', onAction = null } = {}) {
    dismissUpdateNotice();
    const notice = document.createElement('aside');
    notice.id = 'native-update-notice';
    notice.className = 'native-update-notice';
    notice.setAttribute('role', 'status');
    const copy = document.createElement('span');
    copy.className = 'native-update-copy';
    copy.textContent = String(message || '发现新版本');
    notice.appendChild(copy);
    if (actionText && typeof onAction === 'function') {
      const action = document.createElement('button');
      action.className = 'native-update-action';
      action.type = 'button';
      action.textContent = actionText;
      action.addEventListener('click', onAction);
      notice.appendChild(action);
    }
    const dismiss = document.createElement('button');
    dismiss.className = 'native-update-dismiss';
    dismiss.type = 'button';
    dismiss.setAttribute('aria-label', '稍后提醒');
    dismiss.textContent = '×';
    dismiss.addEventListener('click', dismissUpdateNotice);
    notice.appendChild(dismiss);
    document.body.appendChild(notice);
  }

  function secureOrLocalURL(value, base) {
    const url = new URL(value, base);
    const localHosts = ['localhost', '127.0.0.1', '10.0.2.2'];
    if (url.protocol !== 'https:' && !localHosts.includes(url.hostname)) {
      throw new Error(`Insecure OTA URL rejected: ${url.origin}`);
    }
    return url;
  }

  function normalizedNativeRelease(androidRelease = {}) {
    const versionName = String(androidRelease.latest_version_name || '').trim();
    const versionCode = Number(androidRelease.latest_version_code || 0);
    const rawApkUrl = String(androidRelease.apk_url || '').trim();
    const sha256 = String(androidRelease.apk_sha256 || '').trim().toLowerCase();
    const size = Number(androidRelease.apk_size || 0);
    const packageName = String(androidRelease.package_name || '').trim();
    let apkUrl = '';
    try {
      apkUrl = rawApkUrl ? secureOrLocalURL(rawApkUrl, runtimeConfig.apiBase).href : '';
    } catch {
      apkUrl = '';
    }
    return {
      versionName,
      versionCode,
      apkUrl,
      sha256,
      size,
      packageName,
      releaseNotes: String(androidRelease.release_notes || '').trim(),
    };
  }

  function nativeReleaseCanBeVerified(release) {
    return Boolean(
      release.apkUrl
      && Number.isSafeInteger(release.versionCode)
      && release.versionCode > 0
      && Number.isSafeInteger(release.size)
      && release.size > 0
      && /^[0-9a-f]{64}$/.test(release.sha256)
      && release.packageName === 'com.aan.agentassistant'
    );
  }

  function nativeUpdateMessage(release) {
    const prefix = `发现新版本${release.versionName ? ` ${release.versionName}` : ''}`;
    if (!release.releaseNotes) return prefix;
    const notes = release.releaseNotes.length > 80
      ? `${release.releaseNotes.slice(0, 80)}…`
      : release.releaseNotes;
    return `${prefix}：${notes}`;
  }

  async function requestInstallPermission(release) {
    pendingNativeRelease = release;
    try {
      await AppUpdater.openInstallPermission();
      showUpdateNotice({ message: '请允许安装此来源的应用，返回后将自动继续更新' });
    } catch {
      showUpdateNotice({
        message: '无法打开安装权限设置，可改用浏览器下载',
        actionText: '浏览器下载',
        onAction: () => Browser.open({ url: release.apkUrl }),
      });
    }
  }

  async function installNativeAppUpdate(release) {
    if (nativeUpdateInProgress) return;
    if (!nativeReleaseCanBeVerified(release)) {
      showUpdateNotice({
        message: '此版本缺少安全校验信息，请用浏览器下载',
        actionText: release.apkUrl ? '浏览器下载' : '',
        onAction: release.apkUrl ? () => Browser.open({ url: release.apkUrl }) : null,
      });
      return;
    }

    try {
      const permission = await AppUpdater.canInstallPackages();
      if (!permission?.granted) {
        showUpdateNotice({
          message: '首次在 App 内更新需要允许“安装未知应用”',
          actionText: '允许安装',
          onAction: () => requestInstallPermission(release),
        });
        return;
      }

      nativeUpdateInProgress = true;
      pendingNativeRelease = null;
      showUpdateNotice({ message: '正在准备下载新版本…' });
      await AppUpdater.downloadAndInstall({
        url: release.apkUrl,
        sha256: release.sha256,
        size: release.size,
        versionCode: release.versionCode,
        packageName: release.packageName,
      });
      showUpdateNotice({ message: '下载和校验完成，请在系统界面确认安装' });
    } catch (error) {
      if (error?.code === 'INSTALL_PERMISSION_REQUIRED') {
        showUpdateNotice({
          message: '需要允许“安装未知应用”后才能继续',
          actionText: '允许安装',
          onAction: () => requestInstallPermission(release),
        });
      } else {
        showUpdateNotice({
          message: '更新下载或校验失败，请稍后重试',
          actionText: '重试',
          onAction: () => installNativeAppUpdate(release),
        });
      }
    } finally {
      nativeUpdateInProgress = false;
    }
  }

  function showNativeAppUpdate(androidRelease = {}) {
    const release = normalizedNativeRelease(androidRelease);
    showUpdateNotice({
      message: nativeUpdateMessage(release),
      actionText: release.apkUrl ? '更新' : '',
      onAction: release.apkUrl ? () => installNativeAppUpdate(release) : null,
    });
  }

  async function resumePendingNativeInstall() {
    if (!pendingNativeRelease || nativeUpdateInProgress) return false;
    try {
      const permission = await AppUpdater.canInstallPackages();
      if (!permission?.granted) {
        const release = pendingNativeRelease;
        showUpdateNotice({
          message: '尚未获得安装权限，允许后才能继续更新',
          actionText: '打开设置',
          onAction: () => requestInstallPermission(release),
        });
        return true;
      }
      const release = pendingNativeRelease;
      pendingNativeRelease = null;
      await installNativeAppUpdate(release);
      return true;
    } catch {
      return false;
    }
  }

  function showOTAReady(version) {
    showUpdateNotice({
      message: `内容更新 ${version} 已准备好`,
      actionText: '立即应用',
      onAction: () => CapacitorUpdater.reload(),
    });
  }

  function normalizedOTAManifest(ota, apiBase) {
    const entries = Array.isArray(ota?.manifest) ? ota.manifest : [];
    if (!entries.length || entries.length > 10000) throw new Error('Invalid OTA manifest size.');
    const normalized = entries.map((entry) => {
      const fileName = String(entry?.file_name || '');
      const fileHash = String(entry?.file_hash || '').toLowerCase();
      if (!fileName || fileName.startsWith('/') || fileName.includes('\\') || fileName.split('/').includes('..')) {
        throw new Error('Invalid OTA file path.');
      }
      if (!/^[0-9a-f]{64}$/.test(fileHash)) throw new Error('Invalid OTA file checksum.');
      const rawDownloadURL = String(entry?.download_url || '').trim();
      if (!rawDownloadURL) throw new Error('Missing OTA download URL.');
      return {
        file_name: fileName,
        file_hash: fileHash,
        download_url: secureOrLocalURL(rawDownloadURL, `${apiBase}/`).href,
      };
    });
    if (!normalized.some((entry) => entry.file_name === 'index.html')) {
      throw new Error('OTA manifest is missing index.html.');
    }
    return normalized;
  }

  async function prepareOTAUpdate(ota, apiBase, currentVersionCode) {
    const version = String(ota?.version || '').trim();
    const sequence = Number(ota?.sequence || 0);
    const currentSequence = Number(runtimeConfig.otaSequence || 0);
    const minNative = Number(ota?.min_native_version_code || 1);
    const maxNative = Number(ota?.max_native_version_code || 0);
    if (!/^[0-9A-Za-z][0-9A-Za-z._-]{0,79}$/.test(version)) return;
    if (failedOTAVersions.has(version)) return;
    if (!Number.isInteger(sequence) || sequence <= currentSequence) return;
    if (currentVersionCode < minNative || (maxNative > 0 && currentVersionCode > maxNative)) return;

    const manifest = normalizedOTAManifest(ota, apiBase);
    const current = await CapacitorUpdater.current();
    if (current?.bundle?.version === version) return;

    const pending = await CapacitorUpdater.getNextBundle();
    if (pending?.version === version) {
      showOTAReady(version);
      return;
    }

    const bundles = await CapacitorUpdater.list();
    let bundle = bundles.bundles.find((item) => item.version === version && item.status !== 'error');
    if (!bundle) {
      bundle = await CapacitorUpdater.download({
        version,
        url: manifest[0].download_url,
        manifest,
      });
    }
    await CapacitorUpdater.next({ id: bundle.id });
    showOTAReady(version);
  }

  async function checkForAppUpdate({ force = false } = {}) {
    await failedOTAReadyPromise;
    const apiBase = String(runtimeConfig.apiBase || '').replace(/\/+$/, '');
    const currentVersionCode = Number(runtimeConfig.appVersionCode || 0);
    if (!apiBase || !currentVersionCode) return;
    let versionEndpoint;
    try {
      versionEndpoint = secureOrLocalURL(`${apiBase}/api/app/version`, apiBase);
    } catch {
      return;
    }
    const now = Date.now();
    if (!force && now - lastVersionCheckAt < 60 * 60 * 1000) return;
    lastVersionCheckAt = now;
    try {
      versionEndpoint.searchParams.set('platform', 'android');
      versionEndpoint.searchParams.set('version_code', String(currentVersionCode));
      versionEndpoint.searchParams.set('web_version', String(runtimeConfig.webVersion || ''));
      versionEndpoint.searchParams.set('ota_sequence', String(runtimeConfig.otaSequence || 0));
      const response = await fetch(versionEndpoint, {
        cache: 'no-store',
      });
      if (!response.ok) return;
      const manifest = await response.json();
      const androidRelease = manifest?.android || {};
      if (Number(androidRelease.latest_version_code || 0) > currentVersionCode) {
        showNativeAppUpdate(androidRelease);
      }
      if (androidRelease.ota && !otaUpdatePromise) {
        otaUpdatePromise = prepareOTAUpdate(androidRelease.ota, apiBase, currentVersionCode)
          .catch((error) => console.warn('Android OTA update was not prepared.', error))
          .finally(() => {
            otaUpdatePromise = null;
          });
        await otaUpdatePromise;
      }
    } catch {
      // Version discovery must never interfere with normal app startup.
    }
  }

  App.addListener('backButton', async () => {
    const closeControl = document.querySelector(
      '.app-confirm-dialog [data-confirm-cancel], '
      + '.share-card-dialog:not(.hidden) [data-share-card-close], '
      + '.media-lightbox:not(.hidden) [data-media-preview-close], '
      + '.drive-save-dialog:not(.hidden) [data-drive-save-cancel], '
      + '.account-login:not(.hidden) [data-account-login-close]',
    );
    if (closeControl instanceof HTMLElement) {
      closeControl.click();
      return;
    }

    const sidebarBackdrop = document.getElementById('sidebar-backdrop');
    if (sidebarBackdrop && sidebarBackdrop.hidden === false) {
      sidebarBackdrop.click();
      return;
    }

    const driveDetailTab = document.querySelector('.mobile-drive-tab[data-mobile-drive-pane="detail"].active');
    const driveLibraryTab = document.querySelector('.mobile-drive-tab[data-mobile-drive-pane="library"]');
    if (driveDetailTab instanceof HTMLElement && driveLibraryTab instanceof HTMLElement) {
      driveLibraryTab.click();
      return;
    }

    const activeView = document.querySelector('[data-view-panel].active');
    if (activeView?.getAttribute('data-view-panel') !== 'chat') {
      const chatNavigation = document.querySelector('[data-view="chat"]');
      if (chatNavigation instanceof HTMLElement) {
        chatNavigation.click();
        return;
      }
    }

    await App.minimizeApp();
  });

  AppUpdater.addListener('downloadProgress', ({ percent }) => {
    if (!nativeUpdateInProgress) return;
    const progress = Math.max(0, Math.min(100, Number(percent) || 0));
    showUpdateNotice({ message: `正在下载新版本 ${progress}%` });
  });

  App.addListener('appStateChange', ({ isActive }) => {
    if (!isActive) return;
    void resumePendingNativeInstall().then((resumed) => {
      if (!resumed) void checkForAppUpdate();
    });
  });

  document.addEventListener('click', async (event) => {
    const anchor = event.target instanceof Element ? event.target.closest('a[href]') : null;
    if (!(anchor instanceof HTMLAnchorElement)) return;

    const url = new URL(anchor.href, window.location.href);
    if (!['http:', 'https:'].includes(url.protocol) || url.hostname === 'localhost') return;

    event.preventDefault();
    await Browser.open({ url: url.href });
  });

  globalThis.AgentAssistantNative = Object.freeze({
    async share({ title = '', text = '', url = '' } = {}) {
      await Share.share({ title, text, url, dialogTitle: title || '分享' });
    },
    checkForUpdate() {
      return checkForAppUpdate({ force: true });
    },
  });

  window.addEventListener('DOMContentLoaded', () => void checkForAppUpdate({ force: true }), { once: true });
}
