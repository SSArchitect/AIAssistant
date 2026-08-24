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
const styleSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/css/style.css'),
    'utf8',
);

function extractFunctionDeclaration(name) {
    const asyncMarker = `async function ${name}(`;
    const syncMarker = `function ${name}(`;
    const asyncStart = appSource.indexOf(asyncMarker);
    const marker = asyncStart >= 0 ? asyncMarker : syncMarker;
    const start = asyncStart >= 0 ? asyncStart : appSource.indexOf(syncMarker);
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

test('refreshing Pulse keeps the previous feed until the completed payload arrives', () => {
    const source = extractFunctionDeclaration('setPulseResponse');
    const result = vm.runInNewContext(`
        let pulse = {
            date: '2026-07-27',
            generated_at: 'old-time',
            items: [{ id: 'old-item' }],
            modules: [{ key: 'memory', title: 'Old module' }],
            recommended_count: 1,
        };
        ${source}
        setPulseResponse({
            date: '2026-07-27',
            generated_at: '',
            refreshing: true,
            items: [],
            modules: [],
            recommended_count: 0,
        });
        const whileRefreshing = JSON.parse(JSON.stringify(pulse));
        setPulseResponse({
            date: '2026-07-27',
            generated_at: 'new-time',
            refreshing: false,
            items: [{ id: 'new-item' }],
            modules: [{ key: 'topic_hot', title: 'New module' }],
            recommended_count: 1,
        });
        JSON.stringify({ whileRefreshing, completed: pulse });
    `);
    const state = JSON.parse(result);

    assert.equal(state.whileRefreshing.items[0].id, 'old-item');
    assert.equal(state.whileRefreshing.modules[0].title, 'Old module');
    assert.equal(state.whileRefreshing.generated_at, 'old-time');
    assert.equal(state.completed.items[0].id, 'new-item');
    assert.equal(state.completed.modules[0].title, 'New module');
});

test('Pulse empty state does not concatenate verbose module failure summaries', () => {
    const source = extractFunctionDeclaration('pulseFallbackModuleDetail');
    const result = vm.runInNewContext(`
        const pulse = {
            modules: [
                { summary: '外网搜索结果以弱证据为主，这是一段很长的模块说明。' },
                { summary: '检索没有拿到可核验来源，这是另一段很长的模块说明。' },
            ],
        };
        ${source}
        pulseFallbackModuleDetail();
    `, {
        t: (key) => key === 'pulse.emptyUnavailableDetail'
            ? '本轮没有找到由至少两个近期独立来源共同证实的具体事件，因此不展示卡片。'
            : key,
    });

    assert.equal(result, '本轮没有找到由至少两个近期独立来源共同证实的具体事件，因此不展示卡片。');
    assert.doesNotMatch(result, /弱证据为主|另一段很长/);
});

test('Pulse empty state offers a direct news-search recovery action', () => {
    const source = extractFunctionDeclaration('renderPulseEmptyState');
    const html = vm.runInNewContext(`
        ${source}
        renderPulseEmptyState('No valid clusters', 'Search is unavailable.');
    `, {
        escapeHtml: String,
        t: (key) => ({
            'pulse.searchNews': "Search today's news",
            'pulse.searchNewsHint': 'Use the current topics in chat.',
        })[key] || key,
    });

    assert.match(html, /data-pulse-search-news/);
    assert.match(html, /Search today&#39;s news|Search today's news/);
    assert.match(html, /Use the current topics in chat\./);
});

test('Pulse news fallback prompt respects the selected topic and asks for sourced events', () => {
    const source = extractFunctionDeclaration('pulseNewsFallbackPrompt');
    const prompt = vm.runInNewContext(`
        const pulse = {
            date: '2026-08-21',
            topics: [
                { id: 'ai', name: 'AI', keywords: ['Agent', 'RAG'], enabled: true },
                { id: 'travel', name: 'Travel', keywords: ['Tokyo'], enabled: true },
            ],
        };
        const selectedPulseTopicId = 'ai';
        const currentLanguage = 'zh';
        ${source}
        pulseNewsFallbackPrompt();
    `, {
        normalizePulseKeywordList: (values) => values,
        todoTodayKey: () => 'fallback-date',
    });

    assert.match(prompt, /2026-08-21/);
    assert.match(prompt, /AI（Agent、RAG）/);
    assert.doesNotMatch(prompt, /Travel|Tokyo/);
    assert.match(prompt, /来源链接与发布日期/);
});

test('Pulse refresh copy exposes the active backend stage and elapsed time', () => {
    const source = extractFunctionDeclaration('pulseRefreshStatusText');
    const label = vm.runInNewContext(`
        const pulse = { refresh_stage: 'searching', refresh_elapsed_seconds: 17 };
        ${source}
        pulseRefreshStatusText();
    `, {
        t: (key, values = {}) => key === 'pulse.refreshSearching'
            ? 'Searching sources'
            : `${values.status} · ${values.seconds}s`,
    });

    assert.equal(label, 'Searching sources · 17s');
});

test('a stale Pulse load cannot overwrite a newer refresh response', async () => {
    const source = [
        extractFunctionDeclaration('invalidatePulseRequests'),
        extractFunctionDeclaration('beginPulseRequest'),
        extractFunctionDeclaration('pulseRequestIsCurrent'),
        extractFunctionDeclaration('setPulseResponse'),
        extractFunctionDeclaration('loadPulse'),
        extractFunctionDeclaration('refreshPulse'),
    ].join('\n');
    const result = await vm.runInNewContext(`
        (async () => {
            let currentUserId = 'user-a';
            let pulse = {
                user_id: 'user-a',
                date: '2026-07-27',
                generated_at: 'old-time',
                items: [{ id: 'old-item' }],
                modules: [{ key: 'memory', title: 'Old module' }],
            };
            let pulseError = '';
            let pulseErrorType = 'load';
            let pulseRefreshPollTimer = null;
            let pulseRefreshPollAttempts = 0;
            let pulseRequestEpoch = 0;
            let pulseRequestSequence = 0;
            let pulseLatestRequestSequence = 0;
            let pulseRefreshRequestPending = false;
            let renderCount = 0;
            const syncCalls = [];
            const pending = {};
            const apiCall = (method) => new Promise((resolve) => {
                pending[method] = resolve;
            });
            const renderPulse = () => { renderCount += 1; };
            const refreshWelcomeIfEmpty = () => {};
            const syncPulseRefreshPolling = (reset) => { syncCalls.push(reset); };
            ${source}

            const staleLoad = loadPulse();
            const refresh = refreshPulse();
            pending.POST({
                user_id: 'user-a',
                date: '2026-07-27',
                generated_at: '',
                refreshing: true,
                items: [],
                modules: [],
            });
            await refresh;
            pending.GET({
                user_id: 'user-a',
                date: '2026-07-27',
                generated_at: 'old-time',
                refreshing: false,
                items: [{ id: 'stale-item' }],
                modules: [],
            });
            await staleLoad;

            return JSON.stringify({
                pulse,
                pulseRefreshRequestPending,
                renderCount,
                syncCalls,
            });
        })();
    `);
    const state = JSON.parse(result);

    assert.equal(state.pulse.refreshing, true);
    assert.equal(state.pulse.items[0].id, 'old-item');
    assert.equal(state.pulseRefreshRequestPending, false);
    assert.equal(state.renderCount, 1);
    assert.deepEqual(state.syncCalls, [true]);
});

test('Super Chat welcome actions prefer Pulse questions, then recent work, then safe fallbacks', () => {
    const source = extractFunctionDeclaration('superChatWelcomeActions');
    const actions = vm.runInNewContext(`
        const SUPER_CHAT_WELCOME_ACTION_LIMIT = 4;
        const SUPER_CHAT_AGENT_ID = 'super_chat';
        const currentConversationId = '';
        const currentLanguage = 'zh';
        const pulse = {
            items: [
                { id: 'pulse-1', detail: { suggested_questions: ['Pulse question one?'] } },
                { id: 'pulse-2', detail: { suggested_questions: ['Pulse question two?'] } },
            ],
        };
        const conversations = [
            { id: 'recent-1', agent_id: 'super_chat', title: 'Recent project' },
            { id: 'image-1', agent_id: 'image_generation_v1', title: 'Image task' },
        ];
        ${source}
        superChatWelcomeActions();
    `, {
        buildPulseChatPrompt: (item, question) => `pulse:${item.id}:${question}`,
        conversationAgentId: (conversation) => conversation.agent_id,
        truncateText: (value) => value,
        t: (key) => key,
    });

    assert.equal(actions.length, 4);
    assert.deepEqual(Array.from(actions, (action) => action.source), ['pulse', 'pulse', 'conversation', 'fallback']);
    assert.equal(actions[0].label, 'Pulse question one?');
    assert.equal(actions[0].query, 'pulse:pulse-1:Pulse question one?');
    assert.match(actions[2].label, /Recent project/);
    assert.equal(actions[3].label, 'welcome.todayPulse');
    assert.ok(actions.every((action) => action.autoSend === false));
});

test('Super Chat welcome always has four fallback questions when Pulse is empty', () => {
    const source = extractFunctionDeclaration('superChatWelcomeActions');
    const actions = vm.runInNewContext(`
        const SUPER_CHAT_WELCOME_ACTION_LIMIT = 4;
        const SUPER_CHAT_AGENT_ID = 'super_chat';
        const currentConversationId = '';
        const currentLanguage = 'en';
        const pulse = { items: [] };
        const conversations = [];
        ${source}
        superChatWelcomeActions();
    `, {
        buildPulseChatPrompt: () => '',
        conversationAgentId: () => 'super_chat',
        truncateText: (value) => value,
        t: (key) => key,
    });

    assert.equal(actions.length, 4);
    assert.ok(actions.every((action) => action.source === 'fallback'));
    assert.deepEqual(Array.from(actions, (action) => action.label), [
        'welcome.todayPulse',
        'welcome.unfinished',
        'welcome.priorities',
        'welcome.explore',
    ]);
});

test('invalidating Pulse requests clears polling and rejects the old account token', () => {
    const source = [
        extractFunctionDeclaration('invalidatePulseRequests'),
        extractFunctionDeclaration('beginPulseRequest'),
        extractFunctionDeclaration('pulseRequestIsCurrent'),
    ].join('\n');
    const result = vm.runInNewContext(`
        let currentUserId = 'user-a';
        let pulseRefreshPollTimer = 42;
        let pulseRefreshPollAttempts = 9;
        let pulseRequestEpoch = 0;
        let pulseRequestSequence = 0;
        let pulseLatestRequestSequence = 0;
        let pulseRefreshRequestPending = true;
        let clearedTimer = null;
        const clearTimeout = (timer) => { clearedTimer = timer; };
        ${source}
        const request = beginPulseRequest();
        currentUserId = 'user-b';
        invalidatePulseRequests();
        JSON.stringify({
            current: pulseRequestIsCurrent(request),
            pulseRefreshPollTimer,
            pulseRefreshPollAttempts,
            pulseRefreshRequestPending,
            clearedTimer,
        });
    `);
    const state = JSON.parse(result);

    assert.equal(state.current, false);
    assert.equal(state.pulseRefreshPollTimer, null);
    assert.equal(state.pulseRefreshPollAttempts, 0);
    assert.equal(state.pulseRefreshRequestPending, false);
    assert.equal(state.clearedTimer, 42);
    assert.match(extractFunctionDeclaration('switchAccount'), /invalidatePulseRequests\(\)/);
});

test('Pulse refresh timeout keeps server state and continues with slow polling', () => {
    const source = extractFunctionDeclaration('syncPulseRefreshPolling');
    const result = vm.runInNewContext(`
        let pulse = { refreshing: true, items: [{ id: 'kept-item' }] };
        let pulseRefreshPollTimer = null;
        let pulseRefreshPollAttempts = 24;
        let pulseError = '';
        let pulseErrorType = '';
        let renderCount = 0;
        let scheduledDelay = 0;
        const PULSE_REFRESH_FAST_MAX_POLLS = 24;
        const PULSE_REFRESH_POLL_MS = 5000;
        const PULSE_REFRESH_SLOW_POLL_MS = 30000;
        const t = () => 'refresh timed out';
        const renderPulse = () => { renderCount += 1; };
        const setTimeout = (_callback, delay) => {
            scheduledDelay = delay;
            return 1;
        };
        ${source}
        syncPulseRefreshPolling(false);
        JSON.stringify({ pulse, pulseError, pulseErrorType, renderCount, scheduledDelay });
    `);
    const state = JSON.parse(result);

    assert.equal(state.pulse.refreshing, true);
    assert.equal(state.pulse.items[0].id, 'kept-item');
    assert.equal(state.pulseError, 'refresh timed out');
    assert.equal(state.pulseErrorType, 'refresh_timeout');
    assert.equal(state.renderCount, 1);
    assert.equal(state.scheduledDelay, 30000);
});

test('Pulse feed renders generated module titles and summaries', () => {
    const source = [
        extractFunctionDeclaration('pulseModuleSourceKey'),
        extractFunctionDeclaration('pulseModuleCopy'),
        extractFunctionDeclaration('pulseModuleClass'),
        extractFunctionDeclaration('renderPulseModules'),
    ].join('\n');
    const html = vm.runInNewContext(`
        ${source}
        renderPulseModules(
            [{ id: 'topic-card', source: 'topic', title: 'Card' }],
            [{ key: 'topic_hot', title: 'AI radar', summary: 'Today’s verified AI changes.' }],
        );
    `, {
        I18N: {
            en: { pulse: { modules: {
                topicHot: ['Topic', 'Topic detail'],
                memory: ['Memory', 'Memory detail'],
                interestHot: ['Interest', 'Interest detail'],
            } } },
        },
        currentLanguage: 'en',
        escapeAttr: String,
        escapeHtml: String,
        renderPulseCard: (item) => `<article>${item.title}</article>`,
        t: (key) => key,
    });

    assert.match(html, /AI radar/);
    assert.match(html, /Today’s verified AI changes\./);
    assert.match(html, /<article>Card<\/article>/);
});

test('Pulse cards expose source count and date instead of an internal rank', () => {
    const source = extractFunctionDeclaration('pulseCardEvidenceMeta');
    const label = vm.runInNewContext(`
        ${source}
        pulseCardEvidenceMeta({
            detail: {
                news_sources: [
                    { url: 'https://openai.com/news/a', published_at: '2026-07-26' },
                    { url: 'https://reuters.com/report/a', published_at: '2026-07-25' },
                ],
            },
        });
    `, {
        normalizePulseNewsSources: (sources) => sources,
        t: (_key, values) => `${values.count} independent sources`,
    });

    assert.equal(label, '2 independent sources · 2026-07-26');
});

test('Pulse source normalization keeps only absolute HTTP(S) URLs', () => {
    const source = [
        extractFunctionDeclaration('isSafePulseSourceUrl'),
        extractFunctionDeclaration('normalizePulseNewsSources'),
    ].join('\n');
    const result = vm.runInNewContext(`
        ${source}
        JSON.stringify(normalizePulseNewsSources([
            { title: 'Secure', url: 'https://example.com/a' },
            { title: 'Plain HTTP', link: 'http://example.org/b' },
            { title: 'Script', url: 'javascript:alert(1)' },
            { title: 'Relative', url: '/internal/path' },
            { title: 'Data', url: 'data:text/html,unsafe' },
            { title: 'Malformed', url: 'https://' },
            { title: 'Credentials', url: 'https://user:secret@example.net/private' },
            { title: 'Loopback', url: 'http://127.0.0.1/admin' },
            { title: 'Private', url: 'http://192.168.1.8/admin' },
        ]));
    `, {
        URL,
        hostFromUrl: (value) => new URL(value).hostname,
    });
    const sources = JSON.parse(result);

    assert.deepEqual(sources.map((source) => source.url), [
        'https://example.com/a',
        'http://example.org/b',
    ]);
});

test('Pulse post keeps one cluster summary, compact sources, and at most three questions', () => {
    const source = [
        extractFunctionDeclaration('pulseRecommendationNote'),
        extractFunctionDeclaration('renderPulseNewsSources'),
        extractFunctionDeclaration('renderPulseDetail'),
        extractFunctionDeclaration('renderPulsePostBody'),
        extractFunctionDeclaration('renderPulsePostFooter'),
    ].join('\n');
    const result = vm.runInNewContext(`
        ${source}
        const item = {
            id: 'pulse-1',
            summary: 'A concise summary.',
            recommendation_note: 'Generic recommendation.',
            related_clusters: [{ id: 'related-1', title: 'Related cluster must stay hidden.' }],
            detail: {
                recommendation_reason: 'Matches the AI topic you follow.',
                quick_context: 'Background copy must stay hidden.',
                key_points: ['Key point must stay hidden.'],
                signals: ['Signal must stay hidden.'],
                news_sources: [{
                    title: 'Primary source title',
                    url: 'https://example.com/news/1',
                    source: 'Provider label must stay hidden.',
                    published_at: '2026-07-26T08:00:00Z',
                    snippet: 'A long source snippet must stay hidden.',
                }],
                suggested_questions: ['Question one?', 'Question two?', 'Question three?', 'Question four?'],
            },
        };
        JSON.stringify({
            reason: pulseRecommendationNote(item),
            body: renderPulsePostBody(item),
            footer: renderPulsePostFooter(item),
        });
    `, {
        buildPulseChatPrompt: (_item, question) => `ask:${question}`,
        escapeAttr: String,
        escapeHtml: String,
        hostFromUrl: (value) => new URL(value).hostname,
        normalizePulseNewsSources: (...groups) => groups.flatMap((group) => Array.isArray(group) ? group : []),
        pulseEventLike: 'like',
        pulseEventUpvote: 'upvote',
        pulseEventDownvote: 'downvote',
        renderPulseFeedbackButton: () => '',
        renderPulseRelatedClusters: () => 'RELATED_CLUSTER_MARKUP',
        t: (key) => key,
    });
    const state = JSON.parse(result);
    const rendered = `${state.body}${state.footer}`;

    assert.equal(state.reason, 'Matches the AI topic you follow.');
    assert.doesNotMatch(rendered, /Matches the AI topic you follow/);
    assert.match(state.body, /pulse\.clusterContent/);
    assert.equal((state.body.match(/A concise summary\./g) || []).length, 1);
    assert.match(state.body, /Primary source title/);
    assert.match(state.body, /example\.com · 2026-07-26/);
    assert.match(state.body, /Question one\?/);
    assert.match(state.body, /Question two\?/);
    assert.match(state.body, /Question three\?/);
    assert.doesNotMatch(state.body, /Question four\?/);
    assert.equal((state.body.match(/data-pulse-chat=/g) || []).length, 3);
    assert.doesNotMatch(rendered, /Background copy must stay hidden/);
    assert.doesNotMatch(rendered, /Key point must stay hidden/);
    assert.doesNotMatch(rendered, /Signal must stay hidden/);
    assert.doesNotMatch(rendered, /A long source snippet must stay hidden/);
    assert.doesNotMatch(rendered, /Provider label must stay hidden/);
    assert.doesNotMatch(rendered, /Related cluster must stay hidden|RELATED_CLUSTER_MARKUP/);
    assert.doesNotMatch(rendered, /pulse\.(quickContext|keyPoints|signals|relatedClusters)/);
});

test('Pulse recommendation reasons are visually constrained to one line', () => {
    for (const selector of ['pulse-recommend-note', 'pulse-post-note']) {
        const rule = styleSource.match(new RegExp(`\\.${selector}\\s*\\{[^}]*\\}`, 's'))?.[0] || '';
        assert.match(rule, /white-space:\s*nowrap/);
        assert.match(rule, /overflow:\s*hidden/);
        assert.match(rule, /text-overflow:\s*ellipsis/);
    }
});

test('related Pulse clusters are only clickable when present in the current feed', () => {
    const source = [
        extractFunctionDeclaration('findPulseItem'),
        extractFunctionDeclaration('renderPulseRelatedClusters'),
    ].join('\n');
    const html = vm.runInNewContext(`
        let pulse = { items: [{ id: 'visible' }] };
        ${source}
        renderPulseRelatedClusters([
            { id: 'visible', title: 'Visible cluster' },
            { id: 'filtered-out', title: 'Unavailable cluster' },
        ]);
    `, {
        escapeAttr: String,
        escapeHtml: String,
        t: (key) => key,
    });

    assert.match(html, /data-pulse-open-post="visible"/);
    assert.match(html, /disabled aria-disabled="true"/);
    assert.match(html, /pulse\.relatedUnavailable/);
    assert.doesNotMatch(html, /data-pulse-open-post="filtered-out"/);
});
