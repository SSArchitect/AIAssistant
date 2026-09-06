(function initFileActions(root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    } else {
        root.FileActions = api;
    }
}(typeof globalThis !== 'undefined' ? globalThis : this, function createFileActions() {
    'use strict';

    const DOWNLOAD_REVOKE_DELAY_MS = 30000;

    function nativeBridge(root = globalThis) {
        const bridge = root?.AgentAssistantNative;
        return bridge && typeof bridge === 'object' ? bridge : null;
    }

    function hasNativeDownload(root = globalThis) {
        return typeof nativeBridge(root)?.downloadBlob === 'function';
    }

    function triggerBrowserDownload(href, filename, options = {}) {
        const documentApi = options.documentApi || globalThis.document;
        const link = documentApi.createElement('a');
        link.href = href;
        link.download = String(filename || 'download');
        documentApi.body.appendChild(link);
        link.click();
        link.remove();
    }

    async function downloadBlob(blob, filename, options = {}) {
        if (!blob) {
            throw new TypeError('A Blob is required for download.');
        }

        const rootApi = options.root || globalThis;
        const bridge = nativeBridge(rootApi);
        if (typeof bridge?.downloadBlob === 'function') {
            const result = await bridge.downloadBlob({ blob, filename: String(filename || 'download') });
            return { method: 'native', result };
        }

        const urlApi = options.urlApi || rootApi.URL;
        if (!urlApi?.createObjectURL || !urlApi?.revokeObjectURL) {
            throw new Error('Browser downloads are unavailable.');
        }
        const objectUrl = urlApi.createObjectURL(blob);
        triggerBrowserDownload(objectUrl, filename, options);
        const schedule = options.setTimeoutApi || rootApi.setTimeout;
        schedule(() => urlApi.revokeObjectURL(objectUrl), DOWNLOAD_REVOKE_DELAY_MS);
        return { method: 'browser' };
    }

    async function copyImageBlob(blob, filename, options = {}) {
        if (!blob) {
            throw new TypeError('An image Blob is required for copying.');
        }

        const rootApi = options.root || globalThis;
        const bridge = nativeBridge(rootApi);
        if (typeof bridge?.copyImage === 'function') {
            const result = await bridge.copyImage({ blob, filename: String(filename || 'image.png') });
            return { method: 'native', result };
        }

        const clipboard = options.clipboard || rootApi.navigator?.clipboard;
        const ClipboardItemCtor = options.ClipboardItemCtor || rootApi.ClipboardItem;
        if (typeof clipboard?.write !== 'function' || typeof ClipboardItemCtor !== 'function') {
            const error = new Error('Image clipboard is unavailable.');
            error.code = 'IMAGE_CLIPBOARD_UNSUPPORTED';
            throw error;
        }
        await clipboard.write([
            new ClipboardItemCtor({ 'image/png': blob }),
        ]);
        return { method: 'browser' };
    }

    return {
        copyImageBlob,
        downloadBlob,
        hasNativeDownload,
        triggerBrowserDownload,
    };
}));
