import {StateEffect, StateField} from '@codemirror/state';
import {Decoration, EditorView, ViewPlugin, WidgetType} from '@codemirror/view';
import {syntaxTree} from '@codemirror/language';
import {parser, GFM} from '@lezer/markdown';
import {createElement, Pencil} from 'lucide';

export const visualMode = StateEffect.define();
const md = parser.configure(GFM);
const cache = new WeakMap();

export function tableRanges(source, tree = md.parse(source)) {
  const tables = [], ignored = [];
  const frontmatter = /^---[ \t]*\r?\n[\s\S]*?\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/.exec(source)?.[0].length || 0;
  tree.iterate({enter(node) {
    if (node.from < frontmatter && node.name !== 'Document') return false;
    if (['FencedCode','CodeBlock','HTMLBlock'].includes(node.name)) {
      // Lezer reuses its traversal cursor; retain immutable offsets, not the cursor.
      ignored.push({from:node.from,to:node.to}); return false;
    }
    if (node.name !== 'Table') return;
    const rows = [];
    for (let row = node.node.firstChild; row; row = row.nextSibling) {
      if (!['TableHeader','TableRow'].includes(row.name)) continue;
      const cells = [];
      for (let cell = row.firstChild; cell; cell = cell.nextSibling) if (cell.name === 'TableCell') cells.push(source.slice(cell.from, cell.to));
      rows.push(cells);
    }
    if (rows.length <= 250 && rows.reduce((sum, row) => sum + row.length, 0) <= 1000) {
      const delimiter=source.slice(node.from,node.to).split('\n')[1];
      const alignments=(delimiter.match(/:?-+:?/g) || []).map(value=>value.startsWith(':') ? value.endsWith(':')?'center':'left' : value.endsWith(':')?'right':null);
      tables.push({from:node.from, to:node.to, source:source.slice(node.from,node.to), rows, alignments, kind:'pipe'});
    }
    return false;
  }});
  // Grid tables are a Pandoc extension. Only identify a bounded candidate here;
  // the existing converter validates it before any HTML or editing is offered.
  const lines = source.split('\n');
  let offset = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i], from = offset;
    offset += line.length + 1;
    if (from < frontmatter || !/^\+(?:[-=:]+\+)+\s*$/.test(line) ||
        ignored.some(n => from >= n.from && from < n.to) || tables.some(t => from >= t.from && from < t.to)) continue;
    let end = from + line.length, j = i + 1, rows = 0;
    for (; j < lines.length && /^[|+]/.test(lines[j]); j++) {
      end += lines[j].length + 1;
      if (lines[j].startsWith('|')) rows++;
    }
    if (rows && rows <= 500 && /^\+(?:[-=:]+\+)+\s*$/.test(lines[j-1]) && end-from <= 1024*1024) {
      tables.push({from,to:end,source:source.slice(from,end),kind:'grid'});
      for (let k = i + 1; k < j; k++) offset += lines[k].length + 1;
      i = j - 1;
    }
  }
  return tables.sort((a,b)=>a.from-b.from);
}

export function safeTableDOM(html) {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  const allowed = new Set(['TABLE','THEAD','TBODY','TFOOT','TR','TH','TD','P','STRONG','B','EM','I','S','DEL','CODE','A','BR','UL','OL','LI']);
  const copy = node => {
    if (node.nodeType === 3) return document.createTextNode(node.textContent);
    if (node.nodeType !== 1 || !allowed.has(node.tagName)) return document.createTextNode('');
    const el = document.createElement(node.tagName.toLowerCase());
    for (const key of ['rowspan','colspan','start']) {
      const value = node.getAttribute(key);
      if (/^[1-9]\d{0,2}$/.test(value || '')) el.setAttribute(key,value);
    }
    if (['left','center','right'].includes(node.style.textAlign)) el.style.textAlign = node.style.textAlign;
    // Links are labels in the source editor; no navigation or resource loading.
    if (node.tagName === 'A') el.title = node.getAttribute('href') || '';
    for (const child of node.childNodes) el.append(copy(child));
    return el;
  };
  return parsed.querySelector('table') ? copy(parsed.querySelector('table')) : document.createTextNode('');
}

function inlineDOM(source) {
  const fragment = document.createDocumentFragment();
  const visit = (node, parent) => {
    if (['EmphasisMark','CodeMark','LinkMark','LinkTitle','StrikethroughMark'].includes(node.name) ||
        (node.name==='URL' && node.parent?.name==='Link')) return;
    const tag = {StrongEmphasis:'strong',Emphasis:'em',InlineCode:'code',Strikethrough:'s',Link:'span'}[node.name];
    const element = tag ? document.createElement(tag) : parent;
    if (tag) parent.append(element);
    if (node.name === 'Escape') { element.append(document.createTextNode(source.slice(node.from+1,node.to))); return; }
    let at = node.from;
    for (let child=node.firstChild; child; child=child.nextSibling) {
      element.append(document.createTextNode(source.slice(at,child.from))); visit(child,element); at=child.to;
    }
    element.append(document.createTextNode(source.slice(at,node.to)));
  };
  visit(md.parse(source).topNode, fragment);
  return fragment;
}

class Bullet extends WidgetType {
  toDOM() { const el=document.createElement('span'); el.className='ff-visual-bullet'; el.textContent='\u2022'; return el; }
  ignoreEvent() { return false; }
}

