import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {collectNotices} from '../notices.mjs';

test('every bundle graph contributes notices, including nested dependencies', async t => {
  const root = await mkdtemp(path.join(tmpdir(), 'matsugit-notices-'));
  t.after(() => rm(root, {recursive: true, force: true}));
  const graphs = [];
  for (const name of ['browser', 'server', 'merge', 'story/node_modules/nested']) {
    const relative = `node_modules/${name}`;
    const directory = path.join(root, relative);
    await mkdir(directory, {recursive: true});
    await writeFile(path.join(directory, 'package.json'), JSON.stringify({name, version: '1.0.0', license: 'MIT'}));
    await writeFile(path.join(directory, 'LICENSE'), `Copyright ${name}\nTest license text`);
    graphs.push({inputs: {[relative + '/index.js']: {}}});
  }
  const result = await collectNotices([...graphs, graphs[0]], root);
  for (const name of ['browser', 'server', 'merge', 'story/node_modules/nested']) {
    assert.equal(result.split(`Copyright ${name}`).length - 1, 1);
  }
});

test('missing, empty and stale license supplements fail the build', async t => {
  const root = await mkdtemp(path.join(tmpdir(), 'matsugit-notices-'));
  t.after(() => rm(root, {recursive: true, force: true}));
  const directory = path.join(root, 'node_modules/pkg');
  await mkdir(directory, {recursive: true});
  await writeFile(path.join(directory, 'package.json'), JSON.stringify({name: 'pkg', version: '2.0.0'}));
  const graph = [{inputs: {'node_modules/pkg/index.js': {}}}];
  await assert.rejects(collectNotices(graph, root), /Missing dependency license text: pkg@2.0.0/);
  const supplement = path.join(root, 'supplement.txt');
  await writeFile(supplement, 'Copyright Test\nLicense text');
  await assert.rejects(collectNotices(graph, root, new Map([['pkg@1.0.0', supplement]])), /Missing dependency license/);
  assert.match(await collectNotices(graph, root, new Map([['pkg@2.0.0', supplement]])), /Copyright Test/);
  await writeFile(path.join(directory, 'LICENSE'), ' ');
  await assert.rejects(collectNotices(graph, root), /Missing dependency license/);
});
