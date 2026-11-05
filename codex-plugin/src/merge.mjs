import {diff3Merge, diffPatch} from 'node-diff3';

// Keep line terminators and trailing-newline intent; never split on whitespace.
const lines = text => text.match(/[^\n]*\n|[^\n]+$/g) || [];
export function mergePlan(base, local, incoming) {
  const segments = diff3Merge(lines(local), lines(base), lines(incoming),
    {excludeFalseConflicts: true}).map(region => region.ok
      ? {text: region.ok.join('')}
      : {base: region.conflict.o.join(''), local: region.conflict.a.join(''),
        incoming: region.conflict.b.join(''), line: region.conflict.oIndex + 1});
  const external = [];
  const original = lines(base), changed = lines(incoming);
  let cursor = 0, offset = 0;
  for (const patch of diffPatch(original, changed)) {
    const before = patch.buffer1, after = patch.buffer2;
    const stable = original.slice(cursor, before.offset).join('');
    external.push({text:stable}); offset += stable.length;
    external.push({before:before.chunk.join(''), after:after.chunk.join(''),
      line:before.offset + 1, offset});
    offset += before.chunk.join('').length;
    cursor = before.offset + before.length;
  }
  external.push({text:original.slice(cursor).join('')});
  return {segments, external, conflicts: segments.filter(segment => !('text' in segment)).length};
}
