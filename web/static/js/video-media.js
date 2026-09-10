(function initVideoMedia(root, factory) {
    const api = factory(root);
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.VideoMedia = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function createVideoMedia(root) {
    'use strict';

    const DEFAULT_LABELS = {
        video: '视频', download: '下载视频', open: '打开视频', downloading: '正在下载…',
        downloaded: '已开始下载。', failed: '视频下载失败，请重试或打开视频保存。',
        unavailable: '视频暂时无法播放，可以重试或打开视频。', seconds: '秒',
    };

    function escape(value) {
        return String(value || '').replace(/[&<>"']/g, (char) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[char]));
    }

    function resolveUrl(value, apiBase = '') {
        const url = String(value || '').trim();
        if (!url || /[\\\s]/.test(url) || url.startsWith('//')) return '';
        if (!url.startsWith('/') && !/^https?:\/\//i.test(url)) return '';
        try {
            const parsed = new URL(url, 'https://media.invalid');
            if (!['https:', 'http:'].includes(parsed.protocol) || parsed.username || parsed.password) return '';
            if (url.startsWith('/') && apiBase) {
                return resolveUrl(String(apiBase).replace(/\/+$/, '') + url);
            }
            return url;
        } catch { return ''; }
    }

    function isVideoUrl(value) {
        const url = resolveUrl(value);
        return Boolean(url && /\.(mp4|webm|ogg|ogv|mov|m4v)$/i.test(new URL(url, 'https://media.invalid').pathname));
    }

    function parseMarkdown(line) {
        let value = String(line || '').trim().replace(/^(?:[-*+]\s+|\d+[.)]\s+)/, '');
        // Model replies often emphasize an entire media link. Keep recognizing
        // the standalone link without treating prose or inline code as media.
        let emphasis;
        while ((emphasis = value.match(/^(\*\*|__|\*|_)(.+)\1$/))) {
            value = emphasis[2].trim();
        }
        const match = value.match(/^!?\[([^\]]*)\]\(([^\s)]+)\)$/);
        if (match && resolveUrl(match[2]) && (isVideoUrl(match[2]) || /^(video|视频)$/i.test(match[1]))) {
            return { url: match[2], title: match[1] };
        }
        return isVideoUrl(value) ? { url: value, title: '' } : null;
    }

    function getArtifacts(artifacts) {
        const videos = new Map();
        for (const item of Array.isArray(artifacts) ? artifacts : []) {
            if (!item || item.type !== 'video') continue;
            const url = resolveUrl(item.url);
            if (!url || !isVideoUrl(url) || (item.mime_type && !/^video\//i.test(String(item.mime_type)))) continue;
            if (!videos.has(url)) videos.set(url, { ...item, url });
        }
        return [...videos.values()];
    }

    function findMarkdownVideos(line) {
        // Ignore code spans before scanning links embedded in prose. Keep the
        // original line for text rendering so no surrounding content is lost.
        const value = String(line || '').replace(/(`+)[\s\S]*?\1/g, '');
        const videos = new Map();
        for (const match of value.matchAll(/!?\[[^\]]*\]\([^\s)]+\)/g)) {
            const item = parseMarkdown(match[0]);
            if (item && !videos.has(item.url)) videos.set(item.url, item);
        }
        return [...videos.values()];
    }

    // Called after fenced code is extracted. A local sibling is required evidence
    // before repairing a historical URL; unrelated external videos stay untouched.
    function normalizeMarkdownLines(lines) {
        const items = lines.map(parseMarkdown);
        const localUrls = new Set(items.filter(item => item
            && /^\/static\/generated\/aigc\/[\w-]+\.mp4$/.test(item.url)).map(item => item.url));
        const displayed = new Set();
        return lines.map((line, index) => {
            const item = items[index];
            if (!item) return line;
            const path = new URL(item.url, 'https://media.invalid').pathname;
            if (!localUrls.has(path)) return line;
            if (displayed.has(path)) return '';
            displayed.add(path);
            return item.url === path ? line : `[${item.title || DEFAULT_LABELS.video}](${path})`;
        });
    }

    function filename(value) {
        try {
            const name = decodeURIComponent(new URL(value, 'https://media.invalid').pathname.split('/').pop())
                .replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').slice(-160);
            if (/\.(mp4|webm|ogg|ogv|mov|m4v)$/i.test(name)) return name;
        } catch { /* An opaque media route can still be saved as MP4. */ }
        return 'superchat-video.mp4';
    }

    function render(value, title = '', options = {}) {
        const url = resolveUrl(value, options.apiBase);
        if (!url) return '';
        const labels = { ...DEFAULT_LABELS, ...options.labels };
        return `<figure class="message-media message-video">
            <video src="${escape(url)}" controls playsinline preload="metadata" aria-label="${escape(title || labels.video)}"></video>
            ${title ? `<figcaption>${escape(title)}</figcaption>` : ''}
            <div class="message-video-metadata" data-video-metadata hidden></div>
            <div class="message-video-actions">
                <button type="button" class="message-video-download" data-video-download-src="${escape(url)}"
                    data-video-download-name="${escape(filename(url))}">${escape(labels.download)}</button>
                <a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(labels.open)}</a>
                <span data-video-download-status role="status" aria-live="polite" hidden></span>
            </div>
            <p data-video-playback-status role="status" hidden></p>
        </figure>`;
    }

    async function download(value, options = {}) {
        const url = resolveUrl(value, options.apiBase);
        if (!url) throw new Error('Invalid video URL');
        const fetchImpl = options.fetchImpl || root.fetch.bind(root);
        const response = await fetchImpl(url, { mode: 'cors', credentials: 'same-origin' });
        if (!response.ok) throw new Error(`Video download failed: ${response.status}`);
        const blob = await response.blob();
        if (!blob.type.toLowerCase().startsWith('video/')) throw new Error('Not a video response');
        const saveBlob = options.saveBlob || ((file, name) => root.FileActions.downloadBlob(file, name));
        return saveBlob(blob, filename(url));
    }

    async function downloadFromButton(button, options = {}) {
        if (!button || button.disabled) return;
        const labels = { ...DEFAULT_LABELS, ...options.labels };
        const status = button.closest('.message-video')?.querySelector('[data-video-download-status]');
        const showStatus = (text) => {
            if (status) { status.textContent = text; status.hidden = false; }
        };
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        button.textContent = labels.downloading;
        showStatus(labels.downloading);
        try {
            await download(button.dataset.videoDownloadSrc, options);
            showStatus(labels.downloaded);
        } catch {
            showStatus(labels.failed);
        } finally {
            button.disabled = false;
            button.removeAttribute('aria-busy');
            button.textContent = labels.download;
        }
    }

    function updateMetadata(video, options = {}) {
        if (!video?.matches?.('.message-video video')) return;
        const metadata = video.closest('.message-video')?.querySelector('[data-video-metadata]');
        if (!metadata || !video.videoWidth || !video.videoHeight || !Number.isFinite(video.duration)) return;
        metadata.textContent = `${video.videoWidth}×${video.videoHeight} · ${video.duration.toFixed(2)} ${options.seconds || DEFAULT_LABELS.seconds}`;
        metadata.hidden = false;
    }

    function showPlaybackError(video, message = DEFAULT_LABELS.unavailable) {
        if (!video?.matches?.('.message-video video')) return;
        const status = video.closest('.message-video')?.querySelector('[data-video-playback-status]');
        if (status) { status.textContent = message; status.hidden = false; }
    }

    return { resolveUrl, parseMarkdown, normalizeMarkdownLines, filename, getArtifacts, findMarkdownVideos, render, download, downloadFromButton, updateMetadata, showPlaybackError };
}));
