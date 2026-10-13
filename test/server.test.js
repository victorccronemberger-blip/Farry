import test from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign } from 'node:crypto';
import { createApp, validateManifest } from '../server.js';

const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const key = publicKey.export({ type: 'spki', format: 'pem' });
const manifest = { schema: 1, version: '1.0.63', platform: 'windows-x64',
  package: { name: 'Farry-windows-x64.zip', sha256: 'a'.repeat(64), size: 3 } };
function fixture(overrides = {}) {
  const bytes = Buffer.from(JSON.stringify(manifest));
  const signature = sign('RSA-SHA256', bytes, privateKey).toString('base64');
  const release = { tag_name: 'v1.0.63', draft: false, prerelease: false,
    assets: ['release.json', 'release.json.sig', 'Farry-windows-x64.zip'].map((name, i) =>
      ({ id: i + 1, name, state: 'uploaded', size: i === 2 ? 3 : 1 })), ...overrides };
  const requests = [];
  const fetchImpl = async (url, options) => {
    requests.push({ url: String(url), options });
    if (String(url).includes('/releases/assets/1')) return new Response(bytes);
    if (String(url).includes('/releases/assets/2')) return new Response(signature);
    if (String(url).includes('/releases/assets/3')) return new Response('zip');
    return Response.json(release);
  };
  return { fetchImpl, requests };
}
async function serve(t, options = {}) {
  const server = createApp({ publicKey: key, env: { GITHUB_TOKEN: 'test-secret' }, ...options }).listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  return `http://127.0.0.1:${server.address().port}`;
}
test('health and landing page work before private repository is configured', async t => {
  const base = await serve(t, { env: {} });
  assert.equal((await (await fetch(base + '/health')).json()).repository_configured, false);
  assert.equal((await fetch(base)).status, 200);
  const response = await fetch(base + '/api/releases/latest');
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { error: 'repository_not_configured' });
});
test('signed manifest is verified, cached and no private GitHub fields are exposed', async t => {
  const f = fixture(); const base = await serve(t, f);
  const results = await Promise.all(Array.from({ length: 5 }, () => fetch(base + '/api/releases/latest').then(r => r.json())));
  assert.equal(f.requests.length, 3);
  assert.equal(JSON.parse(Buffer.from(results[0].manifest, 'base64')).version, '1.0.63');
  assert.ok(!JSON.stringify(results).includes('test-secret'));
  assert.deepEqual(Object.keys(results[0]).sort(), ['manifest', 'signature']);
});
test('rejects drafts, prereleases and incomplete releases', async t => {
  for (const change of [{ draft: true }, { prerelease: true }, { assets: [] }]) {
    const base = await serve(t, fixture(change));
    assert.ok([404, 503].includes((await fetch(base + '/api/releases/latest')).status));
  }
});
test('invalid signature never enables downloads', async t => {
  const f = fixture(); const original = f.fetchImpl;
  f.fetchImpl = (url, options) => String(url).endsWith('/assets/2') ? Promise.resolve(new Response('fake')) : original(url, options);
  const base = await serve(t, f);
  const r = await fetch(base + '/downloads/v1.0.63/Farry-windows-x64.zip');
  assert.equal(r.status, 502);
  assert.equal((await r.json()).error, 'invalid_release_signature');
});
test('only allowlisted assets in published releases are downloadable', async t => {
  const f = fixture(); const base = await serve(t, f);
  assert.equal((await fetch(base + '/downloads/v1.0.63/private.zip')).status, 404);
  assert.equal(f.requests.length, 0);
  assert.equal(await (await fetch(base + '/downloads/v1.0.63/Farry-windows-x64.zip')).text(), 'zip');
  assert.equal((await fetch(base + '/.env')).status, 404);
});
test('redirect download never sends the server token to storage', async t => {
  const f = fixture(); const original = f.fetchImpl;
  f.fetchImpl = async (url, options) => {
    if (String(url).endsWith('/assets/3')) return new Response(null, { status: 302,
      headers: { location: 'https://release-assets.githubusercontent.com/example' } });
    return original(url, options);
  };
  const base = await serve(t, f);
  const response = await fetch(base + '/downloads/v1.0.63/Farry-windows-x64.zip', { redirect: 'manual' });
  assert.equal(response.status, 302);
  assert.equal(response.headers.get('location'), 'https://release-assets.githubusercontent.com/example');
  assert.equal(response.headers.get('authorization'), null);
});
test('rejects arbitrary upstream redirects and sanitizes upstream errors', async t => {
  const f = fixture(); const original = f.fetchImpl;
  f.fetchImpl = async (url, options) => {
    if (String(url).endsWith('/assets/3')) return new Response(null, { status: 302, headers: { location: 'http://localhost/private' } });
    return original(url, options);
  };
  const base = await serve(t, f);
  assert.equal((await fetch(base + '/downloads/v1.0.63/Farry-windows-x64.zip')).status, 502);
  const errorBase = await serve(t, { fetchImpl: async () => { throw new Error('test-secret'); } });
  assert.equal(await (await fetch(errorBase + '/api/releases/latest')).text(), '{"error":"upstream_unavailable"}');
});
test('manifest cannot select another package or lie about its version', () => {
  for (const change of [{ version: '9.0.0' }, { platform: 'linux' }, { package: { ...manifest.package, name: '../file' } },
    { package: { ...manifest.package, size: -1 } }])
    assert.throws(() => validateManifest({ ...manifest, ...change }, 'v1.0.63'));
});
