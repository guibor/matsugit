import {storyModel} from './story-model.mjs';
import {diffIndices} from 'node-diff3';
import {parser} from '@lezer/markdown';

function readable(source) {
  const omit = [];
  parser.parse(source).iterate({enter(node) {
    if (['FencedCode','CodeBlock'].includes(node.name)) return false;
    if (['HeaderMark','EmphasisMark','LinkMark','CodeMark'].includes(node.name)) omit.push([node.from,node.to]);
  }});
  let result = '', at = 0;
  for (const [from,to] of omit) { if (from >= at) { result += source.slice(at,from); at = to; } }
  return (result + source.slice(at)).trim();
}

export function wordChanges(before, after, org = false) {
  const a = (org ? before : readable(before)).match(/\s+|\S+/g) || [];
  const b = (org ? after : readable(after)).match(/\s+|\S+/g) || [];
  if (a.length*b.length > 500000) return [{before:a.join(''),after:b.join('')}];
  let at = 0;
  const parts = [];
  for (const hunk of diffIndices(a,b)) {
    parts.push({text:a.slice(at,hunk.buffer1[0]).join('')});
    parts.push({before:hunk.buffer1Content.join(''),after:hunk.buffer2Content.join('')});
    at = hunk.buffer1[0]+hunk.buffer1[1];
  }
  parts.push({text:a.slice(at).join('')});
  return parts;
}

export function slideDiff(before, after, org = false) {
  const prepare = text => storyModel(text,org).slides.map((slide,index) => ({...slide,index,
    text:text.slice(slide.from,slide.end),body:text.slice(slide.to,slide.end).trim()}));
  const old = prepare(before), now = prepare(after), matches = new Map(), used = new Set();
  // Exact matches, then unchanged bodies (retitles), then unique titles. Never
  // pair duplicate headings by ordinal: insertions and moves change that ordinal.
  for (const key of ['text','body','label']) {
    const left = new Map(), right = new Map();
    for (const slide of old) if (!matches.has(slide.index) && slide[key]) left.set(slide[key], [...(left.get(slide[key]) || []),slide]);
    for (const slide of now) if (!used.has(slide.index) && slide[key]) right.set(slide[key], [...(right.get(slide[key]) || []),slide]);
    for (const [value,items] of left) if (items.length === 1 && right.get(value)?.length === 1) {
      matches.set(items[0].index,right.get(value)[0]); used.add(right.get(value)[0].index);
    }
  }
  const changes = [];
  for (const slide of old) {
    const match = matches.get(slide.index);
    if (!match) changes.push({kind:'Removed',title:slide.label,before:slide.text,after:''});
    else {
      const types = [];
      if (slide.label !== match.label) types.push('Retitled');
      if (slide.body !== match.body) types.push('Edited');
      if (slide.index !== match.index) types.push('Moved');
      if (types.length) changes.push({kind:types.join(', '),title:match.label,before:slide.text,after:match.text});
    }
  }
  for (const slide of now) if (!used.has(slide.index)) changes.push({kind:'Added',title:slide.label,before:'',after:slide.text});
  return changes;
}
