const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('web/static/js/app.js', 'utf8');
const transport = source.slice(source.indexOf('function apiUsesCrossOriginTransport()'), source.indexOf('function confirmAction('));

function harness({ apiBase = 'https://api.example.test', token = 'test-session-alice' } = {}) {
    const requests = [];
    const context = vm.createContext({
        API_BASE: apiBase, currentAccountToken: token, currentUserId: 'alice',
        window: { location: { href: 'https://localhost/index.html', origin: 'https://localhost' } },
        URL, AbortController, setTimeout, clearTimeout,
        t: () => 'Request timed out',
        fetch: async (url, options) => {
            requests.push({ url, options });
            // Connect accepts the account session only in the request header.
            const connect = new URL(url, 'https://localhost').pathname.startsWith('/api/connect/v1/');
            const authorized = !connect || options.headers['X-Account-Session'] === context.currentAccountToken && !!context.currentAccountToken;
            return { ok: authorized, status: authorized ? 200 : 401, json: async () => authorized ? { ok: true } : { error: 'valid account session required' } };
        },
    });
    vm.runInContext(transport, context);
    return { context, requests };
}

test('Android Connect requests authenticate through headers without session tokens in URLs', async () => {
    const { context, requests } = harness();
    for (const [method, path, body] of [
        ['GET', '/catalog'], ['GET', '/connections'], ['GET', '/roles'],
        ['POST', '/connections', { kind: 'weixin', name: 'Personal' }],
        ['POST', '/connections/c1/check', {}],
        ['PUT', '/connections/c1/role', { role_id: 'mentor' }],
        ['PUT', '/connections/c1/note', { note: 'Personal' }],
        ['DELETE', '/connections/c1'],
    ]) {
        assert.equal((await context.apiCall(method, `/api/connect/v1${path}`, body, { timeoutMs: 500 })).ok, true);
        const { url, options } = requests.at(-1);
        assert.equal(url, `https://api.example.test/api/connect/v1${path}`);
        assert.equal(options.headers['X-Account-Session'], 'test-session-alice');
        assert.equal(options.headers['X-User-ID'], 'alice');
        assert.equal(options.method, method);
        assert.ok(options.signal instanceof AbortSignal);
        assert.equal(options.body, body ? JSON.stringify(body) : undefined);
        assert.equal(options.headers['Content-Type'], body ? 'application/json' : undefined);
    }
});

test('Connect transport uses the current account after switching accounts', async () => {
    const { context, requests } = harness();
    await context.apiCall('GET', '/api/connect/v1/connections');
    context.currentAccountToken = 'test-session-bob';
    context.currentUserId = 'bob';
    await context.apiCall('GET', '/api/connect/v1/connections');
    assert.equal(requests[0].options.headers['X-Account-Session'], 'test-session-alice');
    assert.equal(requests[1].options.headers['X-Account-Session'], 'test-session-bob');
    assert.equal(requests[1].options.headers['X-User-ID'], 'bob');
});

test('Connect without an account session still reports 401', async () => {
    const { context, requests } = harness({ token: '' });
    await assert.rejects(context.apiCall('GET', '/api/connect/v1/catalog'), error => error.httpStatus === 401);
    assert.equal(requests[0].options.headers['X-Account-Session'], undefined);
    assert.equal(new URL(requests[0].url).search, '');
});

test('same-origin Connect requests retain header authentication', async () => {
    const { context, requests } = harness({ apiBase: '' });
    await context.apiCall('GET', '/api/connect/v1/catalog');
    assert.equal(requests[0].url, '/api/connect/v1/catalog');
    assert.equal(requests[0].options.headers['X-Account-Session'], 'test-session-alice');
});

test('Connect header transport recognizes the API boundary and preserves existing query parameters', async () => {
    const { context, requests } = harness();
    for (const path of ['/api/connect/v1', '/api/connect/v1?limit=1', '/api/connect/v1/connections?limit=1']) {
        await context.apiCall('GET', path);
        assert.equal(requests.at(-1).url, `https://api.example.test${path}`);
        assert.equal(requests.at(-1).options.headers['X-Account-Session'], 'test-session-alice');
    }
});

test('other cross-origin APIs and direct resource URLs retain their existing authentication', async () => {
    const { context, requests } = harness();
    for (const path of ['/api/conversations?limit=10', '/api/connect/v10/catalog']) {
        await context.apiCall('GET', path);
        const request = requests.at(-1);
        const url = new URL(request.url);
        assert.equal(url.searchParams.get('account_session'), 'test-session-alice');
        assert.equal(url.searchParams.get('user_id'), 'alice');
        assert.equal(request.options.headers['X-Account-Session'], undefined);
    }
    const resource = new URL(context.authenticatedApiUrl('/api/files/image?download=1'));
    assert.equal(resource.searchParams.get('download'), '1');
    assert.equal(resource.searchParams.get('account_session'), 'test-session-alice');
});
