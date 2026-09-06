(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.ConversationPager = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    function create({ fetchPage, onChange = () => {}, pageSize = 20 }) {
        let generation = 0;
        let pending = null;
        let removed = new Set();
        let state = { items: [], query: '', cursor: '', hasMore: true, total: 0, loading: false, error: '' };
        const snapshot = () => ({ ...state, items: state.items.slice() });
        const notify = () => onChange(snapshot());
        function reset(query = '') {
            generation += 1;
            pending = null;
            removed = new Set();
            state = { items: [], query: query.trim(), cursor: '', hasMore: true, total: 0, loading: false, error: '' };
            notify();
        }
        function load(refresh = false, options = {}) {
            if (pending) return pending;
            if (!refresh && !state.hasMore) return Promise.resolve();
            const token = generation;
            const query = state.query;
            const wanted = refresh ? Math.max(pageSize, state.items.length) : 0;
            let cursor = refresh ? '' : state.cursor;
            let items = refresh ? [] : state.items.slice();
            state.loading = true;
            state.error = '';
            notify();
            pending = (async () => {
                try {
                    let page;
                    do {
                        page = await Promise.resolve().then(() => fetchPage({ query, cursor, limit: pageSize }, options));
                        if (token !== generation) return;
                        if (page.has_more && (!page.next_cursor || page.next_cursor === cursor)) throw new Error('Invalid pagination cursor');
                        const seen = new Set(items.map(item => item.id));
                        items.push(...(page.conversations || []).filter(item => {
                            if (seen.has(item.id) || removed.has(item.id)) return false;
                            seen.add(item.id);
                            return true;
                        }));
                        cursor = page.next_cursor || '';
                    } while (refresh && page.has_more && items.length < wanted);
                    state.items = items.filter(item => !removed.has(item.id));
                    state.cursor = cursor;
                    state.hasMore = Boolean(page.has_more);
                    state.total = Number(page.total || 0);
                } catch (error) {
                    if (token === generation) state.error = error.message || 'Unable to load conversations';
                } finally {
                    if (token === generation) {
                        state.loading = false;
                        pending = null;
                        notify();
                    }
                }
            })();
            return pending;
        }
        function remove(id) {
            removed.add(id);
            if (state.items.some(item => item.id === id)) state.total = Math.max(0, state.total - 1);
            state.items = state.items.filter(item => item.id !== id);
            notify();
        }
        return { snapshot, reset, remove, loadMore: () => load(), refresh: options => load(true, options) };
    }
    return { create };
});
