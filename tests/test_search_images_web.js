'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const appSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/js/app.js'),
    'utf8',
);

function extractFunctionDeclaration(name) {
    const marker = `function ${name}(`;
    const start = appSource.indexOf(marker);
    assert.notEqual(start, -1, `missing ${name} in app.js`);

    const parametersEnd = appSource.indexOf(')', start + marker.length);
    assert.notEqual(parametersEnd, -1, `missing parameters for ${name}`);
    const bodyStart = appSource.indexOf('{', parametersEnd);
    assert.notEqual(bodyStart, -1, `missing body for ${name}`);
    let depth = 0;
    let quote = '';
    let escaped = false;
    for (let index = bodyStart; index < appSource.length; index += 1) {
        const char = appSource[index];
        if (escaped) {
            escaped = false;
            continue;
        }
        if (quote) {
            if (char === '\\') {
                escaped = true;
            } else if (char === quote) {
                quote = '';
            }
            continue;
        }
        if (['"', "'", '`'].includes(char)) {
            quote = char;
            continue;
        }
        if (char === '{') depth += 1;
        if (char === '}') {
            depth -= 1;
            if (depth === 0) return appSource.slice(start, index + 1);
        }
    }
    assert.fail(`unterminated ${name}`);
}

function citationContext() {
    const functionNames = [
        'firstCitationImageUrl',
        'citationImageUrl',
        'normalizeCitations',
        'renderCitationPanel',
    ];
    return {
        URL,
        escapeAttr: (value) => String(value),
        escapeHtml: (value) => String(value),
        hostFromUrl: (value) => new URL(value).hostname,
        isSafeContentUrl: (value) => /^https?:\/\//i.test(String(value)),
        source: functionNames.map(extractFunctionDeclaration).join('\n'),
        t: () => 'Sources',
        traceCopy: (_zh, en) => en,
        truncateText: (value, maxLength) => String(value).slice(0, maxLength),
    };
}

function renderCitations(citations) {
    const context = citationContext();
    return vm.runInNewContext(
        `${context.source}\nrenderCitationPanel(citations);`,
        { ...context, citations },
    );
}

test('citation cards render search thumbnails from metadata', () => {
    const html = renderCitations([{
        title: 'Image result',
        url: 'https://example.com/article',
        snippet: 'A result with a useful preview image.',
        source: 'web',
        metadata: {
            thumbnail_url: 'https://cdn.example.com/preview?id=42',
        },
    }]);

    assert.match(html, /class="citation-item has-image"/);
    assert.match(html, /class="citation-thumbnail"/);
    assert.match(html, /https:\/\/cdn\.example\.com\/preview\?id=42/);
    assert.match(html, /referrerpolicy="no-referrer"/);
    assert.match(html, /A result with a useful preview image\./);
});

test('citation cards ignore unsafe image URLs and keep text fallback', () => {
    const html = renderCitations([{
        title: 'Text-only result',
        url: 'https://example.com/article',
        metadata: {
            image_url: 'javascript:alert(1)',
        },
    }]);

    assert.doesNotMatch(html, /citation-thumbnail/);
    assert.doesNotMatch(html, /has-image/);
    assert.match(html, /Text-only result/);
});

test('failed citation thumbnails fall back to the text layout', () => {
    const source = extractFunctionDeclaration('handleCitationImageError');
    const state = {
        className: '',
        removed: false,
    };
    const citationItem = {
        classList: {
            remove: (className) => {
                state.className = className;
            },
        },
    };
    const thumbnailWrap = {
        remove: () => {
            state.removed = true;
        },
    };
    const image = {
        matches: (selector) => selector === '.citation-thumbnail',
        closest: (selector) => (
            selector === '.citation-item' ? citationItem : thumbnailWrap
        ),
    };

    vm.runInNewContext(
        `${source}\nhandleCitationImageError({ target: image });`,
        { image },
    );

    assert.equal(state.removed, true);
    assert.equal(state.className, 'has-image');
});

test('message image fallback ignores unrelated image errors', () => {
    const source = extractFunctionDeclaration('handleMessageImageError');
    const image = {
        matches: () => false,
        closest: () => {
            throw new Error('unrelated image must not be traversed');
        },
    };

    assert.doesNotThrow(() => vm.runInNewContext(
        `${source}\nhandleMessageImageError({ target: image });`,
        { image },
    ));
});

