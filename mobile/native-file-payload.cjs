'use strict';

const DEFAULT_MAX_BYTES = 64 * 1024 * 1024;
const BASE64_CHUNK_BYTES = 24 * 1024;

function arrayBufferToBase64(buffer, encode = globalThis.btoa) {
  if (typeof encode !== 'function') throw new Error('Base64 encoding is unavailable.');
  const bytes = new Uint8Array(buffer);
  const encoded = [];
  for (let offset = 0; offset < bytes.length; offset += BASE64_CHUNK_BYTES) {
    const chunk = bytes.subarray(offset, Math.min(bytes.length, offset + BASE64_CHUNK_BYTES));
    let binary = '';
    for (let index = 0; index < chunk.length; index += 1) {
      binary += String.fromCharCode(chunk[index]);
    }
    encoded.push(encode(binary));
  }
  return encoded.join('');
}

async function blobToNativeFilePayload(blob, filename, options = {}) {
  const maxBytes = Number(options.maxBytes || DEFAULT_MAX_BYTES);
  if (!blob || typeof blob.arrayBuffer !== 'function') {
    throw new TypeError('A Blob is required.');
  }
  if (!Number.isFinite(blob.size) || blob.size < 0 || blob.size > maxBytes) {
    const error = new Error(`File exceeds the ${maxBytes}-byte native transfer limit.`);
    error.code = 'NATIVE_FILE_TOO_LARGE';
    throw error;
  }
  return {
    data: arrayBufferToBase64(await blob.arrayBuffer(), options.encode),
    filename: String(filename || 'download'),
    mimeType: String(blob.type || 'application/octet-stream'),
  };
}

module.exports = {
  DEFAULT_MAX_BYTES,
  arrayBufferToBase64,
  blobToNativeFilePayload,
};
