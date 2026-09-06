'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const VideoMedia = require('../web/static/js/video-media.js');
const FileActions = require('../web/static/js/file-actions.js');
const videoPath = '/static/generated/aigc/spark-video-5ad06019a7b44f9fa9b0810502f6c78e.mp4';
const traceMarkdown = `[纸鹤视频（480×864，~5.17 秒）](${videoPath})`;

test('the production trace link renders a video player and an explicit download button', () => {
    const parsed = VideoMedia.parseMarkdown(traceMarkdown);
    assert.deepEqual(parsed, { url: videoPath, title: '纸鹤视频（480×864，~5.17 秒）' });
    const html = VideoMedia.render(parsed.url, parsed.title);
    assert.match(html, /<video[^>]+controls[^>]+playsinline/);
    assert.ok(html.includes(`src="${videoPath}"`));
    assert.match(html, /data-video-download-src=/);
    assert.match(html, /下载视频/);
    assert.match(html, /打开视频/);
    assert.doesNotMatch(html, /autoplay/);
});

test('video Markdown supports generated labels, bullet links, query strings and legacy labels', () => {
    for (const line of [`[AI 生视频 1](${videoPath})`, `- [纸鹤](${videoPath}?v=1#t=0)`,
        `![视频](${videoPath})`, videoPath, '[video](https://media.test/stream/123)']) {
        assert.ok(VideoMedia.parseMarkdown(line), line);
    }
    for (const line of ['[来源](https://example.test/article)', '![猫](/static/cat.png)',
        `[not video](javascript:alert(1))`, '`' + traceMarkdown + '`']) {
        assert.equal(VideoMedia.parseMarkdown(line), null);
    }
});

test('video sources resolve against API_BASE for Android and retain query parameters', () => {
    const html = VideoMedia.render(videoPath + '?v=1', '纸鹤', { apiBase: 'https://www.architect8.cn/' });
    assert.ok(html.includes(`src="https://www.architect8.cn${videoPath}?v=1"`));
    assert.ok(html.includes(`data-video-download-src="https://www.architect8.cn${videoPath}?v=1"`));
    assert.equal(VideoMedia.resolveUrl('https://cdn.test/movie.webm', 'https://www.architect8.cn'), 'https://cdn.test/movie.webm');
});

test('video renderer rejects unsafe sources and escapes captions and attributes', () => {
    for (const url of ['javascript:alert(1)', 'data:video/mp4;base64,AAAA', '//evil.test/a.mp4',
        '/\\evil.test/a.mp4', 'https://user:secret@host.test/a.mp4']) {
        assert.equal(VideoMedia.render(url, 'video'), '', url);
    }
    const html = VideoMedia.render(videoPath, '<img src=x onerror="alert(1)">');
    assert.doesNotMatch(html, /<img/);
    assert.match(html, /&lt;img/);
});