function imageContext(apiBase = '') {
    return {
        API_BASE: apiBase, VideoMedia: require('../web/static/js/video-media.js'),
        URL, escapeAttr: value => String(value).replace(/"/g, '&quot;'), escapeHtml: String,
        t: value => value, traceCopy: (zh, en) => en,
        suggestedImageDownloadName: () => 'image.png',
    };
}
function imageCode(...names) { return names.map(extractFunctionDeclaration).join('\n'); }
function renderImage(url, apiBase = '') {
    return vm.runInNewContext(imageCode('renderImageBlock', 'isImageUrl', 'isSafeContentUrl', 'isSafeDataImageUrl')
        + '\nrenderImageBlock(url, "Generated image")', { ...imageContext(apiBase), url });
}

test('generated images and preview/open links resolve against the Android API origin', () => {
    const url = '/static/generated/aigc/spark-regression.png';
    const html = renderImage(url, 'https://www.architect8.cn/');
    for (const attribute of ['src', 'data-media-preview-src', 'href']) {
        assert.ok(html.includes(`${attribute}="https://www.architect8.cn${url}"`), attribute);
    }
    assert.match(html, /data-image-retry/);
    assert.match(html, /data-image-fallback[^>]*hidden/);
});

test('web relative images, signed external images and base64 images remain supported', () => {
    for (const [url, base] of [['/static/test.png', ''],
        ['https://cdn.example.com/test.jpeg?Expires=123&Signature=abc', 'https://app.test'],
        ['data:image/png;base64,AAAA', 'https://app.test']]) {
        assert.ok(renderImage(url, base).includes(`src="${url}"`));
    }
});

test('image renderer rejects unsafe and non-image addresses', () => {
    for (const url of ['//evil.test/a.png', '/\\evil.test/a.png', 'javascript:alert(1)',
        'https://user:password@evil.test/a.png', '/static/video.mp4', 'data:image/svg+xml;base64,AAAA']) {
        assert.equal(renderImage(url, 'https://app.test'), '', url);
    }
});

function imageState() {
    const preview = { hidden: false, dataset: { mediaPreviewSrc: 'https://app.test/image.png' } };
    const fallback = { hidden: true };
    const status = { textContent: '' };
    const retry = { disabled: false };
    const parts = { '[data-media-preview-src]': preview, '[data-image-fallback]': fallback,
        '[data-image-status]': status, '[data-image-retry]': retry };
    const figure = { querySelector: selector => parts[selector], remove() { throw Error('must preserve figure'); } };
    const image = { matches: selector => selector === '.message-media img', closest: () => figure,
        removeAttribute: () => {}, src: preview.dataset.mediaPreviewSrc };
    parts.img = image;
    retry.closest = () => figure;
    return { preview, fallback, status, retry, image };
}

test('failed message images retain a visible explanation and allow retry through success', () => {
    const state = imageState();
    const context = { ...imageContext(), ...state };
    vm.createContext(context);
    vm.runInContext(imageCode('handleMessageImageError', 'handleMessageImageLoad', 'retryMessageImage'), context);
    context.handleMessageImageError({ target: state.image });
    assert.equal(state.preview.hidden, true);
    assert.equal(state.fallback.hidden, false);
    assert.match(state.status.textContent, /failed/i);
    context.retryMessageImage(state.retry);
    assert.equal(state.retry.disabled, true);
    assert.equal(state.image.src, state.preview.dataset.mediaPreviewSrc);
    assert.equal(state.image.loading, 'eager');
    assert.match(state.status.textContent, /loading/i);
    context.handleMessageImageLoad({ target: state.image });
    assert.equal(state.preview.hidden, false);
    assert.equal(state.fallback.hidden, true);
    assert.equal(state.retry.disabled, false);
});

test('failed retries keep their recovery controls and unrelated load events are ignored', () => {
    const state = imageState();
    const context = { ...imageContext(), ...state };
    vm.createContext(context);
    vm.runInContext(imageCode('handleMessageImageError', 'handleMessageImageLoad', 'retryMessageImage'), context);
    context.handleMessageImageError({ target: state.image });
    context.retryMessageImage(state.retry);
    context.handleMessageImageError({ target: state.image });
    assert.equal(state.retry.disabled, false);
    assert.equal(state.fallback.hidden, false);
    assert.doesNotThrow(() => context.handleMessageImageLoad({ target: { matches: () => false } }));
    assert.match(appSource, /document\.addEventListener\('load', handleMessageImageLoad, true\)/);
    assert.match(appSource, /retryMessageImage\(imageRetryButton\)/);
});
