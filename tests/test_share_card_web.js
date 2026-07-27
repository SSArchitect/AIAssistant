'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const {
    buildShareCardFilename,
    parseMarkdownBlocks,
    renderShareCardBlob,
    renderShareCardCanvas,
    resolveShareCardImageFetchUrl,
    sanitizeInlineText,
    wrapMeasuredText,
} = require('../web/static/js/share-card.js');

const appSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/js/app.js'),
    'utf8',
);
const indexSource = fs.readFileSync(
    path.resolve(__dirname, '../web/index.html'),
    'utf8',
);
const styleSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/css/style.css'),
    'utf8',
);

function createFakeCanvasCapture() {
    const drawnText = [];
    const drawnImages = [];
    const context = {
        font: '',
        fillStyle: '',
        strokeStyle: '',
        lineWidth: 1,
        textAlign: 'left',
        textBaseline: 'alphabetic',
        measureText: (value) => ({ width: Array.from(String(value)).length * 13 }),
        createLinearGradient: () => ({ addColorStop: () => {} }),
        fillRect: () => {},
        save: () => {},
        restore: () => {},
        beginPath: () => {},
        arc: () => {},
        fill: () => {},
        moveTo: () => {},
        lineTo: () => {},
        arcTo: () => {},
        closePath: () => {},
        clip: () => {},
        stroke: () => {},
        drawImage: (...args) => drawnImages.push(args),
        fillText: (value) => drawnText.push(String(value)),
    };
    return {
        canvas: {
            width: 0,
            height: 0,
            getContext: () => context,
            toBlob: (callback, type) => callback(new Blob(['png'], { type })),
        },
        drawnText,
        drawnImages,
    };
}

test('share card parser keeps useful Markdown structure without interactive markup', () => {
    const blocks = parseMarkdownBlocks(`
# 发布计划

先完成 **核心流程**，再处理 [帮助文档](https://example.com/docs)。

- 支持中文和 emoji 🚀
- 支持长回答

> 所有图片都在本地生成。

| 项目 | 状态 |
| --- | --- |
| 卡片 | 完成 |

\`\`\`js
const ready = true;
\`\`\`
`);

    assert.deepEqual(
        blocks.map((block) => block.type),
        ['heading', 'paragraph', 'list', 'quote', 'table', 'code'],
    );
    assert.equal(blocks[0].text, '发布计划');
    assert.match(blocks[1].text, /核心流程.*帮助文档/);
    assert.doesNotMatch(blocks[1].text, /https:\/\/example\.com/);
    assert.deepEqual(blocks[4].header, ['项目', '状态']);
    assert.deepEqual(blocks[4].rows[0], ['卡片', '完成']);
    assert.equal(blocks[5].language, 'js');
    assert.match(blocks[5].text, /const ready = true/);
});

test('share card text sanitizing removes HTML and preserves readable content', () => {
    const text = sanitizeInlineText(
        '<script>alert(1)</script> **结论** &amp; [详情](https://example.com) ![图示](https://cdn.example.com/a.png)',
    );

    assert.doesNotMatch(text, /<script>|<\/script>|https:\/\/cdn/);
    assert.match(text, /alert\(1\) 结论 & 详情 图片：图示/);
});

test('share card parser recognizes standalone Markdown and raw image URLs', () => {
    const blocks = parseMarkdownBlocks(`
图片如下：

![生成的海边插画](https://cdn.example.com/generated/card.png)

/static/generated/local-image.webp
`);

    assert.deepEqual(blocks.map((block) => block.type), ['paragraph', 'image', 'image']);
    assert.deepEqual(blocks[1], {
        type: 'image',
        alt: '生成的海边插画',
        url: 'https://cdn.example.com/generated/card.png',
    });
    assert.equal(blocks[2].url, '/static/generated/local-image.webp');
});

test('share card image URLs use direct same-origin access and proxy external origins', () => {
    const options = { locationOrigin: 'https://chat.example.com' };

    assert.equal(
        resolveShareCardImageFetchUrl('https://chat.example.com/media/a.png', options),
        'https://chat.example.com/media/a.png',
    );
    assert.equal(
        resolveShareCardImageFetchUrl('/static/generated/a.png', options),
        '/static/generated/a.png',
    );
    assert.equal(
        resolveShareCardImageFetchUrl('https://cdn.example.com/a.png', options),
        '/api/media/download?url=https%3A%2F%2Fcdn.example.com%2Fa.png',
    );
    assert.equal(resolveShareCardImageFetchUrl('javascript:alert(1)', options), '');
});

test('share card wrapping supports Chinese, words, and overlong tokens', () => {
    const measure = (value) => Array.from(String(value)).length * 10;
    const lines = wrapMeasuredText(measure, '中文 card abcdefghijklmnop', 60);

    assert.ok(lines.length >= 4);
    assert.ok(lines.every((line) => measure(line) <= 60));
    assert.equal(lines.join('').replace(/\s/g, ''), '中文cardabcdefghijklmnop');
});

