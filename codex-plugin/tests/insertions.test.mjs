import {test} from 'node:test';
import assert from 'node:assert/strict';
import {wrapElement, snippetTemplate, ratioLine} from '../src/insertions.mjs';
import {structure} from '../src/structure.mjs';

test('wrap selected evidence without changing or duplicating its contents', () => {
  for (const org of [false,true]) {
    const table = '| A | Value |\n|---|---|\n| Alpha | 12 |';
    const chart = wrapElement('chart-barh',table,org);
    assert.equal(chart.split(table).length,2);
    assert.match(chart,/unit[= ]"units"/);
    assert.throws(()=>wrapElement('chart-bar','Keep my prose.',org),/not changed/);
    const takeaway = wrapElement('takeaway','First\n\n**Second**',org);
    assert.ok(takeaway.includes(org?'First\n\n**Second**':'> First\n> \n> **Second**'));
  }
});
test('snippet fields preserve literal braces and do not interpret selected content', () => {
  assert.equal(snippetTemplate('::: {.chart}\nKey takeaway.\n'), '::: \\{.chart\\}\n${1:Key takeaway.}\n${0}');
  assert.equal(snippetTemplate('${secret}',false),'$\\{secret\\}');
});
test('ratio controls preserve other attributes and native source', () => {
  assert.equal(ratioLine(':::: columns','2:1'),':::: columns 2:1');
  assert.equal(ratioLine('::: {.columns #id ratio="1:1"}','1:2'),'::: {.columns #id ratio="1:2"}');
  assert.equal(ratioLine('#+begin_columns :ratio "1:1"','2:1',true),'#+begin_columns :ratio "2:1"');
});
test('Org examples remain opaque, including misleading block ends', () => {
  const source = '#+begin_src text\n#+end_columns\n/takeaway\n#+end_src\n#+begin_columns :ratio "2:1"\n#+begin_region :title "A"\nA\n#+end_region\n#+end_columns';
  const parsed = structure(source,true);
  assert.ok(parsed.literals.some(l=>l.from<source.indexOf('/takeaway')&&l.to>source.indexOf('/takeaway')));
  assert.ok(parsed.blocks.some(b=>b.role==='columns'));
});
test('takeaway source labels exclude code examples', () => {
  const parsed = structure('> [!TAKEAWAY]\n> A\n\n```md\n> [!TAKEAWAY]\n> B\n```');
  assert.equal(parsed.blocks.filter(b=>b.syntax==='callout').length,1);
});

test('a picked recipe lands in a sensible place wherever the cursor is', async () => {
  const {placeInsertion} = await import('../src/insertions.mjs');
  const apply = (source, change) => source.slice(0, change.from) + change.insert + source.slice(change.to);
  const deck = '---\ntitle: T\nslide-layout: structured\n---\n\n# S\n\n## One\n### Claim one\n\nFirst point.\n\n```text\ncode\n```\n\n## Two\n\nSecond point.\n';
  const slide = {group: 'slide', markdown: '## New\n\n- Point.\n'}, part = {group: 'part', markdown: ':::: columns\n#### A\nx\n\n#### B\ny\n::::\n'};
  const at = text => deck.indexOf(text);
  // New slides follow the slide being edited; from the top of the file they are appended.
  assert.match(apply(deck, placeInsertion(deck, at('First point'), 'slide', slide)), /```\n\n## New\n\n- Point\.\n\n## Two/);
  assert.ok(apply(deck, placeInsertion(deck, 0, 'slide', slide)).endsWith('Second point.\n\n## New\n\n- Point.\n'));
  assert.match(apply(deck, placeInsertion(deck, at('# S'), 'slide', slide)), /# S\n\n## New\n\n- Point\.\n\n## One/);
  // Parts finish the paragraph, never split a title from its claim, and never land in code or settings.
  assert.match(apply(deck, placeInsertion(deck, at('First point') + 3, 'columns', part)), /First point\.\n\n:::: columns[\s\S]*::::\n\n```text/);
  assert.match(apply(deck, placeInsertion(deck, at('## One') + 2, 'columns', part)), /### Claim one\n\n:::: columns[\s\S]*::::\n\nFirst point/);
  assert.match(apply(deck, placeInsertion(deck, at('code'), 'columns', part)), /```\n\n:::: columns[\s\S]*::::\n\n## Two/);
  assert.match(apply(deck, placeInsertion(deck, 5, 'columns', part)), /```\n\n:::: columns[\s\S]*::::\n\n## Two/);
  const blank = deck.replace('First point.\n\n', 'First point.\n\n\n');
  assert.match(apply(blank, placeInsertion(blank, blank.indexOf('First point.') + 14, 'columns', part)), /First point\.\n\n:::: columns[\s\S]*::::\n\n```text/);
  // Foot-of-slide parts go to the end of the slide; a second claim or takeaway is never created.
  const takeaway = {group: 'part', markdown: '> [!TAKEAWAY]\n> Key takeaway.\n'};
  const once = apply(deck, placeInsertion(deck, at('## One'), 'takeaway', takeaway));
  assert.match(once, /```\n\n> \[!TAKEAWAY\]\n> Key takeaway\.\n\n## Two/);
  const again = placeInsertion(once, once.indexOf('## One'), 'takeaway', takeaway);
  assert.equal(again.insert, undefined);
  assert.equal(once.slice(again.select.from, again.select.to), 'Key takeaway.');
  assert.equal(deck.slice(...Object.values(placeInsertion(deck, at('First'), 'claim', {group: 'part', markdown: '### Main claim\n'}).select)), 'Claim one');
  const claimed = placeInsertion(deck, at('Second'), 'claim', {group: 'part', markdown: '### Main claim\n'});
  assert.match(apply(deck, claimed), /## Two\n### Main claim\n\nSecond point/);
  assert.equal(apply(deck, claimed).slice(claimed.select.from, claimed.select.to), 'Main claim');
  // An open block would swallow the insertion; say so instead of guessing.
  assert.throws(() => placeInsertion(deck.replace('First point.', ':::: columns\nFirst point.'), 0, 'slide', slide), /not closed/);
  // Every result still passes the check.
  const {checkDeck} = await import('../src/check.mjs');
  for (const position of [0, 5, at('# S'), at('## One') + 2, at('First point') + 3, at('code'), at('Second'), deck.length])
    for (const [name, recipe] of [['slide', slide], ['columns', part], ['takeaway', takeaway]]) {
      const change = placeInsertion(deck, position, name, recipe);
      assert.deepEqual(checkDeck(apply(deck, change)).filter(found => found.severity === 'problem'), [], `${name} at ${position}`);
    }
});

test('Add accepts shorter closing fences that Check and the renderer accept', async () => {
  const {placeInsertion} = await import('../src/insertions.mjs');
  const {checkDeck} = await import('../src/check.mjs');
  const source = '---\nslide-layout: structured\n---\n\n## One\n\n:::: columns\n#### L\nLeft.\n\n#### R\nRight.\n:::\n\n## Two\n\nBody.\n';
  assert.deepEqual(checkDeck(source), []);
  const recipe = {group: 'part', markdown: '> [!TAKEAWAY]\n> Conclusion.\n'};
  const change = placeInsertion(source, source.indexOf('Left.'), 'takeaway', recipe);
  const inserted = source.slice(0, change.from) + change.insert + source.slice(change.to);
  assert.match(inserted, /Right\.\n:::\n\n> \[!TAKEAWAY\]\n> Conclusion\.\n\n## Two/);
  assert.deepEqual(checkDeck(inserted), []);
});
