import {test} from 'node:test';
import assert from 'node:assert/strict';
import {destinations, sectionReference} from '../src/section-reference.mjs';

const source = '## Decision\n\nEvidence here.\n\n## Appendix {.collapsible}\n\nMethod.\n\n## Appendix\n\nOther.\n\n<!-- matsugit:export-end -->\n\n## Private\n';
function insert(text, at, heading) {
  const {changes,end} = sectionReference(text, at, heading);
  for (const {from,insert} of changes.reverse()) text = text.slice(0,from) + insert + text.slice(from);
  return {text,end};
}
test('linking selected prose is one draft edit with the caret after the link', () => {
  for (const [label,title] of [['Evidence','Appendix'], ['Other','Decision']]) {
    const at = source.indexOf(label), heading = source.indexOf('## '+title);
    const {changes,end} = sectionReference(source,at,heading,label);
    let text = source;
    for (const {from,to=from,insert} of changes.reverse()) text = text.slice(0,from)+insert+text.slice(to);
    assert.ok(text.slice(0,end).endsWith('['+label+'](#detail-'+title.toLowerCase()+')'));
    assert.ok(text.includes('{#detail-'+title.toLowerCase()));
    assert.throws(() => sectionReference(source,at,heading,'wrong selection'));
  }
});
test('one draft transaction creates a numbered reference and preserves target classes', () => {
  assert.deepEqual(destinations(source).map(h=>h.label), ['Decision','Appendix','Appendix']);
  const {text,end} = insert(source, source.indexOf('here.')+5, source.indexOf('## Appendix'));
  assert.ok(text.slice(0,end).endsWith('[\\[1\\]](#detail-appendix)'));
  assert.ok(text.includes('## Appendix {#detail-appendix .collapsible}'));
  const again = insert(text,text.indexOf('Other.')+6,text.indexOf('## Appendix'));
  assert.ok(again.text.slice(0,again.end).endsWith('[\\[1\\]](#detail-appendix)'));
  const second = insert(text,text.indexOf('Other.')+6,text.lastIndexOf('## Appendix'));
  assert.ok(second.text.slice(0,second.end).endsWith('[\\[2\\]](#detail-appendix-2)'));
});
