import {test} from 'node:test';
import assert from 'node:assert/strict';
import {structure, headingTargets, headingKey, slideBoundaries} from '../src/structure.mjs';
import {roleDescription} from '../src/role-help.mjs';
import {preferences} from '../src/recovery.mjs';

test('leading blank / BOM frontmatter and HTML examples never become semantic structure', () => {
  for (const prefix of ['\n', '\uFEFF\n \t\r\n', '']) {
    const source = prefix + '---\ntitle: Review\nslide-layout: structured\n---\n\n'
      + '<!--\n# Section example\n## Slide example\n### Claim example\n'
      + '  ::: takeaway: optional conclusion\n-->\n\n'
      + '# Real section\n## Real slide\n### Real claim\n\n'
      + '::: takeaway\nKeep the evidence.\n:::\n';
    const p = structure(source);
    assert.deepEqual(p.headings.map(h => h.label),['Real section','Real slide','Real claim']);
    assert.equal(p.unfinished.length,0);
    assert.deepEqual(p.blocks.map(b => b.role),['takeaway']);
    assert.deepEqual(slideBoundaries(p),[source.indexOf('## Real slide')]);
    assert.equal(p.markers.filter(m => m.role === 'takeaway').length,2);
  }
});

test('real Setext headings after a comment stay editable and inline comments do not hide later slides', () => {
  const s = '<!--\n::: claim example\n-->\n\nTopic\n=====\n\nSlide\n-----\n\nText <!-- comment -->\n\n## Next\n';
  assert.deepEqual(structure(s).headings.map(h => h.label),['Topic','Slide','Next']);
  assert.equal(structure(s).unfinished.length,0);
});

test('navigation follows visible headings, not YAML, code or hidden requests', () => {
  const source = '---\ntitle: Deck\n---\n# Section\n## **A** [link](https://example.test) `claim` {#stable}\n### Detail\n\n```md\n## Example\n::: takeaway\n```\n\n:::: {.agent-comment #review-one}\n## Hidden\n::::\n\n## A link claim\n';
  const parsed = structure(source);
  assert.deepEqual(parsed.headings.map(h => [h.level, h.key, h.occurrence]), [
    [1, 'section', 0], [2, 'a link claim', 0], [3, 'detail', 0], [2, 'a link claim', 1],
  ]);
  assert.equal(parsed.literals[0].from, 0);
  assert.deepEqual(parsed.blocks.map(b => b.role), ['agent-comment']);
  assert.deepEqual(headingTargets(parsed.headings, source.indexOf('### Detail') + 5).map(h => h.level), [3, 2, 1]);
  assert.deepEqual(headingTargets(parsed.headings, 0), []);
  assert.deepEqual(headingTargets(parsed.headings, source.indexOf('# Section')).map(h => h.level), [1, 2]);
});

test('nested block handles and Setext titles keep exact source positions', () => {
  const source = 'Topic\n=====\n\nSlide\n-----\n\n:::: columns\n::: takeaway\nResult\n:::\n::::\n';
  const parsed = structure(source);
  assert.deepEqual(parsed.headings.map(h => h.label), ['Topic', 'Slide']);
  assert.deepEqual(parsed.blocks.map(b => b.role), ['takeaway', 'columns']);
  assert.equal(source.slice(parsed.blocks[1].from, parsed.blocks[1].startEnd), ':::: columns');
  assert.equal(parsed.markers.filter(m => m.closing).length, 2);
  assert.equal(headingKey('Caf\u00e9: \u05e9\u05dc\u05d5\u05dd'), 'caf\u00e9 \u05e9\u05dc\u05d5\u05dd');
});

test('Org source blocks and hidden comments do not create slide targets', () => {
  const source = '* Topic\n** [[https://example.test][Slide]]\n#+begin_src text\n** Fake\n#+end_src\n#+begin_agent-comment\n** Hidden\n#+end_agent-comment\n*** Claim\n';
  assert.deepEqual(structure(source, true).headings.map(h => h.key), ['topic', 'slide', 'claim']);
});

test('source slide guides ignore YAML, code, quotes, tables and nested layout blocks', () => {
  const source = '---\ntitle: Deck\n---\n# Topic\n## Slide one\n### Claim\n\nBody\n\n---\n\nContinued\n\n'
    + '> ## Quoted heading\n> ---\n\n```md\n## Code\n---\n```\n\n'
    + ':::: notes\n## Note\n\n---\n::::\n\n| A | B |\n| --- | --- |\n| a | b |\n\n'
    + 'Slide two\n---------\n';
  assert.deepEqual(slideBoundaries(structure(source)), [source.indexOf('## Slide one'), source.indexOf('---\n\nContinued'), source.indexOf('Slide two')]);
});

test('Org source slide guides exclude block contents', () => {
  const source = '* Topic\n** Slide\n*** Claim\n\n-----\n\n#+begin_src text\n** Fake\n-----\n#+end_src\n';
  assert.deepEqual(slideBoundaries(structure(source, true)), [source.indexOf('** Slide'), source.indexOf('-----')]);
});

test('role explanations distinguish titles, claims and boundaries', () => {
  assert.equal(roleDescription('Slide').label, 'Slide title');
  assert.equal(roleDescription('Claim').syntax, 'H3');
  assert.equal(roleDescription('columns', true).label, 'End of Columns');
  assert.equal(roleDescription('custom-element').label, 'custom element');
});

test('slide-separator preference is explicit and survives recovery sanitizing', () => {
  assert.equal(preferences().slideSeparators, false);
  assert.equal(preferences({slideSeparators: true}).slideSeparators, true);
  assert.equal(preferences({slideSeparators: 'true'}).slideSeparators, false);
});
