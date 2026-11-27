import {test} from 'node:test';
import assert from 'node:assert/strict';
import {tableRanges} from '../src/visual.mjs';
import {formatProse, headingText} from '../src/prose-edit.mjs';
import {EditorState} from '@codemirror/state';
import {markdown} from '@codemirror/lang-markdown';
import {preferences,RecoveryStore} from '../src/recovery.mjs';
import {WorkspaceStore} from '../src/store.mjs';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const pipe='| Area | Value |\n| --- | --- |\n| **North** | [Report](https://example.com) |';
test('typing spaces in a title never moves them into the hidden markup',()=>{
  for (const suffix of ['', ' {#keep}', ' ###']) {
    const text='## A better '+suffix;
    assert.deepEqual(headingText({from:0,to:text.length,text}),{from:3,to:'## A better '.length});
  }
});
test('format shortcuts compose, toggle off and are inert in code, front matter and anchors',()=>{
  function view(doc, at) {
    return {state:EditorState.create({doc,selection:{anchor:at},extensions:markdown()}),
      dispatch(spec){this.state=this.state.update(spec).state;}};
  }
  const v=view('The pilot.',6);
  for (const [mark,want] of [['**','The **pilot**.'],['*','The ***pilot***.'],['*','The **pilot**.'],['**','The pilot.']]) {
    assert.equal(formatProse(v,mark),true);assert.equal(v.state.doc.toString(),want);
  }
  for (const [doc,at] of [['---\ntitle: Pilot\n---\n\nPilot',12],['Use \x60code\x60.',6],['## Title {#anchor}',14]]) {
    assert.equal(formatProse(view(doc,at),'*'),false);
  }
});
test('visual table detection preserves exact source and GFM cell boundaries',()=>{
  const source='# Topic\n\n'+pipe+'\n\nAfter';
  const [table]=tableRanges(source);
  assert.equal(table.source,pipe);assert.equal(source.slice(table.from,table.to),pipe);
  assert.deepEqual(table.rows,[['Area','Value'],['**North**','[Report](https://example.com)']]);
});
test('fences and YAML are source, not editable table widgets',()=>{
  assert.equal(tableRanges('---\ntitle: Example\ntext: |\n  '+pipe.replaceAll('\n','\n  ')+'\n---\n\n```md\n'+pipe+'\n```').length,0);
});
test('empty and short rows keep their actual column in the visual table',()=>{
  const [table]=tableRanges('| A | B | C |\n|---|---|---|\n| | central | |\n| left\\|right |');
  assert.deepEqual(table.rows,[['A','B','C'],['','central',''],['left\\|right','','']]);
});
test('visual tables retain column alignment instead of making every cell left-aligned',()=>{
  assert.deepEqual(tableRanges('| A | B | C |\n| :--- | :---: | ---: |\n| a | b | c |')[0].alignments,['left','center','right']);
});
test('merged grid candidates retain their full ranges',()=>{
  const grid='+-----+-----+\n| A         |\n+=====+=====+\n| B   | C   |\n+-----+-----+';
  assert.deepEqual(tableRanges('Before\n\n'+grid+'\n\nAfter').map(t=>t.source),[grid]);
  assert.equal(tableRanges('```\n'+grid+'\n```').length,0);
  for (const source of [grid+'\n\n```md\n'+pipe+'\n```','```md\n'+pipe+'\n```\n\n'+grid])
    assert.deepEqual(tableRanges(source).map(t=>t.source),[grid]);
});
test('large tables remain raw instead of silently dropping rows',()=>{
  assert.equal(tableRanges('| A | B |\n| --- | --- |\n'+('| x | y |\n'.repeat(251))).length,0);
});
test('recovery retains visual choice and bounded unapplied table drafts',t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'matsugit-visual-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const store=new RecoveryStore(path.join(dir,'recovery')),{id}=store.begin({name:'test.md'});
  const tableDraft={from:0,to:pipe.length,source:pipe,html:'<table><tr><td>new</td></tr></table>',format:'markdown'};
  store.checkpoint(id,1,{text:pipe,base:pipe,view:{editorMode:'visual',tableDraft}});
  assert.equal(store.list().items[0].dirty,true);
  assert.deepEqual(store.read(id).view.tableDraft,tableDraft);
  assert.equal(store.read(id).view.editorMode,'visual');
  assert.equal(preferences({editorMode:'wrong',tableDraft:{...tableDraft,from:-1}}).tableDraft,null);
  assert.equal(preferences({tableDraft:{...tableDraft,html:'x'.repeat(1024*1024+1)}}).tableDraft,null);
});
test('copy-path data is the actual opened path, not a temporary preview or filename',t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'matsugit-path-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const file=path.join(dir,'My deck.md');fs.writeFileSync(file,pipe);
  const store=new WorkspaceStore('.');assert.equal(store.open(file).path,fs.realpathSync(file));
  assert.equal(store.owner(undefined,undefined),null);
});