test('video filenames are derived from the URL, not a caption claiming dimensions', () => {
    assert.equal(VideoMedia.filename(videoPath), 'spark-video-5ad06019a7b44f9fa9b0810502f6c78e.mp4');
    assert.equal(VideoMedia.filename('https://video.test/stream?id=1'), 'superchat-video.mp4');
    assert.doesNotMatch(VideoMedia.filename('/a/%22%2Fbad.mp4'), /["/]/);
});

test('video download fetches the MP4 directly and delegates a video Blob to native storage', async () => {
    const calls = [];
    const root = { AgentAssistantNative: { downloadBlob: async (payload) => {
        calls.push(payload); return { saved: true };
    } } };
    const result = await VideoMedia.download(videoPath, {
        apiBase: 'https://www.architect8.cn',
        fetchImpl: async (url) => {
            assert.equal(url, 'https://www.architect8.cn' + videoPath);
            assert.ok(!url.includes('/api/media/download'));
            return new Response('video fixture', { headers: { 'Content-Type': 'video/mp4' } });
        },
        saveBlob: (blob, filename) => FileActions.downloadBlob(blob, filename, { root }),
    });
    assert.equal(result.method, 'native');
    assert.equal(calls[0].blob.type, 'video/mp4');
    assert.equal(calls[0].filename, VideoMedia.filename(videoPath));
});

test('video downloads use the browser save path and retain the mp4 filename', async () => {
    const link = { click() {}, remove() {} };
    const root = { URL: { createObjectURL: () => 'blob:video', revokeObjectURL() {} }, setTimeout() {} };
    const result = await VideoMedia.download(videoPath, {
        fetchImpl: async () => new Response('video', { headers: { 'Content-Type': 'video/mp4' } }),
        saveBlob: (blob, filename) => FileActions.downloadBlob(blob, filename, {
            root, documentApi: { createElement: () => link, body: { appendChild() {} } },
        }),
    });
    assert.equal(result.method, 'browser');
    assert.equal(link.download, VideoMedia.filename(videoPath));
    assert.equal(link.href, 'blob:video');
});

test('HTTP failures, HTML responses and native save errors are surfaced without false success', async () => {
    for (const response of [new Response('gone', { status: 410 }),
        new Response('<html>login</html>', { headers: { 'Content-Type': 'text/html' } })]) {
        await assert.rejects(VideoMedia.download(videoPath, {
            fetchImpl: async () => response,
            saveBlob: async () => assert.fail('invalid response must not be saved'),
        }));
    }
    await assert.rejects(VideoMedia.download(videoPath, {
        fetchImpl: async () => new Response('video', { headers: { 'Content-Type': 'video/mp4' } }),
        saveBlob: async () => { throw new Error('storage denied'); },
    }), /storage denied/);
});

function downloadButton() {
    const status = { textContent: '', hidden: true };
    const button = { disabled: false, textContent: '下载视频', dataset: { videoDownloadSrc: videoPath },
        closest: () => ({ querySelector: () => status }), setAttribute() {}, removeAttribute() {} };
    return { button, status };
}

test('download button prevents duplicate clicks, reports completion and becomes usable again', async () => {
    const { button, status } = downloadButton();
    let release;
    const pending = VideoMedia.downloadFromButton(button, {
        fetchImpl: () => new Promise((resolve) => { release = resolve; }), saveBlob: async () => ({}),
    });
    assert.equal(button.disabled, true);
    await VideoMedia.downloadFromButton(button, { fetchImpl: () => assert.fail('duplicate fetch') });
    release(new Response('video', { headers: { 'Content-Type': 'video/mp4' } }));
    await pending;
    assert.equal(button.disabled, false);
    assert.match(status.textContent, /下载/);
    assert.equal(status.hidden, false);
    assert.equal(button.textContent, '下载视频');
});

test('download button displays retry guidance and is reenabled on failure', async () => {
    const { button, status } = downloadButton();
    await VideoMedia.downloadFromButton(button, { fetchImpl: async () => { throw new Error('offline'); } });
    assert.equal(button.disabled, false);
    assert.match(status.textContent, /失败/);
    assert.equal(status.hidden, false);
});

test('the real chat Markdown renderer routes arbitrary video labels through VideoMedia', () => {
    const app = fs.readFileSync(path.join(__dirname, '../web/static/js/app.js'), 'utf8');
    const render = app.match(/function renderMediaMarkdown\(line\) \{[\s\S]*?\n\}/)[0];
    const html = vm.runInNewContext(`${render}; renderMediaMarkdown(line)`, {
        VideoMedia, globalThis: { VideoMedia }, line: traceMarkdown,
        renderVideoBlock: (url, title) => VideoMedia.render(url, title),
        isImageUrl: () => false, isVideoUrl: () => false,
    });
    assert.match(html, /<video/);
    assert.match(html, /data-video-download-src/);
    assert.match(app, /closest\('\[data-video-download-src\]'\)/);
    const index = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
    assert.ok(index.indexOf('video-media.js') < index.indexOf('app.js?'));
});

test('the player displays dimensions and duration read from the actual MP4', () => {
    const metadata = { hidden: true, textContent: '' };
    VideoMedia.updateMetadata({ videoWidth: 864, videoHeight: 480, duration: 5.1718,
        matches: () => true, closest: () => ({ querySelector: () => metadata }) });
    assert.equal(metadata.textContent, '864×480 · 5.17 秒');
    assert.equal(metadata.hidden, false);
});

test('playback failures keep the video block and offer the open/download fallback', () => {
    const status = { hidden: true, textContent: '' };
    VideoMedia.showPlaybackError({ matches: () => true, closest: () => ({ querySelector: () => status }) });
    assert.equal(status.hidden, false);
    assert.match(status.textContent, /打开视频/);
    assert.doesNotThrow(() => VideoMedia.showPlaybackError({}));
});
