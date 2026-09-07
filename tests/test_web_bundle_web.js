'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const source = path.join(__dirname, '../web');

async function checker() {
    return (await import('../scripts/verify_web_bundle.mjs')).verifyWebBundle;
}

function fixture(t) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'web-bundle-test-'));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    fs.cpSync(source, root, { recursive: true, filter: file => !file.includes(`${path.sep}generated${path.sep}`) });
    return root;
}

test('shipped entrypoint and actual browser module exports can render a message and a video', async () => {
    const result = (await checker())(source);
    assert.equal(result.smokeRender, true);
    assert.ok(result.methods.includes('VideoMedia.normalizeMarkdownLines'));
    assert.ok(result.methods.includes('ThinkingProcess.summarize'));
});

test('bundle check rejects the missing normalizer that broke the released OTA', async t => {
    const verify = await checker();
    const root = fixture(t);
    const modulePath = path.join(root, 'static/js/video-media.js');
    fs.writeFileSync(modulePath, fs.readFileSync(modulePath, 'utf8').replace('parseMarkdown, normalizeMarkdownLines, filename', 'parseMarkdown, filename'));
    assert.throws(() => verify(root), /VideoMedia\.normalizeMarkdownLines/);
});

test('bundle check rejects missing scripts and modules loaded after the chat entrypoint', async t => {
    const verify = await checker();
    const root = fixture(t);
    const index = path.join(root, 'index.html');
    const html = fs.readFileSync(index, 'utf8');
    const video = html.match(/<script src="[^\"]*video-media\.js[^\"]*"><\/script>/)[0];
    fs.writeFileSync(index, html.replace(video, '') + video);
    assert.throws(() => verify(root), /video-media\.js must load before app\.js/);
    fs.writeFileSync(index, html);
    fs.unlinkSync(path.join(root, 'static/js/video-media.js'));
    assert.throws(() => verify(root), /Missing script.*video-media/);
});
