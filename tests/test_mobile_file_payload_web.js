'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
    arrayBufferToBase64,
    blobToNativeFilePayload,
} = require('../mobile/native-file-payload.cjs');

test('native file payload preserves filename, MIME type, and base64 bytes', async () => {
    const bytes = Uint8Array.from({ length: (24 * 1024) + 5 }, (_, index) => index % 251);
    const blob = new Blob([bytes], { type: 'image/png' });

    const payload = await blobToNativeFilePayload(blob, '回答卡片.png');

    assert.equal(payload.filename, '回答卡片.png');
    assert.equal(payload.mimeType, 'image/png');
    assert.equal(payload.data, Buffer.from(bytes).toString('base64'));
    assert.equal(arrayBufferToBase64(new Uint8Array([0, 1, 2, 253, 254, 255]).buffer), 'AAEC/f7/');
});

test('native file payload rejects missing and oversized Blobs before bridge transfer', async () => {
    await assert.rejects(
        blobToNativeFilePayload(null, 'missing.bin'),
        TypeError,
    );
    await assert.rejects(
        blobToNativeFilePayload(new Blob(['123']), 'large.bin', { maxBytes: 2 }),
        (error) => error.code === 'NATIVE_FILE_TOO_LARGE',
    );
});
