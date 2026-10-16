import test from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, createHash, sign } from 'node:crypto';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { checkRelease } from '../tools/check-release.mjs';

test('publication checks both signed artifacts and rejects tampering or version mismatch', async t => {
  const root = await mkdtemp(join(tmpdir(), 'farry-release-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
  const manifest = { schema: 1, version: '1.0.64', platform: 'windows-x64' };
  for (const [field, name] of [['package', 'Farry-windows-x64.zip'], ['installer', 'FarrySetup.exe']]) {
    const bytes = Buffer.from(name);
    await writeFile(join(root, name), bytes);
    manifest[field] = { name, size: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
  }
  async function save() {
    const bytes = Buffer.from(JSON.stringify(manifest));
    await writeFile(join(root, 'release.json'), bytes);
    await writeFile(join(root, 'release.json.sig'), sign('RSA-SHA256', bytes, privateKey).toString('base64'));
  }
  await save();
  assert.equal((await checkRelease(root, publicKey, '1.0.64')).version, '1.0.64');
  await assert.rejects(checkRelease(root, publicKey, '1.0.65'));
  await writeFile(join(root, 'FarrySetup.exe'), Buffer.alloc(manifest.installer.size));
  await assert.rejects(checkRelease(root, publicKey, '1.0.64'), /SHA-256/);
  await writeFile(join(root, 'FarrySetup.exe'), 'FarrySetup.exe');
  await writeFile(join(root, 'Farry-windows-x64.zip'), 'incomplete');
  await assert.rejects(checkRelease(root, publicKey, '1.0.64'), /Tamanho/);
  await writeFile(join(root, 'Farry-windows-x64.zip'), 'Farry-windows-x64.zip');
  delete manifest.installer;
  await save();
  await assert.rejects(checkRelease(root, publicKey, '1.0.64'), /obrigatório/);
  await writeFile(join(root, 'release.json.sig'), 'invalid');
  await assert.rejects(checkRelease(root, publicKey, '1.0.64'), /Assinatura/);
});
