import { readFile } from 'node:fs/promises';
import { verify, createHash } from 'node:crypto';
import assert from 'node:assert/strict';
import { validateManifest } from '../app.js';
const base = 'https://lightcyan-wolf-956118.hostingersite.com';
const response = await fetch(base + '/api/releases/latest', { signal: AbortSignal.timeout(30000) });
assert.equal(response.status, 200);
const envelope = await response.json(), bytes = Buffer.from(envelope.manifest, 'base64');
assert.ok(verify('RSA-SHA256', bytes, await readFile(new URL('../keys/update-public.pem', import.meta.url)),
  Buffer.from(envelope.signature, 'base64')));
const manifest = JSON.parse(bytes);
validateManifest(manifest, 'v' + manifest.version);
const installerResponse = await fetch(`${base}/downloads/v${manifest.version}/FarrySetup.exe`, { signal: AbortSignal.timeout(30000) });
assert.equal(installerResponse.status, 200);
const installer = Buffer.from(await installerResponse.arrayBuffer());
assert.equal(installer.length, manifest.installer.size);
assert.equal(createHash('sha256').update(installer).digest('hex'), manifest.installer.sha256);
const packageResponse = await fetch(`${base}/downloads/v${manifest.version}/${manifest.package.name}`, {
  headers: { Range: 'bytes=0-3' }, signal: AbortSignal.timeout(30000) });
if (packageResponse.status !== 206) { await packageResponse.body?.cancel(); throw new Error('Package range not available'); }
assert.equal(Buffer.from(await packageResponse.arrayBuffer()).toString('hex'), '504b0304');
console.log(`Live ${manifest.version}: signed manifest, installer hash and package download passed. No executable was run.`);
