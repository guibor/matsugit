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
