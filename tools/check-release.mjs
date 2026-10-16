import { createHash, verify } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { readFile, stat } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { validateManifest } from '../app.js';

export async function checkRelease(directory, publicKey, version) {
  const bytes = await readFile(resolve(directory, 'release.json'));
  if (bytes.length > 32768) throw new Error('Manifesto excessivo');
  const signature = await readFile(resolve(directory, 'release.json.sig'), 'ascii');
  if (!verify('RSA-SHA256', bytes, publicKey, Buffer.from(signature.trim(), 'base64')))
    throw new Error('Assinatura do manifesto inválida');
  const manifest = JSON.parse(bytes);
  validateManifest(manifest, 'v' + version);
  for (const [name, artifact] of [['Farry-windows-x64.zip', manifest.package], ['FarrySetup.exe', manifest.installer]]) {
    if (!artifact || artifact.name !== name || !/^[a-f0-9]{64}$/.test(artifact.sha256)
        || !Number.isSafeInteger(artifact.size) || artifact.size < 1)
      throw new Error('Artefato obrigatório inválido: ' + name);
    const file = resolve(directory, name);
    if ((await stat(file)).size !== artifact.size) throw new Error('Tamanho incorreto: ' + name);
    const hash = createHash('sha256');
    for await (const chunk of createReadStream(file)) hash.update(chunk);
    if (hash.digest('hex') !== artifact.sha256) throw new Error('SHA-256 incorreto: ' + name);
  }
  return manifest;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const [, , version, directory = new URL('../dist/', import.meta.url)] = process.argv;
  const manifest = await checkRelease(directory instanceof URL ? fileURLToPath(directory) : directory,
    await readFile(new URL('../keys/update-public.pem', import.meta.url)), version);
  console.log(`Release ${manifest.version}: assinatura, tamanhos e SHA-256 dos dois artefatos conferidos.`);
}
