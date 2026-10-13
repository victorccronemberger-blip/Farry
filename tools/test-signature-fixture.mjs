import { readFile, writeFile } from 'node:fs/promises';
import { sign } from 'node:crypto';
const value = { schema: 1, version: '1.0.63', platform: 'windows-x64',
  package: { name: 'Farry-windows-x64.zip', size: 3, sha256: 'a'.repeat(64) } };
const bytes = Buffer.from(JSON.stringify(value));
const key = await readFile(new URL('../secrets/update-private.pem', import.meta.url));
const signature = sign('RSA-SHA256', bytes, key).toString('base64');
await writeFile(new URL('../work/launcher-tests/valid.json', import.meta.url), JSON.stringify({ manifest: bytes.toString('base64'), signature }));
value.version = '9.0.0';
await writeFile(new URL('../work/launcher-tests/invalid.json', import.meta.url), JSON.stringify({ manifest: Buffer.from(JSON.stringify(value)).toString('base64'), signature }));
