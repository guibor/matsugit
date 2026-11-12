import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {brotliCompressSync} from 'node:zlib';
import {PluginRuntime} from '../src/runtime.mjs';

const files = {'codex-plugin/worker.py': '# worker', 'matsugit/core.py': '# core',
  'matsugit/preview.py': '# preview', 'matsugit/runtime/layout.css': 'p {}',
  'matsugit/themes/default/theme.json': '{}'};
const archive = (extra = {}) => brotliCompressSync(JSON.stringify({app: '<html>Bundled UI</html>',
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

test('text files arrive as text and binary files as base64, and both are written byte for byte', () => {
  const binary = Buffer.from([0, 255, 1, 128, 10]);
  const runtime = new PluginRuntime(brotliCompressSync(JSON.stringify({app: '<html></html>',
    files: {'matsugit/runtime/picture.bin': binary.toString('base64')},
    texts: {...files, 'matsugit/runtime/unicode.js': 'const label = "café ✓";\n'}})).toString('base64'));
  try {
    const root = runtime.root();
    assert.deepEqual(fs.readFileSync(path.join(root, 'matsugit/runtime/picture.bin')), binary);
    assert.equal(fs.readFileSync(path.join(root, 'matsugit/runtime/unicode.js'), 'utf8'), 'const label = "café ✓";\n');
    assert.equal(fs.readFileSync(path.join(root, 'matsugit/core.py'), 'utf8'), '# core');
    assert.equal(runtime.intact(), true);
  } finally { runtime.close(); }
  assert.throws(() => new PluginRuntime(brotliCompressSync(JSON.stringify({app: '', files: {}, texts: {'../escape.py': 'x'}})).toString('base64')), /runtime path/);
});
