import {test} from 'node:test';
import assert from 'node:assert/strict';
import {structure} from '../src/structure.mjs';
import {placeInsertion} from '../src/insertions.mjs';

const marker = '<!-- matsugit:export-end -->';
test('export separator is top-level only and keeps working material editable', () => {
  const text = `## Published\n\nText.\n\n${marker}\n\n## Working\n\nDraft.\n`;
  const model = structure(text);
  assert.equal(model.exportEnd.from, text.indexOf(marker));
  assert.equal(model.headings.length, 2);
  for (const example of [`\`\`\`html\n${marker}\n\`\`\``, `    ${marker}`, `> ${marker}`,
    `::: notes\n${marker}\n:::`, `A literal \`${marker}\`.`, `<!-- example\n${marker}\n-->`,
    `---\nexample: |\n  ${marker}\n---\n`]) assert.equal(structure(example).exportEnd, undefined, example);
  const recipe = {group:'part',markdown:marker};
  assert.deepEqual(placeInsertion(text, 0, 'export-end', recipe).select, model.exportEnd);
  const before = '## Published\n\nText.\n\n## Working\n\nDraft.\n';
  const edit = placeInsertion(before, 0, 'export-end', recipe);
  const result = before.slice(0,edit.from)+edit.insert+before.slice(edit.to);
  assert(result.indexOf(marker)<result.indexOf('## Working'));
});
