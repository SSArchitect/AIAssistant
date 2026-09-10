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

test('the chat formatter still renders text and video when a cached module has no normalizer', () => {
    const app = fs.readFileSync(path.join(__dirname, '../web/static/js/app.js'), 'utf8');
    const format = app.match(/function formatContent\(text, options = \{\}\) \{[\s\S]*?\n\}/)[0];
    const legacy = { ...VideoMedia };
    delete legacy.normalizeMarkdownLines;
    const context = {
        VideoMedia: legacy,
        renderMediaMarkdown: line => {
            const item = legacy.parseMarkdown(line);
            return item ? legacy.render(item.url, item.title) : '';
        },
        renderInlineMarkdown: value => value, isMarkdownTableStart: () => false,
    };
    assert.equal(vm.runInNewContext(`${format}; formatContent('正常回复')`, context), '<p>正常回复</p>');
    context.text = traceMarkdown;
    assert.match(vm.runInNewContext(`${format}; formatContent(text)`, context), /<video /);
});

test('historical duplicate generated videos use the local sibling URL and keep the first caption', () => {
    const lines = [`[小兔子](https://mini.amini.net${videoPath}?download=1#t=0)`, '', '视频小档案：',
        `[AI 生视频 1](${videoPath})`];
    const result = VideoMedia.normalizeMarkdownLines(lines);
    assert.equal(result[0], `[小兔子](${videoPath})`);
    assert.equal(result.filter(line => VideoMedia.parseMarkdown(line)).length, 1);
    assert.ok(result.includes('视频小档案：'));
    assert.ok(lines[0].includes('mini.amini.net')); // Do not mutate stored messages.
});

test('history normalization preserves distinct videos and external links without a matching local path', () => {
    const lines = [`[外部](https://cdn.test${videoPath})`, '[视频](https://cdn.test/other.mp4)',
        '[本地](/static/generated/aigc/another.mp4)', '正文'];
    assert.deepEqual(VideoMedia.normalizeMarkdownLines(lines), lines);
    const sameFilename = [`[外部](https://cdn.test/other/${VideoMedia.filename(videoPath)})`, traceMarkdown];
    assert.deepEqual(VideoMedia.normalizeMarkdownLines(sameFilename), sameFilename);
    assert.deepEqual(VideoMedia.normalizeMarkdownLines([traceMarkdown, traceMarkdown]), [traceMarkdown, '']);
});

test('the chat formatter repairs the real duplicate pattern, excluding fenced code and media-disabled output', () => {
    const app = fs.readFileSync(path.join(__dirname, '../web/static/js/app.js'), 'utf8');
    const format = app.match(/function formatContent\(text, options = \{\}\) \{[\s\S]*?\n\}/)[0];
    const text = `[小兔子](https://mini.amini.net${videoPath})\n\n${traceMarkdown}`;
    const context = {
        VideoMedia, text, renderMediaMarkdown: line => {
            const item = VideoMedia.parseMarkdown(line);
            return item ? VideoMedia.render(item.url, item.title, { apiBase: 'https://app.test' }) : '';
        }, renderInlineMarkdown: value => value, isMarkdownTableStart: () => false,
        escapeHtml: value => value, escapeAttr: value => value, renderCodeCopyButton: () => '',
    };
    const html = vm.runInNewContext(`${format}; formatContent(text)`, context);
    assert.equal((html.match(/<video /g) || []).length, 1);
    assert.ok(html.includes(`src="https://app.test${videoPath}"`));
    assert.ok(!html.includes('mini.amini.net'));
    const disabled = vm.runInNewContext(`${format}; formatContent(text, { allowMedia: false })`, context);
    assert.ok(disabled.includes('mini.amini.net'));
    const code = vm.runInNewContext(`${format}; formatContent(text)`, {
        ...context, text: `[小兔子](https://mini.amini.net${videoPath})\n\n\`\`\`md\n${traceMarkdown}\n\`\`\``,
    });
    assert.ok(code.includes(`src="https://mini.amini.net${videoPath}"`));
});

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
    const render = app.match(/function renderMediaMarkdown\(line, options = \{\}\) \{[\s\S]*?\n\}/)[0];
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

test('emphasis around standalone video links still creates playable media', () => {
    for (const wrapper of ['**', '__', '*', '_', '***']) {
        for (const prefix of ['', '- ', '1. ']) {
            const line = `${prefix}${wrapper}[▶️ 点击观看：令的加油视频](${videoPath})${wrapper}`;
            assert.deepEqual(VideoMedia.parseMarkdown(line), { url: videoPath, title: '▶️ 点击观看：令的加油视频' }, line);
        }
    }
    for (const line of [`**说明 ${traceMarkdown}**`, `**\`${traceMarkdown}\`**`,
        `**${traceMarkdown}*`, '**[网页](https://example.test/article)**',
        `**${traceMarkdown} ${traceMarkdown}**`]) {
        assert.equal(VideoMedia.parseMarkdown(line), null, line);
    }
});

