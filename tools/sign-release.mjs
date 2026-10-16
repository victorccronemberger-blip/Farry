import { createHash, sign } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { readFile, stat, writeFile } from 'node:fs/promises';
import { validateManifest } from '../app.js';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const version = process.argv[2];
const directory = process.argv[3] ? pathToFileURL(resolve(process.argv[3]) + '/') : new URL('../dist/', import.meta.url);
const applicationVersion = process.argv[4] || version;
async function artifact(name) {
  const file = new URL(name, directory), hash = createHash('sha256');
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return { name, sha256: hash.digest('hex'), size: (await stat(file)).size };
}
let provenance;
try { provenance = JSON.parse((await readFile(new URL('payload-source.json', directory), 'utf8')).replace(/^\uFEFF/, '')); }
catch (error) { if (error.code !== 'ENOENT') throw error; }
const value = { schema: 1, version, application_version: applicationVersion, platform: 'windows-x64',
  published_at: new Date().toISOString(), notes: 'Instalador por usuário com desinstalação registrada, assinatura interna e atualizações verificadas. Contas, configurações e arquivos preservados.',
  ...(provenance ? { provenance } : {}),
  package: await artifact('Farry-windows-x64.zip'), installer: await artifact('FarrySetup.exe') };
validateManifest(value, 'v' + version);
const bytes = Buffer.from(JSON.stringify(value));
const key = await readFile(new URL('../secrets/update-private.pem', import.meta.url));
await writeFile(new URL('release.json', directory), bytes);
await writeFile(new URL('release.json.sig', directory), sign('RSA-SHA256', bytes, key).toString('base64'));
console.log(`Manifesto ${version} assinado.`);
