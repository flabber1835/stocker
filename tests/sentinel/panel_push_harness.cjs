// Run the rendered notification controller with browser/transport boundaries only.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const scenario = input.scenario;
const events = {};
const calls = [];
let phase = 'initial';
let polls = 0;
let subscription = scenario.startsWith('existing-') || scenario.startsWith('remove-');
const card = {hidden: true};
const status = {textContent: ''};
const enable = {disabled: false, hidden: false,
  addEventListener: (event, fn) => { events['enable-' + event] = fn; }};
const remove = {disabled: false, hidden: true,
  addEventListener: (event, fn) => { events['remove-' + event] = fn; }};
const sub = {
  endpoint: 'https://push.fixture.invalid/device',
  toJSON: () => ({endpoint: sub.endpoint, keys: {p256dh: 'fixture', auth: 'fixture'}}),
  unsubscribe: async () => { calls.push('unsubscribe'); subscription = false; },
};
const registration = {
  pushManager: {
    getSubscription: async () => {
      if (scenario === 'status-unavailable' && phase === 'initial') throw new Error('unreadable');
      return subscription ? sub : null;
    },
    subscribe: async options => {
      calls.push('subscribe');
      assert.equal(options.userVisibleOnly, true);
      assert.deepEqual(Array.from(options.applicationServerKey), [251, 255]);
      if (scenario === 'subscribe-failed') throw new Error('browser enrollment failed');
      subscription = true;
      return sub;
    },
  },
};
const context = {
  document: {getElementById: id => ({'push-card':card, 'push-enable':enable,
    'push-remove':remove, 'push-status':status})[id]},
  window: {isSecureContext: scenario !== 'unsupported-insecure',
    PushManager: {}, Notification: {}},
  navigator: {serviceWorker: {register: async (url, options) => {
    calls.push('register');
    assert.equal(url, '/service-worker.js');
    assert.equal(options.scope, '/');
    assert.equal(options.updateViaCache, 'none');
    return registration;
  }}},
  Notification: {requestPermission: async () => {
    calls.push('permission');
    return scenario === 'permission-denied' ? 'denied' : 'granted';
  }},
  Uint8Array, atob: value => Buffer.from(value, 'base64').toString('binary'),
  crypto: {randomUUID: () => 'single-test-id'},
  setTimeout: (callback, delay) => {
    assert.equal(delay, 2000);
    Promise.resolve().then(callback);
  },
  fetch: async (url, options) => {
    calls.push(url);
    assert.equal(options.cache, 'no-store');
    if (url === '/push/config') {
      assert.equal(options.method, undefined);
      return {ok: scenario !== 'config-failed', json: async () => ({applicationServerKey: '-_8'})};
    }
    assert.equal(options.credentials, 'same-origin');
    if (url === '/push/subscriptions') {
      assert.equal(options.method, 'POST');
      const body = JSON.parse(options.body);
      assert.equal(body.endpoint, sub.endpoint);
      assert.equal(body.test_id, 'single-test-id');
      if (scenario === 'enrollment-null-error') throw null;
      const terminal = scenario.split('-').at(-1).toUpperCase();
      return {ok: scenario !== 'save-failed', json: async () => ({
        delivery_status: ['ACCEPTED', 'FAILED', 'CANCELLED'].includes(terminal)
          && !scenario.includes('poll-') ? terminal : 'QUEUED',
        alert_id: scenario === 'queued-no-id' ? undefined : 'test /?#',
        sender_available: scenario !== 'sender-unavailable',
      })};
    }
    if (url === '/push/subscriptions/remove') {
      assert.equal(options.method, 'POST');
      assert.deepEqual(JSON.parse(options.body), {endpoint: sub.endpoint});
      if (scenario === 'remove-null-error') throw null;
      return {ok: scenario !== 'remove-refused'};
    }
    assert.equal(url, '/push/tests/test%20%2F%3F%23');
    assert.equal(options.method, undefined);
    polls++;
    if (scenario === 'poll-network-failed') throw new Error('network failed');
    return {ok: scenario !== 'poll-refused', json: async () => {
      if (scenario === 'poll-json-failed') throw new Error('bad JSON');
      const terminal = scenario.split('-').at(-1).toUpperCase();
      return {alert_id: 'test /?#', delivery_status: ['ACCEPTED', 'FAILED', 'CANCELLED'].includes(terminal)
          ? terminal : 'QUEUED', sender_available: scenario !== 'sender-unavailable'};
    }};
  },
};
if (scenario === 'unsupported-worker') delete context.navigator.serviceWorker;
if (scenario === 'unsupported-manager') delete context.window.PushManager;
if (scenario === 'unsupported-notification') delete context.window.Notification;
async function settled() { for (let i = 0; i < 32; i++) await Promise.resolve(); }
(async () => {
  const hash = crypto.createHash('sha256').update(input.script).digest('hex');
  vm.runInNewContext(input.script, context, {filename: 'sentinel-panel-push://' + hash});
  await settled();
  assert.equal(card.hidden, false);
  if (scenario.startsWith('unsupported-')) {
    assert.equal(calls.length, 0, 'unsupported browsers must not enroll or contact transport');
    assert.equal(enable.hidden, true);
    assert.equal(Object.keys(events).length, 0);
    assert(status.textContent.includes('unavailable'));
    return;
  }
  if (scenario === 'status-unavailable') {
    assert.equal(status.textContent, 'Notification status could not be read.');
    assert.equal(calls.length, 1);
    return;
  }
  assert.equal(enable.textContent, subscription ? 'Send test notification' : 'Enable notifications');
  assert.equal(remove.hidden, !subscription);
  assert(status.textContent.includes(subscription ? 'enabled' : 'off'));
  phase = 'click';
  if (scenario.startsWith('remove-')) {
    if (scenario === 'remove-absent') subscription = false;
    await events['remove-click']();
    assert.equal(remove.disabled, false, 'failure must not leave the device control disabled');
    if (scenario === 'remove-refused' || scenario === 'remove-null-error') {
      assert.equal(subscription, true, 'server refusal must preserve the browser subscription');
      assert(!calls.includes('unsubscribe'));
      assert(status.textContent.includes(scenario === 'remove-refused' ? 'could not be saved' : 'removal failed'));
    } else {
      assert.equal(subscription, false);
      assert.equal(remove.hidden, true);
      assert.equal(enable.textContent, 'Enable notifications');
      assert.equal(calls.filter(c => c === 'unsubscribe').length, scenario === 'remove-absent' ? 0 : 1);
      assert(status.textContent.includes('disabled'));
    }
    assert(!calls.includes('permission'));
    return;
  }
  await events['enable-click']();
  assert.equal(enable.disabled, false, 'failure must not leave enrollment disabled');
  const failures = {'permission-denied':'permission was not granted',
    'config-failed':'configuration is unavailable', 'subscribe-failed':'browser enrollment failed',
    'save-failed':'could not be saved', 'enrollment-null-error':'enrollment failed'};
  if (failures[scenario]) {
    assert(status.textContent.includes(failures[scenario]));
    assert.equal(polls, 0);
    if (scenario === 'permission-denied') assert(!calls.includes('/push/config'));
    return;
  }
  assert.equal(calls.filter(c => c === '/push/subscriptions').length, 1);
  assert.equal(calls.filter(c => c === 'subscribe').length, scenario.startsWith('existing-') ? 0 : 1);
  assert.equal(remove.hidden, false);
  assert.equal(enable.textContent, 'Send test notification');
  if (scenario.includes('accepted')) assert(status.textContent.includes('accepted by the push service'));
  else if (scenario.includes('cancelled')) assert(status.textContent.includes('cancelled'));
  else if (scenario === 'new-failed') assert(status.textContent.includes('notification failed'));
  else if (scenario.startsWith('poll-')) assert(status.textContent.includes('could not be read'));
  else if (scenario === 'sender-unavailable') assert(status.textContent.includes('sender is unavailable'));
  else assert(status.textContent.includes('queued'));
  const terminal = ['accepted', 'failed', 'cancelled'].includes(scenario.split('-').at(-1));
  assert.equal(polls, scenario.includes('poll-') ? 1 : terminal || scenario === 'queued-no-id' ? 0 : 10,
    'delivery polling must be finite and must not create another test');
})().then(() => process.stdout.write('PASS\n')).catch(error => {
  console.error(error.message); process.exitCode = 1;
});