class VisualTable extends WidgetType {
  constructor(table, actions) { super(); this.table=table; this.actions=actions; }
  eq(other) { return this.table.source === other.table.source && this.table.from === other.table.from; }
  toDOM(view) {
    const table=this.table, root=document.createElement('div'); root.className='ff-visual-table';
    root.setAttribute('contenteditable','false');
    const toolbar=document.createElement('div'), edit=document.createElement('button');
    edit.title='Edit table'; edit.setAttribute('aria-label','Edit table'); edit.append(createElement(Pencil));
    edit.disabled=!this.actions.enabled();
    const open=cell=>{if(this.actions.enabled())this.actions.open(table,{mount:root,cell,measure:()=>view.requestMeasure()});};
    edit.onclick=()=>open(); toolbar.append(edit); root.append(toolbar);
    const body=document.createElement('div'); body.className='ff-table-scroll'; root.append(body);
    if (table.rows) {
      const el=document.createElement('table');
      table.rows.forEach((row,i)=>{const tr=el.insertRow();row.forEach((value,c)=>{const cell=document.createElement(i?'td':'th');cell.style.textAlign=table.alignments[c] || '';cell.append(inlineDOM(value));tr.append(cell);});});
      body.append(el);
    } else {
      const label=document.createElement('pre'); label.textContent=table.source; body.append(label);
      this.actions.preview(table.source).then(html=>{
        if (!root.isConnected) return;
        body.replaceChildren(safeTableDOM(html)); view.requestMeasure();
      }).catch(error=>{edit.title='Edit table: '+error.message;});
    }
    body.onclick=event=>{
      const cell=event.target.closest('th,td');
      if(cell)open({row:cell.parentElement.rowIndex,column:cell.cellIndex});
    };
    return root;
  }
  destroy(root) { this.actions.detach?.(root); }
  ignoreEvent() { return true; }
}

export function visualExtensions(actions) {
  const model = state => {
    const tree=syntaxTree(state), old=cache.get(state.doc);
    if (old?.tree===tree) return old;
    const source=state.doc.toString(), tables=tableRanges(source,tree);
    const frontmatter=/^---[ \t]*\r?\n[\s\S]*?\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/.exec(source)?.[0].length || 0;
    const result={tree,source,tables,frontmatter};cache.set(state.doc,result);return result;
  };
  const build = state => {
    if (actions.isOrg()) return {decorations:Decoration.none,atomic:Decoration.none};
    const {tree,tables,frontmatter}=model(state), decorations=[];
    for(let line=1;line<=state.doc.lines && state.doc.line(line).from<frontmatter;line++)
      decorations.push(Decoration.line({class:'ff-visual-metadata'}).range(state.doc.line(line).from));
    const active = node => state.selection.ranges.some(s=>s.from<=node.to && s.to>=node.from);
    tree.iterate({enter(node) {
      if (node.name==='Document') return;
      if (node.from<frontmatter || ['FencedCode','CodeBlock','HTMLBlock','Image'].includes(node.name)) return false;
      if (tables.some(t=>node.from>=t.from && node.from<t.to)) return false;
      const heading=/^(?:ATX|Setext)Heading([1-6])$/.exec(node.name);
      if (heading) decorations.push(Decoration.line({class:'ff-visual-heading ff-heading-'+heading[1]}).range(state.doc.lineAt(node.from).from));
      const mark={StrongEmphasis:'ff-visual-strong',Emphasis:'ff-visual-em',InlineCode:'ff-visual-code',Strikethrough:'ff-visual-strike',Link:'ff-visual-link'}[node.name];
      if (mark) decorations.push(Decoration.mark({class:mark}).range(node.from,node.to));
      if (['HeaderMark','EmphasisMark','CodeMark','StrikethroughMark','LinkMark','URL','LinkTitle'].includes(node.name)) {
        const parent=node.node.parent;
        // Reveal syntax only in the inline construct currently being edited.
        if (!active(parent) && (node.name!=='URL' || parent.name==='Link'))
          decorations.push(Decoration.replace({}).range(node.from,node.to));
      }
      if (node.name==='ListMark' && !active(node.node.parent) && /^[-+*]$/.test(state.doc.sliceString(node.from,node.to)))
        decorations.push(Decoration.replace({widget:new Bullet()}).range(node.from,node.to));
    }});
    for(const table of tables) decorations.push(Decoration.replace({widget:new VisualTable(table,actions),block:true}).range(table.from,table.to));
    return {decorations:Decoration.set(decorations,true),
      atomic:Decoration.set(decorations.filter(d=>!d.value.spec.class),true)};
  };
  const field=StateField.define({
    create:()=>({enabled:false,decorations:Decoration.none,atomic:Decoration.none}),
    update(value,tr) {
      let enabled=value.enabled;
      for(const effect of tr.effects) if(effect.is(visualMode)) enabled=effect.value;
      return enabled ? {enabled,...build(tr.state)} : {enabled,decorations:Decoration.none,atomic:Decoration.none};
    },
    provide:f=>EditorView.decorations.from(f,v=>v.decorations),
  });
  return [field,EditorView.atomicRanges.of(view=>view.state.field(field).atomic),
    ViewPlugin.fromClass(class {
      constructor(view) { this.updateClass(view); }
      update(update) { this.updateClass(update.view); }
      updateClass(view) { view.dom.classList.toggle('ff-visual',view.state.field(field).enabled && !actions.isOrg()); }
    })];
}
