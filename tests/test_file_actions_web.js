'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
    copyImageBlob,
    downloadBlob,
    hasNativeDownload,
} = require('../web/static/js/file-actions.js');

test('image copy prefers the Android native bridge when browser image clipboard APIs are absent', async () => {
    const blob = new Blob(['png'], { type: 'image/png' });
    const calls = [];
    const root = {
        AgentAssistantNative: {
            copyImage: async (payload) => {
                calls.push(payload);
                return { copied: true };
            },
        },
        navigator: {},
    };

    const result = await copyImageBlob(blob, 'answer.png', { root });

    assert.equal(result.method, 'native');
    assert.deepEqual(calls, [{ blob, filename: 'answer.png' }]);
});

test('image copy retains the browser ClipboardItem path outside the native app', async () => {
    const blob = new Blob(['png'], { type: 'image/png' });
    const writes = [];
    class FakeClipboardItem {
        constructor(items) {
            this.items = items;
        }
    }

    const result = await copyImageBlob(blob, 'answer.png', {
        root: {},
        clipboard: { write: async (items) => writes.push(items) },
        ClipboardItemCtor: FakeClipboardItem,
    });

    assert.equal(result.method, 'browser');
    assert.equal(writes.length, 1);
    assert.equal(writes[0][0].items['image/png'], blob);
});

test('image copy reports a stable unsupported error when neither path exists', async () => {
    await assert.rejects(
        copyImageBlob(new Blob(['png'], { type: 'image/png' }), 'answer.png', { root: {} }),
        (error) => error.code === 'IMAGE_CLIPBOARD_UNSUPPORTED',
    );
});

test('file download delegates the Blob to Android and propagates native failures', async () => {
    const blob = new Blob(['document'], { type: 'application/pdf' });
    const calls = [];
    const root = {
        AgentAssistantNative: {
            downloadBlob: async (payload) => {
                calls.push(payload);
                return { saved: true, uri: 'content://download/1' };
            },
        },
    };

    assert.equal(hasNativeDownload(root), true);
    const result = await downloadBlob(blob, 'report.pdf', { root });
    assert.equal(result.method, 'native');
    assert.deepEqual(calls, [{ blob, filename: 'report.pdf' }]);

    const failure = new Error('storage denied');
    await assert.rejects(
        downloadBlob(blob, 'report.pdf', {
            root: { AgentAssistantNative: { downloadBlob: async () => { throw failure; } } },
        }),
        failure,
    );
});

test('file download keeps the anchor fallback and revokes its object URL in browsers', async () => {
    const events = [];
    const link = {
        click: () => events.push('click'),
        remove: () => events.push('remove'),
    };
    const root = {
        URL: {
            createObjectURL: () => 'blob:download',
            revokeObjectURL: (url) => events.push(`revoke:${url}`),
        },
        setTimeout: (callback, delay) => {
            events.push(`delay:${delay}`);
            callback();
        },
    };
    const documentApi = {
        createElement: () => link,
        body: { appendChild: () => events.push('append') },
    };

    const result = await downloadBlob(new Blob(['text']), 'notes.txt', { root, documentApi });

    assert.equal(result.method, 'browser');
    assert.equal(link.href, 'blob:download');
    assert.equal(link.download, 'notes.txt');
    assert.deepEqual(events, [
        'append',
        'click',
        'remove',
        'delay:30000',
        'revoke:blob:download',
    ]);
});
