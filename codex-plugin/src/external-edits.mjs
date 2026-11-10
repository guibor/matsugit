// Two writers, one file: the author types in the workspace (and autosaves)
// while an agent or another editor writes the same file. These pure helpers
// decide which version the other writer started from, and turn a new text into
// small editor changes so the cursor, selection and undo history survive.
import {diffIndices} from 'node-diff3';

const lines = text => text.split(/(?<=\n)/);
function hunks(a, b) {
  // Trim what both share first; the diff then only sees the changed middle.
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length, endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) { endA--; endB--; }
  const middleA = a.slice(start, endA), middleB = b.slice(start, endB);
  if (!middleA.length && !middleB.length) return [];
  // Very large rewrites are replaced as one block rather than diffed line by line.
  if (middleA.length * middleB.length > 4_000_000) return [{at: start, remove: middleA.length, add: middleB}];
  return diffIndices(middleA, middleB).map(item => ({at: start + item.buffer1[0], remove: item.buffer1[1], add: item.buffer2Content}));
}

// Editor changes ({from, to, insert}, offsets in `from`) that turn one text into another.
export function textChanges(from, to) {
  if (from === to) return [];
  const a = lines(from), b = lines(to), offsets = [0];
  for (const line of a) offsets.push(offsets.at(-1) + line.length);
  return hunks(a, b).map(hunk => ({from: offsets[hunk.at], to: offsets[hunk.at + hunk.remove], insert: hunk.add.join('')}));
}

// How many lines differ between two texts.
export function distance(a, b) {
  return hunks(lines(a), lines(b)).reduce((sum, hunk) => sum + hunk.remove + hunk.add.length, 0);
}

// Which of our recent saved versions did the incoming file start from? A writer
// that read the file a minute ago and writes it back whole "undoes" everything
// typed since. Its text is then closest to the version it read, not to the
// latest one. Candidates are newest first; ties go to the newest, so an edit
// made on the current file is never mistaken for a stale one.
export function closestAncestor(candidates, incoming) {
  let best = 0, least = Infinity;
  candidates.forEach((candidate, index) => {
    const value = distance(candidate, incoming);
    if (value < least) { least = value; best = index; }
  });
  return best;
}
