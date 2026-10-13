import express from 'express';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { createPublicKey, verify } from 'node:crypto';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';

const PACKAGE = 'Farry-windows-x64.zip';
const ASSETS = new Set([PACKAGE, 'FarrySetup.exe', 'release.json', 'release.json.sig']);
const TAG = /^v(?:0|[1-9]\d{0,5})\.(?:0|[1-9]\d{0,5})\.(?:0|[1-9]\d{0,5})$/;
class HttpError extends Error {
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}
export function validateManifest(value, tag) {
  if (!value || value.schema !== 1 || !TAG.test(tag) || value.version !== tag.slice(1)
      || value.platform !== 'windows-x64' || value.package?.name !== PACKAGE
      || !/^[a-f0-9]{64}$/.test(value.package?.sha256 ?? '')
      || !Number.isSafeInteger(value.package?.size) || value.package.size < 1
      || value.package.size > 8 * 1024 ** 3) throw new HttpError(502, 'invalid_release');
  return value;
}
export function createApp({ env = process.env, fetchImpl = fetch, publicKey, now = Date.now } = {}) {
  const app = express();
  app.disable('x-powered-by');
  const repository = env.GITHUB_REPOSITORY || 'victorccronemberger-blip/Farry';
  if (!/^[\w.-]+\/[\w.-]+$/.test(repository)) throw new Error('Invalid repository');
  const api = `https://api.github.com/repos/${repository}`;
  const cache = new Map(), pending = new Map();
  async function github(path, accept = 'application/vnd.github+json') {
    if (!env.GITHUB_TOKEN) throw new HttpError(503, 'repository_not_configured');
    const response = await fetchImpl(`${api}${path}`, { headers: { Accept: accept,
      'User-Agent': 'Farry-Updates', 'X-GitHub-Api-Version': '2022-11-28',
      Authorization: `Bearer ${env.GITHUB_TOKEN}` }, redirect: 'manual', signal: AbortSignal.timeout(15000) });
    if (response.status === 404) throw new HttpError(404, 'release_not_found');
    if (response.status === 401 || response.status === 403) throw new HttpError(503, 'repository_unavailable');
    if (response.status !== 200 && response.status !== 302) throw new HttpError(502, 'github_unavailable');
    return response;
  }
  function redirectUrl(response) {
    const url = new URL(response.headers.get('location'));
    if (url.protocol !== 'https:' || url.username || url.password
        || !['release-assets.githubusercontent.com', 'objects.githubusercontent.com'].includes(url.hostname))
      throw new HttpError(502, 'invalid_asset_redirect');
    return url;
  }
  async function assetBytes(asset, limit) {
    let response = await github(`/releases/assets/${asset.id}`, 'application/octet-stream');
    if (response.status === 302) response = await fetchImpl(redirectUrl(response), {
      redirect: 'error', signal: AbortSignal.timeout(15000) });
    if (!response.ok || Number(response.headers.get('content-length')) > limit)
      throw new HttpError(502, 'invalid_asset');
    const chunks = []; let length = 0;
    for await (const chunk of response.body) {
      length += chunk.length;
      if (length > limit) throw new HttpError(502, 'invalid_asset');
      chunks.push(chunk);
    }
    return Buffer.concat(chunks);
  }
  async function loadRelease(tag = 'latest') {
    const cached = cache.get(tag);
    if (cached && cached.until > now()) return cached.value;
    if (pending.has(tag)) return pending.get(tag);
    const operation = (async () => {
      const response = await github(tag === 'latest' ? '/releases/latest' : `/releases/tags/${tag}`);
      const release = await response.json();
      if (release.draft || release.prerelease || !TAG.test(release.tag_name)
          || (tag !== 'latest' && release.tag_name !== tag)) throw new HttpError(404, 'release_not_found');
      const assets = new Map();
      for (const asset of release.assets || []) {
        if (!ASSETS.has(asset.name)) continue;
        if (assets.has(asset.name) || !Number.isSafeInteger(asset.id) || asset.id < 1
            || asset.state !== 'uploaded') throw new HttpError(502, 'invalid_release');
        assets.set(asset.name, asset);
      }
      if (!assets.has('release.json') || !assets.has('release.json.sig') || !assets.has(PACKAGE))
        throw new HttpError(503, 'release_incomplete');
      const [bytes, sigBytes] = await Promise.all([
        assetBytes(assets.get('release.json'), 32768), assetBytes(assets.get('release.json.sig'), 2048)]);
      const signature = sigBytes.toString('ascii').trim();
      const key = publicKey || await readFile(new URL('./keys/update-public.pem', import.meta.url));
      if (!verify('RSA-SHA256', bytes, createPublicKey(key), Buffer.from(signature, 'base64')))
        throw new HttpError(502, 'invalid_release_signature');
      let manifest;
      try { manifest = JSON.parse(bytes.toString('utf8')); }
      catch { throw new HttpError(502, 'invalid_release'); }
      validateManifest(manifest, release.tag_name);
      if (assets.get(PACKAGE).size !== manifest.package.size) throw new HttpError(502, 'invalid_release');
      if (manifest.installer && (!assets.has('FarrySetup.exe')
          || assets.get('FarrySetup.exe').size !== manifest.installer.size))
        throw new HttpError(502, 'invalid_release');
      const value = { assets, envelope: { manifest: bytes.toString('base64'), signature } };
      if (cache.size > 50) cache.clear();
      cache.set(tag, { until: now() + 60000, value });
      return value;
    })();
    pending.set(tag, operation);
    try { return await operation; } finally { pending.delete(tag); }
  }
  app.use((_req, res, next) => {
    res.set({ 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
      'Content-Security-Policy': "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'" });
    next();
  });
  app.get('/health', (_req, res) => res.json({ service: 'farry-updates', status: 'ok',
    repository_configured: Boolean(env.GITHUB_TOKEN) }));
  app.get('/api/releases/latest', async (_req, res) => {
    res.set('Cache-Control', 'no-store').json((await loadRelease()).envelope);
  });
  app.get('/downloads/:tag/:name', async (req, res) => {
    const { tag, name } = req.params;
    if (!TAG.test(tag) || !ASSETS.has(name)) throw new HttpError(404, 'not_found');
    const asset = (await loadRelease(tag)).assets.get(name);
    if (!asset) throw new HttpError(404, 'not_found');
    const response = await github(`/releases/assets/${asset.id}`, 'application/octet-stream');
    res.set('Cache-Control', 'no-store');
    if (response.status === 302) return res.redirect(302, redirectUrl(response).href);
    res.set({ 'Content-Type': 'application/octet-stream', 'Content-Disposition': `attachment; filename="${name}"` });
    await pipeline(Readable.fromWeb(response.body), res);
  });
  app.use(express.static(fileURLToPath(new URL('./public', import.meta.url)), { dotfiles: 'deny' }));
  app.use((_req, res) => res.status(404).json({ error: 'not_found' }));
  app.use((err, _req, res, _next) => {
    if (res.headersSent) return res.destroy();
    res.set('Cache-Control', 'no-store').status(err instanceof HttpError ? err.status : 502)
      .json({ error: err instanceof HttpError ? err.code : 'upstream_unavailable' });
  });
  return app;
}
