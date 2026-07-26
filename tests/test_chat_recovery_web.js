'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const {
    createRunId,
    hasAssistantMessageForRun,
    isRecoverableStreamError,
} = require('../web/static/js/chat-recovery.js');

const appSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/js/app.js'),
    'utf8',
);

test('createRunId uses a stable client-generated run prefix', () => {
    const runId = createRunId({
        cryptoApi: { randomUUID: () => '12345678-1234-1234-1234-123456789abc' },
    });
    assert.equal(runId, 'run_12345678123412341234123456789abc');
});

test('createRunId has a non-crypto fallback for non-secure mobile pages', () => {
    const runId = createRunId({
        cryptoApi: null,
        now: () => 12345,
        random: () => 0.5,
    });
    assert.match(runId, /^run_[a-z0-9]+$/);
});

test('transport failures recover, including lifecycle AbortError', () => {
    const error = new Error('The operation was aborted');
    error.name = 'AbortError';
    error.streamTransportError = true;
    assert.equal(isRecoverableStreamError(error), true);
});

test('HTTP, server SSE, and explicit cancellation errors do not recover', () => {
    assert.equal(isRecoverableStreamError({
        streamTransportError: true,
        httpStatus: 502,
    }), false);
    assert.equal(isRecoverableStreamError({
        streamTransportError: true,
        streamEventError: true,
    }), false);
    assert.equal(isRecoverableStreamError({
        streamTransportError: true,
        userCancelled: true,
    }), false);
    assert.equal(isRecoverableStreamError({
        streamTransportError: true,
        errorType: 'cancelled',
    }), false);
});

test('persisted recovery matches the exact assistant run', () => {
    const messages = [
        { role: 'user', content: 'question' },
        { role: 'assistant', run_id: 'run_old', content: 'old answer' },
        { role: 'assistant', run_id: 'run_target', content: 'new answer' },
    ];
    assert.equal(hasAssistantMessageForRun(messages, 'run_target'), true);
    assert.equal(hasAssistantMessageForRun(messages, 'run_missing'), false);
    assert.equal(hasAssistantMessageForRun(messages, ''), false);
});

test('stream requests send the client run id and recover premature EOF', () => {
    assert.match(appSource, /run_id:\s*runId/);
    assert.match(
        appSource,
        /if\s*\(!finalResponse\)\s*\{\s*throw markChatStreamTransportError/,
    );
    assert.match(appSource, /recoverInterruptedChatStream\(\{/);
});

test('page lifecycle events trigger chat reconciliation', () => {
    assert.match(appSource, /addEventListener\('visibilitychange'/);
    assert.match(appSource, /addEventListener\('pageshow'/);
    assert.match(appSource, /addEventListener\('online', reconcileChatAfterPageResume\)/);
});
