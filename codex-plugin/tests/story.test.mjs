import {test} from 'node:test';
import assert from 'node:assert/strict';
import {storyModel, titleRange, moveStory, adjacentMove, insertStory, insertClaim} from '../src/story-model.mjs';
import {preferences} from '../src/recovery.mjs';

const apply = (source, result) => result ? source.slice(0,result.changes.from) + result.changes.insert + source.slice(result.changes.to ?? result.changes.from) : source;
const preamble = '---\ntitle: Narrative\nslide-layout: structured\n---\n\n';
const a = '# Context\n\n## Same\n### Grow carefully\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n::: notes\nPrivate note\n::: \n\n';
const b = '## Same\n### Learn first\n\n![Evidence](image.png)\n\n:::: agent-comment\n## Not a slide\n::::\n\n';
const c = '# Decision\n\n## Commit\n### Scale deliberately\n\n::: takeaway\nProceed\n:::\n';

test('story groups duplicate titles by positions and excludes literal / nested headings', () => {
  const source = preamble+a+b+c+'\n```md\n## Example\n```\n\n:::: columns\n## Nested\n::::\n';
  const m = storyModel(source);
  assert.deepEqual(m.slides.map(n => n.label),['Same','Same','Commit']);
  assert.deepEqual(m.slides.map(n => n.number),[1,2,3]);
  assert.deepEqual(m.sections.map(n => n.children.map(c => c.label)),[['Same','Same'],['Commit']]);
  assert.equal(m.slides[0].end,source.indexOf(b));
  assert.equal(m.sections[0].end,source.indexOf(c));
});

test('section moves carry all slides, claims, evidence and notes; metadata remains fixed', () => {
  const source = preamble+a+b+c, m = storyModel(source);
  const result = moveStory(source,m.sections[1].from,m.sections[0].from);
  const moved = apply(source,result);
  assert.equal(moved,preamble+c+'\n'+a+b);
  assert.equal(result.anchor,preamble.length);
  assert.deepEqual(storyModel(moved).sections.map(n=>n.label),['Decision','Context']);
});

test('a slide moves between sections without losing its attached body', () => {
  const source = preamble+a+b+c, m = storyModel(source);
  const moved = apply(source,moveStory(source,m.slides[0].from,m.sections[1].from,'inside'));
  assert.equal(storyModel(moved).slides[2].label,'Same');
  assert.equal(storyModel(moved).slides[2].parent.label,'Decision');
  assert(moved.endsWith(a.slice(a.indexOf('## Same'))));
  assert.equal(moved.split('Private note').length,2);
  assert(moved.startsWith(preamble+'# Context\n\n'+b));
});

test('move arrows stay within siblings and preserve duplicate titles', () => {
  const source = preamble+a+b+c, m = storyModel(source);
  assert.equal(adjacentMove(source,m.slides[0].from,-1),null);
  const moved = apply(source,adjacentMove(source,m.slides[1].from,-1));
  assert.equal(moved,preamble+'# Context\n\n'+b+a.slice('# Context\n\n'.length)+c);
  assert.equal(moveStory(source,m.sections[0].from,m.sections[0].from),null);
  assert.throws(()=>moveStory(source,m.slides[0].from,m.sections[0].from,'before'),/Move sections/);
});

test('manual continuations stay attached, without treating notes or code rules as slides', () => {
  const source = '## First\n### Claim\n\nOne\n\n---\n\nTwo\n\n::: notes\n\n---\n::: \n\n## Second\n\nEnd';
  const m = storyModel(source);
  assert.equal(m.slides[0].continuations,1);
  const moved = apply(source,adjacentMove(source,m.slides[0].from,1));
  assert(moved.startsWith('## Second\n\nEnd\n\n## First'));
  assert(moved.endsWith(source.slice(0,source.indexOf('## Second'))));
});

test('EOF without newline, Setext headings and CRLF remain parseable after moving', () => {
  const source = '# Topic\r\n\r\nFirst\r\n-----\r\n\r\nOne\r\n\r\n## Second\r\n\r\nTwo';
  const m = storyModel(source), moved = apply(source,adjacentMove(source,m.slides[1].from,-1));
  assert(moved.includes('Two\r\n\r\nFirst\r\n-----'));
  assert.deepEqual(storyModel(moved).slides.map(n=>n.label),['Second','First']);
  assert(!/(?<!\r)\n/.test(moved));
});

