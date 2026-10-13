import { generateKeyPairSync, createPublicKey } from 'node:crypto';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
await mkdir(new URL('../secrets/', import.meta.url), { recursive: true });
await mkdir(new URL('../keys/', import.meta.url), { recursive: true });
const privatePath = new URL('../secrets/update-private.pem', import.meta.url);
let privateKey;
try { privateKey = await readFile(privatePath, 'utf8'); }
catch (error) {
  if (error.code !== 'ENOENT') throw error;
  privateKey = generateKeyPairSync('rsa', { modulusLength: 3072 }).privateKey.export({ type: 'pkcs8', format: 'pem' });
  await writeFile(privatePath, privateKey, { flag: 'wx', mode: 0o600 });
}
const key = createPublicKey(privateKey);
await writeFile(new URL('../keys/update-public.pem', import.meta.url), key.export({ type: 'spki', format: 'pem' }));
const jwk = key.export({ format: 'jwk' });
const xml = `<RSAKeyValue><Modulus>${Buffer.from(jwk.n, 'base64url').toString('base64')}</Modulus><Exponent>${Buffer.from(jwk.e, 'base64url').toString('base64')}</Exponent></RSAKeyValue>`;
await mkdir(new URL('../launcher/', import.meta.url), { recursive: true });
await writeFile(new URL('../launcher/ReleaseKey.cs', import.meta.url), `internal static class ReleaseKey { internal const string Xml = "${xml}"; }\n`);
console.log('Chave pública preparada. A chave privada permanece em secrets/ e não é publicada.');
