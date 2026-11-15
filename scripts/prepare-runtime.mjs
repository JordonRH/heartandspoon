import { open, chmod } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import { userInfo } from 'node:os';
// Generate once. Never read, print or replace an existing runtime secret.
try {
  const file = await open(new URL('../.env', import.meta.url), 'wx', 0o600);
  await file.writeFile(`HEARTH_DB_PASSWORD=${randomBytes(36).toString('hex')}\nHEARTH_BACKUP_KEY=${randomBytes(48).toString('hex')}\nHEARTH_UID=${userInfo().uid}\nHEARTH_GID=${userInfo().gid}\n`);
  await file.close();
  console.log('Created protected runtime configuration; no values displayed.');
} catch (error) {
  if (error.code !== 'EEXIST') throw error;
  console.log('Existing runtime configuration retained without reading it.');
}