test('editing heading ranges preserves attributes, closing hashes, links and Org metadata', () => {
  const source = '## **Title** [link](https://example.test) {#stable .hide-title} ##\r\n';
  const node = storyModel(source).slides[0], range = titleRange(source,node);
  assert.equal(range.text,'**Title** [link](https://example.test)');
  assert.equal(source.slice(0,range.from)+'New'+source.slice(range.to),'## New {#stable .hide-title} ##\r\n');
  const org = '** TODO [#A] \u05e9\u05dc\u05d5\u05dd :work:next:\n';
  const r = titleRange(org,storyModel(org,true).slides[0],true);
  assert.equal(r.text,'\u05e9\u05dc\u05d5\u05dd');
  assert.equal(org.slice(0,r.from)+'Other'+org.slice(r.to),'** TODO [#A] Other :work:next:\n');
  const setext = 'A title\n--------\n';
  assert.equal(titleRange(setext,storyModel(setext).slides[0]).text,'A title');
});

test('Org moves preserve drawers, blocks and Unicode', () => {
  const source = '#+title: Plan\n\n* Topic\n** One\n:PROPERTIES:\n:CUSTOM_ID: one\n:END:\n*** Claim\n#+begin_src org\n** Fake\n#+end_src\n\n** Two\n\n\u05e9\u05dc\u05d5\u05dd\n';
  const m = storyModel(source,true);
  assert.equal(m.slides.length,2);
  const moved = apply(source,adjacentMove(source,m.slides[1].from,-1,true));
  assert(moved.startsWith('#+title: Plan\n\n* Topic\n** Two\n\n\u05e9\u05dc\u05d5\u05dd\n\n** One'));
  assert(moved.includes(':CUSTOM_ID: one'));
});

test('unfinished blocks fail closed for reordering, never swallow later source', () => {
  const source = '## One\n\nBody\n\n## Two\n\n::: notes\nSecret\n## Not a slide\n';
  const m = storyModel(source);
  assert.equal(m.slides.length,2);
  assert.throws(()=>adjacentMove(source,m.slides[1].from,-1),/unfinished/);
  const code = '## One\n\nBody\n\n## Two\n\n```md\nNever closed\n';
  assert.throws(()=>adjacentMove(code,storyModel(code).slides[1].from,-1),/parsed/);
});

test('Story view settings survive recovery with conservative validation', () => {
  const view = preferences({layout:'story',storyDepth:2,storyPreview:true});
  assert.equal(view.layout,'story'); assert.equal(view.storyDepth,2); assert.equal(view.storyPreview,true);
  assert.equal(preferences({storyDepth:10,storyPreview:'true'}).storyDepth,3);
  assert.equal(preferences({storyPreview:'true'}).storyPreview,false);
});

test('new slides and sections are inserted after the whole selected subtree', () => {
  const source = preamble+a+b+c, position = source.indexOf('Grow carefully');
  const result = insertStory(source,position,'slide');
  const next = apply(source,result);
  assert(next.includes('Private note\n::: \n\n## New slide\n\n'+b));
  assert.equal(storyModel(next).slides[1].from,result.anchor);
  const section = apply(source,insertStory(source,position,'section'));
  assert(section.includes(b+'# New section\n\n'+c));
  assert.equal(apply('',insertStory('',0,'section',true)),'* New section\n\n');
});

test('inserting a claim preserves Org properties on the original slide', () => {
  const source = '** A\nSCHEDULED: <2026-11-06 Fri>\n:PROPERTIES:\n:CUSTOM_ID: a\n:END:\n\nEvidence\n';
  const result = insertClaim(source,storyModel(source,true).slides[0],true);
  assert.equal(apply(source,result),'** A\nSCHEDULED: <2026-11-06 Fri>\n:PROPERTIES:\n:CUSTOM_ID: a\n:END:\n\n*** Main claim\n\n\nEvidence\n');
});

test('explicit claim blocks are retained and prevent inserting a competing heading claim', () => {
  const source = '## Title\n\n::: claim\nThe main point\n:::\n\nEvidence\n';
  assert.equal(storyModel(source).slides[0].hasBlockClaim,true);
});
