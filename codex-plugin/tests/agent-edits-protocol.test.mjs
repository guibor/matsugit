import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';

const root = fileURLToPath(new URL('../../',import.meta.url));
test('agent slide tools expose their write scope and reject stale revisions over MCP', async () => {
  const directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'matsugit-agent-api-')));
  const file = path.join(directory,'deck.md'), source = '## One\nEvidence A\n\n## Two\nEvidence B\n';
  fs.writeFileSync(file,source);
  const client = new Client({name:'agent-edit-test',version:'1.0'});
  try {
    await client.connect(new StdioClientTransport({command:process.execPath,args:[path.join(root,'codex-plugin/bundle/server.mjs')],stderr:'pipe'}));
    const tools = (await client.listTools()).tools;
    for (const name of ['matsugit_read_slide','matsugit_edit_slide']) assert.equal(tools.find(t => t.name === name)._meta?.ui,undefined);
    assert.equal(tools.find(t => t.name === 'matsugit_edit_slide').annotations.destructiveHint,true);
    assert.equal(tools.find(t => t.name === 'matsugit_doctor').annotations.readOnlyHint,true);
    const call = async (name,args) => {
      const result = await client.callTool({name,arguments:args});
      assert.notEqual(result.isError,true,JSON.stringify(result));
      return result.structuredContent;
    };
    const snapshot = await call('matsugit_read_slide',{path:file,slide:2});
    const edits = [{old:'Evidence B',new:'New evidence'}];
    assert.equal((await call('matsugit_edit_slide',{edit_id:snapshot.edit_id,edits,preview_only:true})).outcome,'preview');
    assert.equal(fs.readFileSync(file,'utf8'),source);
    const human = source.replace('Evidence A','Human edit'); fs.writeFileSync(file,human);
    assert.equal((await call('matsugit_edit_slide',{edit_id:snapshot.edit_id,edits})).outcome,'conflict');
    assert.equal(fs.readFileSync(file,'utf8'),human);
    const fresh = await call('matsugit_read_slide',{path:file,slide:2});
    assert.equal((await call('matsugit_edit_slide',{edit_id:fresh.edit_id,edits})).outcome,'saved');
    const finalSource = human.replace('Evidence B','New evidence');
    assert.equal(fs.readFileSync(file,'utf8'),finalSource);
    const report = await call('matsugit_doctor',{});
    assert.equal(report.schema,1);
    assert.equal(typeof report.ready,'boolean');
    assert.deepEqual(report.checks.filter(c => c.required).map(c => c.id),['python','git','node','quarto','converter']);
    assert.equal(fs.readFileSync(file,'utf8'),finalSource);
  } finally { await client.close(); fs.rmSync(directory,{recursive:true,force:true}); }
});
