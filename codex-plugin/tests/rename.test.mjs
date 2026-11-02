import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';

test('rename keeps legacy recovery storage in place and explicit new settings win', () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-rename-'));
  try {
    const legacy = process.platform === 'darwin'
      ? path.join(home, 'Library/Application Support/Folioforge/recovery')
      : path.join(home, '.local/state/folioforge/recovery');
    const modern = process.platform === 'darwin'
      ? path.join(home, 'Library/Application Support/matsugit/recovery')
      : path.join(home, '.local/state/matsugit/recovery');
    const env = {...process.env, HOME: home, XDG_STATE_HOME: path.join(home, '.local/state')};
    delete env.MATSUGIT_RECOVERY_DIR; delete env.FOLIOFORGE_RECOVERY_DIR;
    const module = new URL('../src/recovery.mjs', import.meta.url).href;
    const read = extra => execFileSync(process.execPath, ['--input-type=module', '-e',
      `import {recoveryDirectory} from ${JSON.stringify(module)}; console.log(recoveryDirectory())`],
      {env: {...env, ...extra}, encoding: 'utf8'}).trim();
    assert.equal(read(), modern);
    fs.mkdirSync(legacy, {recursive: true, mode: 0o700});
    fs.writeFileSync(path.join(legacy, 'sentinel'), 'unchanged');
    assert.equal(read(), legacy);
    fs.mkdirSync(modern, {recursive: true, mode: 0o700});
    assert.equal(read(), legacy);
    assert.equal(read({FOLIOFORGE_RECOVERY_DIR: '/legacy-custom'}), '/legacy-custom');
    assert.equal(read({FOLIOFORGE_RECOVERY_DIR: '/legacy-custom', MATSUGIT_RECOVERY_DIR: '/new-custom'}), '/new-custom');
    assert.equal(fs.readFileSync(path.join(legacy, 'sentinel'), 'utf8'), 'unchanged');
  } finally { fs.rmSync(home, {recursive: true, force: true}); }
});
