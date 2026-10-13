import { createHash, sign } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { readFile, stat, writeFile } from 'node:fs/promises';
import { validateManifest } from '../server.js';
const version = process.argv[2];
async function artifact(name) {
  const file = new URL('../dist/' + name, import.meta.url), hash = createHash('sha256');
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return { name, sha256: hash.digest('hex'), size: (await stat(file)).size };
}
const value = { schema: 1, version, platform: 'windows-x64',
  published_at: new Date().toISOString(), notes: 'Distribuição inicial pelo Farry. Contas e configurações preservadas.',
  package: await artifact('Farry-windows-x64.zip'), installer: await artifact('FarrySetup.exe') };
validateManifest(value, 'v' + version);
const bytes = Buffer.from(JSON.stringify(value));
const key = await readFile(new URL('../secrets/update-private.pem', import.meta.url));
await writeFile(new URL('../dist/release.json', import.meta.url), bytes);
await writeFile(new URL('../dist/release.json.sig', import.meta.url), sign('RSA-SHA256', bytes, key).toString('base64'));
console.log(`Manifesto ${version} assinado.`);
