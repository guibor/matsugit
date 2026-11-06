import {test} from 'node:test';
import assert from 'node:assert/strict';
import {storyRequest} from '../src/story-bridge.mjs';
const apply = (source,result) => {const chars=[...source],c=result.change; return chars.slice(0,c.from).join('')+c.insert+chars.slice(c.to).join('');};

test('Emacs Story shares heading grammar and Unicode character positions',()=>{
  const source='---\ntitle: Deck\n---\n\n# \ud83d\ude80 Section\n\n## First {.hide-title}\n### Claim\n\n::: takeaway\nRemember\n:::\n\n## Second\nEvidence\n';
  const model=storyRequest({source});
  assert.equal(model.slides,2); assert.equal(model.sections,1);
  const first=model.nodes[1]; assert.equal(first.title,'First'); assert.equal(first.claims[0].label,'Claim'); assert.equal(first.takeaways[0].label,'Remember');
  const edit=storyRequest({source,action:'edit',from:first.from,text:'Changed'});
  const changed=apply(source,edit);
  assert.match(changed,/## Changed \{.hide-title\}/); assert.ok(changed.startsWith('---\ntitle: Deck'));
  const moved=apply(source,storyRequest({source,action:'move',from:first.from,target:model.nodes[2].from,placement:'after'}));
  assert.ok(moved.indexOf('## Second')<moved.indexOf('## First')); assert.match(moved,/Remember\n:::/);
});
test('Org properties, source blocks, empty slides and claims stay native',()=>{
  const source='#+title: Native\n* Section\n** Slide\n:PROPERTIES:\n:CUSTOM_ID: stable\n:END:\n#+begin_src markdown\n## Not a slide\n#+end_src\n';
  const model=storyRequest({source,org:true}); assert.equal(model.slides,1);
  const added=apply(source,storyRequest({source,org:true,action:'claim',from:model.nodes[1].from}));
  assert.ok(added.indexOf(':END:')<added.indexOf('*** Main claim'));
  const inserted=apply(source,storyRequest({source,org:true,action:'insert',from:model.nodes[1].from,kind:'slide',title:'New',claim:'Message'}));
  assert.match(inserted,/\*\* New\n\n\*\*\* Message/); assert.equal(storyRequest({source:inserted,org:true}).slides,2);
});
test('malformed requests never imply a write or manufacture a target',()=>{
  assert.throws(()=>storyRequest({source:'## Slide',action:'edit',from:123,text:'No'}),/position/);
  assert.throws(()=>storyRequest({source:'## Slide',action:'edit',from:0,text:'Title\n## Injection'}),/one nonempty/);
  assert.throws(()=>storyRequest({source:'## Slide\n::: columns\n',action:'insert',kind:'slide',title:'No'}),/unfinished/);
});
