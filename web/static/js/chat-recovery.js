(function initializeChatRecovery(globalScope, factory) {
    const api = factory(globalScope);
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    }
    if (globalScope) {
        globalScope.ChatRecovery = api;
    }
}(typeof globalThis !== 'undefined' ? globalThis : this, function buildChatRecovery(globalScope) {
    'use strict';

    function createRunId(options = {}) {
        const cryptoApi = options.cryptoApi === undefined ? globalScope?.crypto : options.cryptoApi;
        const now = options.now || Date.now;
        const random = options.random || Math.random;
        if (typeof cryptoApi?.randomUUID === 'function') {
            return `run_${cryptoApi.randomUUID().replace(/-/g, '')}`;
        }
        if (typeof cryptoApi?.getRandomValues === 'function') {
            const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
            return `run_${Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')}`;
        }
        return `run_${now().toString(36)}${random().toString(36).slice(2)}`;
    }

    function isRecoverableStreamError(error) {
        return error?.streamTransportError === true
            && error?.streamEventError !== true
            && error?.httpStatus === undefined
            && error?.userCancelled !== true
            && error?.cancelled !== true
            && error?.errorType !== 'cancelled'
            && error?.message !== 'cancelled';
    }

    function hasAssistantMessageForRun(messages = [], runId = '') {
        return Boolean(runId && messages.some((message) => (
            message?.role === 'assistant' && message?.run_id === runId
        )));
    }

    return Object.freeze({
        createRunId,
        hasAssistantMessageForRun,
        isRecoverableStreamError,
    });
}));
