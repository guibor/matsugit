import {diff3Merge} from 'node-diff3';

// Keep line terminators and trailing-newline intent; never split on whitespace.
const lines = text => text.match(/[^\n]*\n|[^\n]+$/g) || [];
export function mergePlan(base, local, incoming) {
  const segments = diff3Merge(lines(local), lines(base), lines(incoming),
    {excludeFalseConflicts: true}).map(region => region.ok
      ? {text: region.ok.join('')}
      : {base: region.conflict.o.join(''), local: region.conflict.a.join(''),
        incoming: region.conflict.b.join(''), line: region.conflict.oIndex + 1});
  return {segments, conflicts: segments.filter(segment => !('text' in segment)).length};
}