test('the formatter renders the bold video link from run 1e94f2e9 and preserves code-only views', () => {
    const app = fs.readFileSync(path.join(__dirname, '../web/static/js/app.js'), 'utf8');
    const format = app.match(/function formatContent\(text, options = \{\}\) \{[\s\S]*?\n\}/)[0];
    const link = `**[▶️ 点击观看：令的加油视频](${videoPath})**`;
    const context = {
        VideoMedia, text: `视频出炉啦\n\n${link}\n\n视频规格`,
        renderMediaMarkdown: line => {
            const item = VideoMedia.parseMarkdown(line);
            return item ? VideoMedia.render(item.url, item.title, { apiBase: 'https://app.test' }) : '';
        },
        renderInlineMarkdown: value => value, isMarkdownTableStart: () => false,
        escapeHtml: value => value, escapeAttr: value => value, renderCodeCopyButton: () => '',
    };
    const html = vm.runInNewContext(`${format}; formatContent(text)`, context);
    assert.equal((html.match(/<video /g) || []).length, 1);
    assert.ok(html.includes(`src="https://app.test${videoPath}"`));
    assert.ok(html.includes('下载视频'));
    assert.ok(!html.includes('**['));
    const disabled = vm.runInNewContext(`${format}; formatContent(text, { allowMedia: false })`, context);
    assert.ok(!disabled.includes('<video '));
    const code = vm.runInNewContext(`${format}; formatContent(text)`, { ...context, text: '```md\n' + link + '\n```' });
    assert.ok(!code.includes('<video '));
    assert.ok(code.includes(link));
});

// Exercise the actual inline + block renderers together: a stubbed inline
// renderer concealed the unclickable relative links in production message 1836.
function createChatRenderContext(apiBase = 'https://www.architect8.cn') {
    const app = fs.readFileSync(path.join(__dirname, '../web/static/js/app.js'), 'utf8');
    const names = ['formatContent', 'renderInlineMarkdown', 'renderMediaMarkdown',
        'renderVideoBlock', 'videoMediaLabels', 'renderSafeLink', 'isSafeContentUrl',
        'isSafeDataImageUrl', 'isImageUrl', 'isVideoUrl', 'isMarkdownTableStart',
        'isMarkdownTableRow', 'splitMarkdownTableRow', 'isMarkdownTableSeparatorCell',
        'renderArtifactPanel', 'normalizeArtifacts', 'renderDriveArtifactCard',
        'renderMessageHtml', 'appendStreamingAssistantMessage'];
    const source = names.map(name => app.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0]).join('\n');
    const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[char]));
    const context = vm.createContext({
        VideoMedia, API_BASE: apiBase, t: value => value,
        escapeHtml: escape, escapeAttr: escape, renderCodeCopyButton: () => '',
    });
    vm.runInContext(source, context);
    return context;
}

function renderChatFixture(text, options = {}, apiBase) {
    return createChatRenderContext(apiBase).formatContent(text, options);
}

const latestVideoPath = '/static/generated/aigc/spark-video-7c81872152c44a5ca7846782128cb04a.mp4';
const latestVideoLink = `[陈千语卖萌跳舞视频（MP4）](${latestVideoPath})`;

test('production message 1836 renders a playable video with an emoji before its bold link', () => {
    const html = renderChatFixture(`跳起来啦～老板请看：\n\n🎬 **${latestVideoLink}**\n\n**视频信息：**\n- 📐 画幅：480 × 864 竖屏\n- ⏱️ 时长：约 5.17 秒`);
    assert.equal((html.match(/<video /g) || []).length, 1);
    assert.ok(html.includes(`src="https://www.architect8.cn${latestVideoPath}"`));
    assert.ok(html.includes(`href="https://www.architect8.cn${latestVideoPath}"`));
    assert.ok(html.includes('data-video-download-src'));
    assert.ok(html.includes('🎬'));
    assert.ok(html.includes('画幅：480 × 864'));
    assert.ok(!html.includes(latestVideoLink));
});

test('embedded video links preserve surrounding prose, emphasis, lists and multiple videos', () => {
    const other = '[另一个](/static/generated/aigc/another.mp4)';
    for (const line of [`请看 **${latestVideoLink}**，可以下载。`,
        `**请看 ${latestVideoLink}，可以下载。**`, `- 请看 ${latestVideoLink}，可以下载。`]) {
        const html = renderChatFixture(line);
        assert.equal((html.match(/<video /g) || []).length, 1);
        assert.ok(html.includes('请看'));
        assert.ok(html.includes('可以下载。'));
        assert.ok(!/<p>(?:(?!<\/p>)[^])*<figure/.test(html), 'player must not be nested in a paragraph');
    }
    const html = renderChatFixture(`请看 ${latestVideoLink} 和 ${other}，${latestVideoLink} 是第一个。`);
    assert.equal((html.match(/<video /g) || []).length, 2);
    assert.ok(html.includes('是第一个。'));
});

test('relative inline video links remain clickable with media disabled and use the client API origin', () => {
    for (const base of ['', 'https://www.architect8.cn']) {
        const html = renderChatFixture(`请看 **${latestVideoLink}**。`, { allowMedia: false }, base);
        assert.ok(!html.includes('<video '));
        assert.ok(html.includes(`href="${base}${latestVideoPath}"`));
        assert.ok(html.includes('<strong><a'));
    }
});

