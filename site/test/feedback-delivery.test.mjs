import test from 'node:test';
import assert from 'node:assert/strict';
import { onRequestPost } from '../functions/api/feedback.js';

const env = { GITHUB_REPO: 'fixture/feedback', GITHUB_TOKEN: 'fixture-only-not-a-secret' };
const input = { kind: 'bug', title: 'Fixture report', message: 'An isolated delivery test.', elapsed: 4000 };
function submit(environment = env, body = input) {
  return onRequestPost({
    env: environment,
    request: new Request('https://fixture.invalid/api/feedback', {
      method: 'POST', headers: { origin: 'https://fixture.invalid', 'content-type': 'application/json' },
      body: JSON.stringify(body),
    }),
  });
}

test('a submission rejected before GitHub is safe to send elsewhere', async t => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; throw new Error('unexpected network'); });
  for (const [environment, body, status] of [[{}, input, 503], [env, { ...input, title: 'no' }, 400]]) {
    const response = await submit(environment, body);
    assert.equal(response.status, status);
    assert.equal((await response.json()).retrySafe, true);
  }
  assert.equal(calls, 0);
});

test('an acknowledged GitHub rejection offers the fallback without retrying the POST', async t => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; return new Response('{}', { status: 422 }); });
  const response = await submit();
  assert.equal(response.status, 502);
  assert.equal((await response.json()).retrySafe, true);
  assert.equal(calls, 1);
});

test('lost, failed or malformed acknowledgements retain uncertainty and never repeat the POST', async t => {
  const replies = [
    () => { throw new Error('connection lost after request'); },
    () => new Response('{}', { status: 503 }),
    () => new Response('not JSON', { status: 201 }),
    () => new Response('{}', { status: 201 }),
    () => Response.json({ number: 7, html_url: 'https://elsewhere.invalid/issues/7' }, { status: 201 }),
  ];
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; return replies.shift()(); });
  for (let index = 0; index < 5; index++) {
    const response = await submit();
    assert.equal(response.status, 502);
    const body = await response.json();
    assert.equal(body.retrySafe, false);
    assert.match(body.error, /Check recent issues/);
    assert.equal(calls, index + 1);
  }
});

test('success requires a receipt for an issue in the configured repository', async t => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async (url, request) => {
    calls++;
    assert.equal(url, 'https://api.github.com/repos/fixture/feedback/issues');
    assert.equal(request.method, 'POST');
    return Response.json({ number: 7, html_url: 'https://github.com/fixture/feedback/issues/7' }, { status: 201 });
  });
  const response = await submit();
  assert.equal(response.status, 201);
  assert.deepEqual(await response.json(), { ok: true, number: 7, url: 'https://github.com/fixture/feedback/issues/7' });
  assert.equal(calls, 1);
});
