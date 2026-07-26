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

test('failed message images remove the complete media figure', () => {
    const source = extractFunctionDeclaration('handleMessageImageError');
    const state = {
        removed: false,
    };
    const mediaFigure = {
        remove: () => {
            state.removed = true;
        },
    };
    const image = {
        matches: (selector) => selector === '.message-media img',
        closest: (selector) => (
            selector === '.message-media' ? mediaFigure : null
        ),
    };

    vm.runInNewContext(
        `${source}\nhandleMessageImageError({ target: image });`,
        { image },
    );

    assert.equal(state.removed, true);
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
