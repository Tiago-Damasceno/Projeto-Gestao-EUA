const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness({ initialSession = null, configStatus = 200, config = { url: 'https://example.supabase.co', publicKey: 'sb_publishable_test' } } = {}) {
  let session = initialSession;
  let callback;
  const calls = [];
  const events = [];
  const removed = [];
  const auth = {
    onAuthStateChange(fn) { callback = fn; },
    async getSession() { return { data: { session }, error: null }; },
    async signInWithPassword(credentials) {
      calls.push({ credentials });
      session = { access_token: 'real-password-token', user: { id: 'user-a' } };
      callback('SIGNED_IN', session);
      return { data: { session }, error: null };
    },
    async signInWithOAuth(options) { calls.push({ oauth: options }); return { error: null }; },
    async signOut(options) { calls.push({ signOut: options }); session = null; callback('SIGNED_OUT', null); return { error: null }; }
  };
  const context = vm.createContext({
    URL, setTimeout, console,
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    localStorage: { removeItem(key) { removed.push(key); } },
    sessionStorage: { removeItem(key) { removed.push(key); } },
    async fetch(url, options) {
      calls.push({ url, options });
      if (url === '/auth/config') return { ok: configStatus === 200, json: async () => config };
      return { ok: true, headers: { get: () => 'application/json' }, json: async () => ({ data: [] }) };
    },
    window: {
      location: { origin: 'http://localhost:5000' },
      dispatchEvent(event) { events.push(event); },
      supabase: { createClient(url, key, options) { calls.push({ create: { url, key, options } }); return { auth }; } }
    }
  });
  for (const file of ['api.js', 'auth.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../public/js', file), 'utf8'), context);
  }
  return { context, calls, events, removed, auth,
    change(event, next) { session = next; callback(event, session); } };
}

test('OAuth return/restored session is loaded; old fake-token storage is removed', async () => {
  const h = harness({ initialSession: { access_token: 'oauth-token', user: { id: 'user-a' } } });
  const session = await h.context.window.authSession.initialize();
  assert.equal(session.access_token, 'oauth-token');
  assert.equal(h.context.window.apiClient.getToken(), 'oauth-token');
  assert.deepEqual(h.removed, ['23e_token', '23e_token']);
  const options = h.calls.find(x => x.create).create.options.auth;
  assert.equal(options.autoRefreshToken, true);
  assert.equal(options.detectSessionInUrl, true);
});

test('API reads the refreshed session and includes selected company', async () => {
  const h = harness();
  await h.context.window.authSession.initialize();
  h.change('TOKEN_REFRESHED', { access_token: 'fresh-token', user: { id: 'user-a' } });
  h.context.window.apiClient.setCompany('company-b');
  await h.context.window.apiClient.getLeads('new');
  const call = h.calls.find(x => String(x.url).includes('/leads'));
  assert.equal(call.options.headers.Authorization, 'Bearer fresh-token');
  const url = new URL(call.url);
  assert.equal(url.searchParams.get('company_id'), 'company-b');
  assert.equal(url.searchParams.get('stage'), 'new');
});

test('password login uses Supabase; signout clears session and company', async () => {
  const h = harness();
  await h.context.window.authSession.initialize();
  await h.context.window.authSession.signIn('test@example.com', 'test-password');
  assert.equal(h.context.window.apiClient.getToken(), 'real-password-token');
  assert.equal(h.calls.find(x => x.credentials).credentials.email, 'test@example.com');
  h.context.window.apiClient.setCompany('company-b');
  await h.context.window.authSession.signOut();
  assert.equal(await h.context.window.authSession.getToken(), null);
  assert.equal(h.context.window.apiClient.companyId, null);
  assert.equal(h.calls.find(x => x.signOut).signOut.scope, 'local');
});

test('missing config fails without creating a fake session', async () => {
  const h = harness({ configStatus: 503, config: { error: { message: 'Configuration unavailable' } } });
  await assert.rejects(h.context.window.authSession.initialize(), /Configuration unavailable/);
  await assert.rejects(h.context.window.authSession.signIn('test@example.com', 'password'), /Login indisponível/);
  assert.equal(h.context.window.apiClient.getToken(), null);
  assert.equal(h.calls.some(x => x.credentials), false);
});

