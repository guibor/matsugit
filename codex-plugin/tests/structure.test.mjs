import {test} from 'node:test';
import assert from 'node:assert/strict';
import {structure, headingTargets, headingKey} from '../src/structure.mjs';

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
