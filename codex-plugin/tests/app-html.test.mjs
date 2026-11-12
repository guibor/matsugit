import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {bundledApp} from '../app-html.mjs';

test('the app inspection CLI works in paths requiring URL encoding', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit app #'));
  const alias = root + ' alias';
  try {
    fs.copyFileSync(new URL('../app-html.mjs', import.meta.url), path.join(root, 'app-html.mjs'));
    fs.mkdirSync(path.join(root, 'bundle'));
    fs.copyFileSync(new URL('../bundle/server.mjs', import.meta.url), path.join(root, 'bundle/server.mjs'));
    fs.symlinkSync(root, alias, 'junction');
    const expected = bundledApp();
    for (const directory of [root, alias]) {
      const actual = execFileSync(process.execPath, [path.join(directory, 'app-html.mjs')],
        {encoding: 'utf8', maxBuffer: 8 * 1024 * 1024});
      assert.equal(actual.length, expected.length, 'Inspection output length: ' + directory);
      assert.ok(actual === expected, 'Inspection bytes: ' + directory);
    }
  } finally {
    fs.rmSync(alias, {recursive: true, force: true});
    fs.rmSync(root, {recursive: true, force: true});
  }
});