test('embedded video detection excludes inline and fenced code, unsafe URLs and ordinary links', () => {
    for (const text of ['`' + latestVideoLink + '`', '``' + latestVideoLink + '``',
        '```md\n🎬 **' + latestVideoLink + '**\n```',
        '[bad](//evil.test/a.mp4)', '[bad](/\\evil.test/a.mp4)',
        '[bad](javascript:alert)', '[网页](https://example.test/article)']) {
        assert.ok(!renderChatFixture(text).includes('<video '), text);
    }
    const html = renderChatFixture('`' + latestVideoLink + '` 请看 ' + traceMarkdown);
    assert.equal((html.match(/<video /g) || []).length, 1);
    assert.ok(!html.includes(`src="https://www.architect8.cn${latestVideoPath}"`));
    for (const url of ['//evil.test/a.mp4', '/\\evil.test/a.mp4']) {
        assert.ok(!renderChatFixture(`[bad](${url})`, { allowMedia: false }).includes('<a '));
    }
});

const typedVideo = { type: 'video', item_id: latestVideoPath, url: latestVideoPath,
    title: '生成视频', mime_type: 'video/mp4' };

function addMessageChromeStubs(context) {
    Object.assign(context, {
        currentConversationId: 'c', currentAgentId: 'super_chat', STREAM_TYPEWRITER: null,
        renderAssistantActions: () => '', renderUserMessageActions: () => '',
        renderProcessPanel: () => '', renderProcessPanelInto() {}, renderMessageDivider: () => '',
        renderInlineLongTask: () => '', renderApprovalPanel: () => '', renderCitationPanel: () => '',
        renderInputMeta: () => '', renderApprovalCards: () => '',
        shouldFollowConversationStream: () => false, updateCopyButtonState() {}, updateAssistantActions() {},
        scheduleTaskResultRead() {}, renderPersistedFollowUpsAfterMessage() {},
        updateFollowUpButtonsState() {}, updateRegenerateButtonsState() {},
        ThinkingProcess: require('../web/static/js/thinking-process.js'),
    });
}

test('history renders typed videos even with no model link and never duplicates Markdown players', () => {
    const context = createChatRenderContext();
    addMessageChromeStubs(context);
    for (const prose of ['', '已经做好了，没有链接。', `🎬 **${latestVideoLink}**`, latestVideoLink]) {
        const html = context.renderMessageHtml('assistant', prose, [], '', '', [], '', '', [], [typedVideo]);
        assert.equal((html.match(/<video /g) || []).length, 1, prose);
        assert.ok(html.includes(`src="https://www.architect8.cn${latestVideoPath}"`));
        assert.ok(html.includes('data-video-download-src'));
        assert.ok(!html.includes('data-drive-artifact-id'));
    }
});

test('stream finalization uses typed artifacts with no link or arbitrarily formatted prose', () => {
    for (const prose of ['没有链接的完成说明', `🎬 **${latestVideoLink}**`]) {
        const context = createChatRenderContext();
        addMessageChromeStubs(context);
        const children = {};
        const element = () => ({ dataset: {}, classList: { toggle() {}, remove() {} },
            addEventListener() {}, remove() {}, contains: () => true });
        const div = { ...element(), querySelector: selector => children[selector] ||= element() };
        Object.assign(context, {
            document: { createElement: () => div },
            messagesContainer: { querySelector: () => null, appendChild() {} },
            createAdaptiveTypingBuffer: render => ({ setImmediate: render, enqueue: render, reset() {} }),
        });
        const view = context.appendStreamingAssistantMessage('', 'c');
        view.finalize({ response: prose, artifacts: [typedVideo], events: [] });
        const html = children['.streaming-content'].innerHTML + children['.streaming-artifacts'].innerHTML;
        assert.equal((html.match(/<video /g) || []).length, 1);
        assert.ok(html.includes(`src="https://www.architect8.cn${latestVideoPath}"`));
        assert.ok(html.includes('data-video-download-src'));
    }
});

test('typed video artifacts reject invalid media, deduplicate by URL, and do not suppress legacy fallback', () => {
    const context = createChatRenderContext();
    for (const item of [null, { ...typedVideo, url: '//evil.test/a.mp4' },
        { ...typedVideo, url: 'javascript:x' }, { ...typedVideo, mime_type: 'text/html' },
        { ...typedVideo, mime_type: 42 }, { ...typedVideo, url: '/page.html' }]) {
        assert.equal(VideoMedia.getArtifacts([item]).length, 0);
        assert.equal(context.renderArtifactPanel([item]), '');
        assert.match(context.formatContent(latestVideoLink, { artifacts: [item] }), /<video /);
    }
    assert.equal(VideoMedia.getArtifacts([typedVideo, { ...typedVideo, item_id: 'other' }]).length, 1);
    assert.equal((context.renderArtifactPanel([typedVideo, typedVideo]).match(/<video /g) || []).length, 1);
});