test('share card filename is safe and predictable', () => {
    const filename = buildShareCardFilename(
        '如何分享 / AI:* 回答？',
        new Date(2026, 6, 28),
    );

    assert.equal(filename, '如何分享-AI-回答？-20260728.png');
    assert.doesNotMatch(filename, /[\\/:*"<>|]/);
});

test('share card canvas renderer creates a bounded local-only long image', () => {
    const { canvas, drawnText } = createFakeCanvasCapture();
    const rendered = renderShareCardCanvas({
        question: '如何把回答分享出去？',
        answer: `# 结论\n\n${'这是一个很长的本地回答。'.repeat(4000)}`,
        brand: '测试工作台',
        product: 'Super Chat',
        questionLabel: '提问',
        answerLabel: 'AI 回答',
        truncatedLabel: '内容过长',
        footer: '本地生成',
        createCanvas: () => canvas,
    });

    assert.equal(rendered.width, 1080);
    assert.ok(rendered.height >= 1080);
    assert.ok(rendered.height <= 14400);
    assert.equal(rendered.truncated, true);
    assert.ok(drawnText.includes('测试工作台'));
    assert.ok(drawnText.includes('AI 回答'));
});

test('share card keeps the question clear of the body and gives table rows breathing room', () => {
    const { canvas } = createFakeCanvasCapture();
    const rendered = renderShareCardCanvas({
        question: '可以给我看看错误和正确姿势的对比图吗？',
        answer: `
| 错误姿势 | 主要表现 | 风险点 | 怎么改 |
| --- | --- | --- | --- |
| 挺腰、骨盆前倾 | 腰椎拱得很高，靠腰发力 | 腰椎压力巨大 | 先做骨盆后倾，把腰贴向地面 |
| 骨盆过度后倾 | 髋抬不到位，臀部没感觉 | 大腿前侧发力主导 | 抬到肩髋膝一线 |
`,
        createCanvas: () => canvas,
    });

    const lastQuestionBaseline = 202 + ((rendered.layout.questionLines.length - 1) * 48);
    assert.ok(rendered.layout.bodyY - lastQuestionBaseline >= 36);
    const tableRows = rendered.layout.bodyLayouts.filter((item) => item.kind === 'tableRow');
    assert.equal(tableRows.length, 3);
    assert.ok(tableRows.every((row) => (
        row.height >= row.top + row.bottom + (row.lines.length * row.lineHeight) + 28
    )));
});

test('share card canvas draws loaded images at a bounded aspect ratio', () => {
    const { canvas, drawnImages } = createFakeCanvasCapture();
    const imageUrl = 'https://cdn.example.com/generated/wide.png';
    const fakeImage = { naturalWidth: 1600, naturalHeight: 900 };
    const rendered = renderShareCardCanvas({
        question: '给我看图片',
        answer: `![海边图片](${imageUrl})`,
        imageAssets: new Map([[
            imageUrl,
            { status: 'loaded', image: fakeImage, width: 1600, height: 900 },
        ]]),
        createCanvas: () => canvas,
    });

    const imageLayout = rendered.layout.bodyLayouts.find((item) => item.kind === 'image');
    assert.ok(imageLayout);
    assert.equal(drawnImages.length, 1);
    assert.equal(drawnImages[0][0], fakeImage);
    assert.ok(imageLayout.drawWidth <= 876);
    assert.ok(imageLayout.drawHeight <= 680);
    assert.equal(
        Math.round((imageLayout.drawWidth / imageLayout.drawHeight) * 100),
        Math.round((1600 / 900) * 100),
    );
});

test('share card uses an image placeholder when an answer image cannot load', () => {
    const { canvas, drawnText } = createFakeCanvasCapture();
    const rendered = renderShareCardCanvas({
        answer: '![结果图](https://cdn.example.com/missing.png)',
        imageFallbackLabel: '图片未能加载',
        createCanvas: () => canvas,
    });

    assert.ok(rendered.layout.bodyLayouts.some((item) => item.kind === 'imagePlaceholder'));
    assert.ok(drawnText.some((text) => text.includes('图片未能加载')));
});

test('share card blob pipeline loads external images through the media proxy', async () => {
    const { canvas, drawnImages } = createFakeCanvasCapture();
    const requested = [];
    const revoked = [];
    class FakeImage {
        set src(value) {
            this.source = value;
            this.naturalWidth = 1200;
            this.naturalHeight = 800;
            queueMicrotask(() => this.onload?.());
        }
    }
    const rendered = await renderShareCardBlob({
        answer: '![生成图](https://cdn.example.com/generated.png)',
        locationOrigin: 'http://127.0.0.1:8080',
        fetchApi: async (url) => {
            requested.push(url);
            return {
                ok: true,
                status: 200,
                blob: async () => new Blob(['image'], { type: 'image/png' }),
            };
        },
        ImageCtor: FakeImage,
        urlApi: {
            createObjectURL: () => 'blob:share-card-image',
            revokeObjectURL: (url) => revoked.push(url),
        },
        createCanvas: () => canvas,
    });

    assert.deepEqual(requested, [
        '/api/media/download?url=https%3A%2F%2Fcdn.example.com%2Fgenerated.png',
    ]);
    assert.equal(rendered.imageCount, 1);
    assert.equal(rendered.imageFailedCount, 0);
    assert.equal(drawnImages.length, 1);
    assert.deepEqual(revoked, ['blob:share-card-image']);
});

test('assistant answers expose a card action and a copy/download preview dialog', () => {
    assert.match(appSource, /data-share-answer-card/);
    assert.match(appSource, /renderShareCardActionButton\(copyEnabled\)/);
    assert.match(appSource, /closest\?\.\('\.message\.assistant\[data-copy-text\]'\)/);
    assert.match(appSource, /new window\.ClipboardItem\(\{ 'image\/png': blob \}\)/);
    assert.match(appSource, /shareCardLoading\.hidden = ready \|\| !shareCardState\.busy/);
    assert.match(indexSource, /id="share-card-dialog"[\s\S]*data-share-card-copy[\s\S]*data-share-card-download/);
    assert.match(indexSource, /src="\/static\/js\/share-card\.js\?v=3"/);
    assert.match(styleSource, /body\.share-card-open\s*\{\s*overflow:\s*hidden/);
});
