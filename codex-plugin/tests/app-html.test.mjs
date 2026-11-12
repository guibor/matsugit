import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {bundledApp} from '../app-html.mjs';

test('the app inspection CLI works in paths requiring URL encoding', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit app #'));
  try {
    fs.copyFileSync(new URL('../app-html.mjs', import.meta.url), path.join(root, 'app-html.mjs'));
    fs.mkdirSync(path.join(root, 'bundle'));
    fs.copyFileSync(new URL('../bundle/server.mjs', import.meta.url), path.join(root, 'bundle/server.mjs'));
    assert.equal(execFileSync(process.execPath, [path.join(root, 'app-html.mjs')],
      {encoding: 'utf8', maxBuffer: 8 * 1024 * 1024}), bundledApp());
  } finally {
    fs.rmSync(root, {recursive: true, force: true});
  }
});
