// File contents do not identify the other writer's parent revision. Retain
// plausible bases and require review when they disagree, rather than guessing.
import {diffIndices} from 'node-diff3';
import {mergeResult} from './merge-result.mjs';

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

export function savedEditHistory({limit = 20, maxBytes = 8 * 1024 * 1024} = {}) {
  let versions = [], bytes = 0, incomplete = false;
  return {
    remember(text) {
      if (versions.some(item => item.text === text)) return;
      const size = new TextEncoder().encode(text).length;
      versions.unshift({text, size}); bytes += size;
      while (versions.length > limit || bytes > maxBytes) {
        bytes -= versions.pop().size; incomplete = true;
      }
    },
    get versions() { return versions.map(item => item.text); },
    get incomplete() { return incomplete; },
    get pending() { return incomplete || versions.length > 0; },
    rebase(texts) {
      versions = []; bytes = 0;
      for (const text of [...texts].reverse()) this.remember(text);
    },
    clear() { versions = []; bytes = 0; incomplete = false; },
  };
}

export function wholeFileReview(plan, base, local, incoming) {
  return {...plan, conflicts: 1, segments: [{base, local, incoming, line: 1}]};
}

// merge runs off the UI thread. Only unanimous, conflict-free results may be
// applied automatically. An alternative base is a review proposal, not proof
// that the incoming writer used it. Missing history also requires review.
export async function planExternalEdit({base, local, incoming, history, merge}) {
  const current = await merge(base, local, incoming);
  if (history.incomplete) return {review: true, ambiguous: true, whole: true, base,
    plan: wholeFileReview(current, base, local, incoming)};
  if (current.conflicts) return {review: true, base, plan: current};
  const text = mergeResult(current);
  const versions = [];
  for (const candidate of history.versions) {
    if (candidate === base) continue;
    // Compare saved text separately from the still-unsaved keystrokes. Otherwise
    // extending a saved sentence looks like two competing historical insertions.
    const protectedText = await merge(candidate, base, incoming);
    if (protectedText.conflicts || mergeResult(protectedText) !== incoming)
      return {review: true, ambiguous: true, base: candidate, plan: await merge(candidate, local, incoming)};
    // Carry accepted external changes into the pre-save bases, without carrying
    // the author's saved edits. Later targeted edits then stay independent.
    const rebased = await merge(base, candidate, incoming);
    if (rebased.conflicts) return {review: true, ambiguous: true, whole: true, base,
      plan: wholeFileReview(current, base, local, incoming)};
    versions.push(mergeResult(rebased));
  }
  return {review: false, base, plan: current, text, versions};
}
