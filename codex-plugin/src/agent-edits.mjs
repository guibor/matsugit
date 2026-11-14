import {randomUUID} from 'node:crypto';
import {checkedPath, checkedText, readDocument, saveDocument} from './store.mjs';
import {completeStoryModel} from './story-model.mjs';

export const MAX_SLIDE = 64 * 1024;
const MAX_SNAPSHOTS = 128, TTL = 10 * 60 * 1000;
const stale = () => ({outcome:'conflict', message:'The saved document changed. Read the slide again and review the new text before editing. Nothing was written.'});

function selected(source, slide, org) {
  const model = completeStoryModel(source, org);
  const node = model.slides[slide - 1];
  if (!Number.isInteger(slide) || slide < 1 || !node) throw Error('Choose an existing slide number from Story.');
  const text = source.slice(node.from, node.end);
  if (Buffer.byteLength(text) > MAX_SLIDE) throw Error('This slide exceeds the 64 KiB edit limit. Split it before requesting a scoped edit.');
  return {model, node, text};
}

// All replacements refer to the same snapshot, never the result of an earlier
// replacement. Reject ambiguity instead of guessing which repeated text to edit.
export function patchSlide(source, slide, edits, org = false) {
  const {model, node, text} = selected(source, slide, org);
  if (!Array.isArray(edits) || !edits.length || edits.length > 32) throw Error('Provide between 1 and 32 exact text replacements.');
  let size = 0;
  const changes = edits.map(edit => {
    if (!edit || typeof edit.old !== 'string' || typeof edit.new !== 'string' || !edit.old.length)
      throw Error('Each edit needs nonempty old text and replacement new text.');
    checkedText(edit.old); checkedText(edit.new);
    size += Buffer.byteLength(edit.old) + Buffer.byteLength(edit.new);
    if (size > 2 * MAX_SLIDE) throw Error('Slide replacements exceed the 128 KiB edit limit.');
    const from = text.indexOf(edit.old);
    if (from < 0 || text.indexOf(edit.old, from + 1) >= 0)
      throw Error('Old text must occur exactly once in this slide. Include more surrounding text; nothing was written.');
    return {from, to:from + edit.old.length, insert:edit.new};
  }).sort((a,b) => a.from - b.from);
  for (let i = 1; i < changes.length; i++) if (changes[i].from < changes[i-1].to)
    throw Error('The replacements overlap. Use separate, non-overlapping passages.');
  let next = text;
  for (const change of [...changes].reverse()) next = next.slice(0,change.from) + change.insert + next.slice(change.to);
  if (Buffer.byteLength(next) > MAX_SLIDE) throw Error('The updated slide exceeds the 64 KiB edit limit.');
  const output = checkedText(source.slice(0,node.from) + next + source.slice(node.end));
  const after = completeStoryModel(output,org), target = after.slides[slide-1], delta = next.length-text.length;
  const neighbors = m => m.nodes.filter(n => n.kind !== 'claim' && n !== m.slides[slide-1]);
  const beforeNeighbors = neighbors(model), afterNeighbors = neighbors(after);
  if (after.unfinished.length || after.slides.length !== model.slides.length || !target
      || target.from !== node.from || target.end !== node.end + delta
      || beforeNeighbors.length !== afterNeighbors.length
      || beforeNeighbors.some((n,i) => {
        const other = afterNeighbors[i], offset = n.from >= node.end ? delta : 0;
        return n.kind !== other.kind || n.label !== other.label || n.from + offset !== other.from;
      })) throw Error('This edit changes slide boundaries or surrounding sections. Use Story for structural changes; nothing was written.');
  return {text:output, source:next, replacements:changes.length};
}

export class AgentEdits {
  snapshots = new Map();
  constructor({now = () => Date.now(), save = saveDocument} = {}) { this.save = save; this.now = now; }
  prune() { for (const [id,item] of this.snapshots) if (this.now() - item.created >= TTL) this.snapshots.delete(id); }
  read(file, slide, etag) {
    this.prune();
    const target = checkedPath(file), current = readDocument(target);
    if (etag && current.etag !== etag) return stale();
    const org = target.toLowerCase().endsWith('.org');
    const {model,node,text} = selected(current.text,slide,org);
    if (this.snapshots.size >= MAX_SNAPSHOTS) throw Error('Too many pending slide edits. Finish an edit or wait for its snapshot to expire.');
    const id = randomUUID();
    this.snapshots.set(id,{created:this.now(), path:target, etag:current.etag, slide, org});
    return {edit_id:id, etag:current.etag, path:target, slide, slides:model.slides.length,
      title:node.label, section:node.parent?.label || '', source:text,
      format:org ? 'org' : 'markdown', readOnly:current.readOnly, expires_in_seconds:TTL/1000,
      scope:'Saved file only. Unsaved workspace typing is separate and will be combined or offered for review.'};
  }
  edit(id, edits, previewOnly = false) {
    this.prune();
    const item = this.snapshots.get(id);
    if (!item) throw Error('Edit snapshot expired or already used. Read the slide again; no document was changed.');
    // readDocument refuses replaced symlinks too. A Share relocation needs a new
    // explicit read at its new path, not a silently redirected write.
    const current = readDocument(item.path);
    if (current.etag !== item.etag) { this.snapshots.delete(id); return stale(); }
    const patch = patchSlide(current.text,item.slide,edits,item.org);
    if (previewOnly) return {outcome:'preview', path:item.path, slide:item.slide, etag:item.etag, source:patch.source};
    const finish = saved => {
      if (saved.outcome === 'saved' || saved.outcome === 'conflict') this.snapshots.delete(id);
      return {...saved, path:item.path, slide:item.slide, replacements:patch.replacements,
        ...(saved.outcome === 'conflict' ? {message:stale().message} : {})};
    };
    const saved = this.save(item.path,patch.text,item.etag);
    return saved?.then ? saved.then(finish) : finish(saved);
  }
}
