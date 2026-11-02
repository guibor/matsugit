import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {gzipSync} from 'node:zlib';
import {PluginRuntime} from '../src/runtime.mjs';

const files = {'codex-plugin/worker.py': '# worker', 'matsugit/core.py': '# core',
  'matsugit/preview.py': '# preview', 'matsugit/runtime/layout.css': 'p {}',
  'matsugit/themes/default/theme.json': '{}'};
const archive = (extra = {}) => gzipSync(JSON.stringify({app: '<html>Bundled UI</html>',
  files: Object.fromEntries(Object.entries({...files, ...extra}).map(([name, text]) =>
    [name, Buffer.from(text).toString('base64')]))})).toString('base64');

test('renderer is process-owned, complete, reusable and private', () => {
  const one = new PluginRuntime(archive()), two = new PluginRuntime(archive());
  let root, other;
  try {
    assert.equal(one.app, '<html>Bundled UI</html>');
    root = one.root(); other = two.root();
    assert.notEqual(root, other);
    assert.equal(one.root(), root);
    for (const [name, text] of Object.entries(files)) assert.equal(fs.readFileSync(path.join(root, name), 'utf8'), text);
    if (process.platform !== 'win32') {
      assert.equal(fs.statSync(root).mode & 0o777, 0o700);
      assert.equal(fs.statSync(path.join(root, 'codex-plugin/worker.py')).mode & 0o777, 0o600);
    }
  } finally { one.close(); two.close(); }
  assert.equal(fs.existsSync(root), false);
  assert.equal(fs.existsSync(other), false);
});

test('deleted or changed runtime files are recreated from this version in memory', () => {
  const runtime = new PluginRuntime(archive());
  try {
    const first = runtime.root();
    fs.rmSync(first, {recursive: true});
    const second = runtime.root();
    assert.notEqual(first, second);
    fs.writeFileSync(path.join(second, 'matsugit/core.py'), '# Changed');
    const third = runtime.root();
    assert.notEqual(second, third);
    assert.equal(fs.readFileSync(path.join(third, 'matsugit/core.py'), 'utf8'), '# core');
    // Do not remove an older directory out from under an in-flight worker.
    assert.equal(fs.existsSync(second), true);
  } finally { runtime.close(); }
});

test('bundled paths cannot escape the renderer directory', () => {
  for (const name of ['../escape.py', '/tmp/escape.py', 'matsugit/../../escape',
    'matsugit\\escape', 'matsugit/.hidden', 'private/theme.css']) {
    assert.throws(() => new PluginRuntime(archive({[name]: 'bad'})), /runtime path/);
  }
});