test('Google redirect uses the application root; provider errors are surfaced', async () => {
  const h = harness();
  await h.context.window.authSession.initialize();
  await h.context.window.authSession.signInWithGoogle();
  assert.equal(h.calls.find(x => x.oauth).oauth.options.redirectTo, 'http://localhost:5000/');
  h.auth.signInWithOAuth = async () => ({ error: new Error('Provider disabled') });
  await assert.rejects(h.context.window.authSession.signInWithGoogle(), /Provider disabled/);
});

test('inline page script parses after auth integration', () => {
  const html = fs.readFileSync(path.join(__dirname, '../public/index.html'), 'utf8');
  for (const match of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
  assert.equal(html.includes('dummyToken'), false);
});

test('lead card helpers format price and stage age and escape customer text', () => {
  const html = fs.readFileSync(path.join(__dirname, '../public/index.html'), 'utf8');
  const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];
  const context = vm.createContext({
    console,
    window: {},
    document: { addEventListener() {} }
  });
  vm.runInContext(inline, context);
  assert.equal(vm.runInContext("formatLeadPrice('1250')", context), '$1,250.00');
  assert.equal(vm.runInContext('formatLeadPrice(null)', context), '$0,00');
  assert.equal(vm.runInContext("escapeHtml('<b>Lead</b>')", context), '&lt;b&gt;Lead&lt;/b&gt;');
  const oneDayAgo = new Date(Date.now() - 36 * 60 * 60 * 1000).toISOString();
  context.oneDayAgo = oneDayAgo;
  assert.equal(vm.runInContext('formatDaysInStage(oneDayAgo)', context), '1 dia nesta etapa');
  assert.equal(html.includes('lead-chat-button'), true);
  assert.equal(html.includes('lead-edit-button'), true);
  assert.equal(html.includes('>Editar</button>'), false);
  assert.equal(html.includes('>💬 Chat</button>'), false);
  assert.equal(html.includes('openEditLead'), true);
  assert.equal(html.includes('Valor: ${formatLeadPrice(l.estimated_value)}'), true);
});


test('page restores OAuth session into dashboard and logout returns to login', async () => {
  const h = harness({ initialSession: { access_token: 'oauth-token', user: { id: 'master' } } });
  const elements = new Map();
  let startup;
  const listeners = {};
  h.context.document = {
    addEventListener(type, callback) { if (type === 'DOMContentLoaded') startup = callback; },
    getElementById(id) {
      if (!elements.has(id)) {
        const classes = new Set(['oculto']);
        elements.set(id, {
          classList: { add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x) },
          addEventListener() {}, replaceChildren() {}, add() {}, innerText: '', value: ''
        });
      }
      return elements.get(id);
    }
  };
  h.context.Option = class {};
  h.context.window.addEventListener = (name, callback) => { listeners[name] = callback; };
  h.context.window.dispatchEvent = event => { listeners[event.type]?.(event); };
  const originalFetch = h.context.fetch;
  h.context.fetch = async (url, options) => {
    if (url === '/auth/config') return originalFetch(url, options);
    const data = String(url).endsWith('/me')
      ? { id: 'master', email: 'test@example.com', role: 'platform_admin', onboarding_completed: true,
          company: { name: '23e growth' } }
      : String(url).endsWith('/companies') ? [] : { new_leads: 3 };
    return { ok: true, headers: { get: () => 'application/json' }, json: async () => ({ data }) };
  };
  const html = fs.readFileSync(path.join(__dirname, '../public/index.html'), 'utf8');
  const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];
  vm.runInContext(inline, h.context);
  await startup();
  assert.equal(elements.get('screen-main').classList.contains('oculto'), false);
  assert.equal(elements.get('screen-auth').classList.contains('oculto'), true);
  assert.equal(elements.get('header-user-role').innerText, 'Super admin (23e growth)');
  await vm.runInContext('logout()', h.context);
  assert.equal(elements.get('screen-main').classList.contains('oculto'), true);
  assert.equal(elements.get('screen-auth').classList.contains('oculto'), false);
  assert.equal(await h.context.window.authSession.getToken(), null);
});
