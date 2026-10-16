import { readFile, writeFile } from 'node:fs/promises';
import { sign } from 'node:crypto';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const output = process.argv[2] ? pathToFileURL(resolve(process.argv[2]) + '/') : new URL('../work/launcher-tests/', import.meta.url);
const value = { schema: 1, version: '1.0.63', platform: 'windows-x64',
  package: { name: 'Farry-windows-x64.zip', size: 3, sha256: 'a'.repeat(64) } };
const bytes = Buffer.from(JSON.stringify(value));
const key = await readFile(new URL('../secrets/update-private.pem', import.meta.url));
const signature = sign('RSA-SHA256', bytes, key).toString('base64');
await writeFile(new URL('valid.json', output), JSON.stringify({ manifest: bytes.toString('base64'), signature }));
value.version = '9.0.0';
await writeFile(new URL('invalid.json', output), JSON.stringify({ manifest: Buffer.from(JSON.stringify(value)).toString('base64'), signature }));
