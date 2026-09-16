(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.RunPager = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    function create({ fetchPage, onChange = () => {} }) {
        let generation = 0;
        let pending = null;
        let previous = [];
        let lastAttempt = null;
        const initial = () => ({ items: [], cursor: '', nextCursor: '', hasMore: false,
            page: 1, loading: false, error: '' });
        let state = initial();
        const snapshot = () => ({ ...state, items: state.items.slice() });
        const notify = () => onChange(snapshot());
        function reset() {
            generation += 1;
            pending = null;
            previous = [];
            lastAttempt = null;
            state = initial();
            notify();
        }
        function load(cursor, history) {
            if (pending) return pending;
            const token = generation;
            lastAttempt = { cursor, history };
            state.loading = true;
            state.error = '';
            notify();
            pending = (async () => {
                try {
                    const page = await Promise.resolve().then(() => fetchPage({ limit: 10, cursor }));
                    if (generation !== token) return;
                    if (page.has_more && (!page.next_cursor || page.next_cursor === cursor)) {
                        throw new Error('Invalid pagination cursor');
                    }
                    previous = history;
                    state = { ...state, items: page.runs || [], cursor,
                        nextCursor: page.next_cursor || '', hasMore: Boolean(page.has_more), page: history.length + 1 };
                } catch (error) {
                    if (generation === token) state.error = error.message || 'Unable to load runs';
                } finally {
                    if (generation === token) {
                        pending = null;
                        state.loading = false;
                        notify();
                    }
                }
            })();
            return pending;
        }
        return { snapshot, reset,
            refresh: () => state.error && lastAttempt
                ? load(lastAttempt.cursor, lastAttempt.history) : load(state.cursor, previous.slice()),
            next: () => state.hasMore ? load(state.nextCursor, [...previous, state.cursor]) : Promise.resolve(),
            previous: () => previous.length ? load(previous[previous.length - 1], previous.slice(0, -1)) : Promise.resolve(),
        };
    }
    return { create };
});
