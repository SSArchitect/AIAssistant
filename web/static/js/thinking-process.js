(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.ThinkingProcess = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    function createState() {
        let phase = 'thinking';
        let expanded = true;
        const rounds = new Map();
        return {
            get expanded() { return expanded; },
            get live() { return phase === 'thinking'; },
            setExpanded(value) { expanded = Boolean(value); },
            startAnswer() {
                if (phase === 'thinking') expanded = false;
                phase = 'answer';
            },
            resume() { phase = 'thinking'; },
            finish() { phase = 'finished'; },
            appendReasoning(text, meta = {}) {
                if (!meta.model_event_id || !text) return;
                const key = meta.model_event_id;
                const previous = rounds.get(key);
                rounds.set(key, {
                    id: `live-reasoning-${key}`, type: 'model.reasoning', status: 'running',
                    payload: { model_event_id: key, round: meta.round, text: (previous?.payload.text || '') + text },
                });
            },
            reasoningEvents() { return [...rounds.values()]; },
        };
    }

    function mergeTimeline(events = [], liveReasoning = [], legacyReasoning = '') {
        const timeline = [...events];
        const persisted = new Set(events.filter(event => event.type === 'model.reasoning')
            .map(event => event.payload?.model_event_id));
        for (const reasoning of liveReasoning) {
            const anchor = reasoning.payload?.model_event_id;
            if (persisted.has(anchor)) continue;
            const index = timeline.findIndex(event => event.id === anchor);
            if (index >= 0) timeline.splice(index + 1, 0, reasoning);
            else timeline.push(reasoning);
        }
        if (!timeline.some(event => event.type === 'model.reasoning') && String(legacyReasoning || '').trim()) {
            const reasoning = { id: 'legacy-reasoning', type: 'model.reasoning', status: 'completed',
                payload: { text: String(legacyReasoning).trim() } };
            const end = timeline.findIndex(event => /^run\.(completed|partial|failed|cancelled|interrupted)$/.test(event.type));
            timeline.splice(end < 0 ? timeline.length : end, 0, reasoning);
        }
        const toolResults = new Map(timeline.filter(event => event.step_id && ['tool.completed', 'tool.failed'].includes(event.type))
            .map(event => [event.step_id, event.status]));
        return timeline.map(event => event.type === 'tool.started' && toolResults.has(event.step_id)
            ? { ...event, status: toolResults.get(event.step_id) } : event);
    }

    function toolName(event = {}) {
        return event.payload?.name || event.payload?.tool_name
            || String(event.title || '').match(/^Tool (.+?)(?: completed| failed)?$/)?.[1] || '';
    }

    function summarize(events = []) {
        events = Array.isArray(events) ? events : [];
        const starts = events.filter(event => event.type === 'model.started');
        const rounds = starts.length ? starts : events.filter(event => event.type === 'model.reasoning');
        return {
            rounds: new Set(rounds.map(event => event.payload?.round ?? event.payload?.model_event_id ?? event.id)).size,
            toolCalls: new Set(events.filter(event => event.type === 'tool.started').map(event => event.step_id || event.id)).size,
        };
    }

    return { createState, mergeTimeline, toolName, summarize };
});
