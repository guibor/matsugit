import {EditorState, StateEffect, StateField, Prec} from '@codemirror/state';
import {Decoration, EditorView, ViewPlugin, WidgetType, keymap, showTooltip} from '@codemirror/view';
import {editableHeading, formatProse, headingText} from './prose-edit.mjs';
import {syntaxTree} from '@codemirror/language';
import {parser, GFM} from '@lezer/markdown';
import {createElement, Bold, Italic, Link, Pencil} from 'lucide';
import {structure} from './structure.mjs';
import {columnGroups} from './column-targets.mjs';
import {layoutControl, layoutEditAllowed} from './layout-edit.mjs';

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
      // Lezer has no TableCell node for an empty cell. Its parsed delimiters
      // retain those positions, without treating an escaped pipe as a column.
      const cells = [];
      let start = row.from;
      for (let cell = row.firstChild; cell; cell = cell.nextSibling) if (cell.name === 'TableDelimiter') {
        if (cell.from !== row.from) cells.push(source.slice(start, cell.from).trim());
        start = cell.to;
      }
      if (start < row.to) cells.push(source.slice(start, row.to).trim());
      rows.push(cells);
    }
    if (rows.length <= 250 && rows.length * Math.max(...rows.map(r=>r.length),0) <= 1000) {
      for (const row of rows) while (row.length < rows[0].length) row.push('');
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

// The YAML settings at the top, shown as one line. Clicking it opens the text.
class DeckSettings extends WidgetType {
  constructor(source) { super(); this.source = source; }
  eq(other) { return other.source === this.source; }
  toDOM(view) {
    const values = Object.fromEntries([...this.source.matchAll(/^([A-Za-z][\w-]*):[ \t]*(.*?)[ \t]*$/gm)].map(m => [m[1], m[2].replace(/^(['"])(.*)\1$/, '$2')]));
    const el = document.createElement('button');
    el.type = 'button'; el.className = 'ff-deck-settings';
    const label = document.createElement('strong'); label.textContent = 'Deck settings';
    const summary = document.createElement('span');
    summary.textContent = [values.title && `"${values.title}"`, values['slide-layout'] && `${values['slide-layout']} layout`,
      values['slide-aspect-ratio'], values['slide-section-dividers'] === 'false' && 'no section slides'].filter(Boolean).join(' · ') || 'Title and slide options';
    const edit = document.createElement('span'); edit.className = 'ff-deck-settings-edit'; edit.textContent = 'Edit';
    el.append(label, summary, edit);
    el.title = 'Title and slide options from the top of the file. Click to edit them as text.';
    el.onmousedown = event => event.preventDefault();
    el.onclick = () => { view.dispatch({selection:{anchor:Math.max(0,this.source.indexOf('\n') + 1)}, scrollIntoView:true}); view.focus(); };
    return el;
  }
  ignoreEvent() { return true; }
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

class RenameHeading extends WidgetType {
  toDOM(view) {
    const button=document.createElement('button');
    button.type='button';button.className='ff-rename-heading';
    button.title='Rename heading (F2)';button.setAttribute('aria-label','Rename heading');
    button.append(createElement(Pencil));
    button.onmousedown=e=>e.preventDefault();
    button.onclick=()=>{
      const line=view.state.doc.lineAt(view.posAtDOM(button)), title=headingText(line);
      if (title) view.dispatch({selection:{anchor:title.from,head:title.to}});
      view.focus();
    };
    return button;
  }
}

class ExportBoundary extends WidgetType {
  toDOM() {
    const el = document.createElement('div');
    el.className = 'ff-export-boundary';
    el.textContent = 'Export ends here';
    return el;
  }
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
    const parsed=structure(source);
    const comparisons=parsed.blocks.filter(b=>b.role==='comparison' && b.endFrom!==undefined);
    const optionHeadings=parsed.headings.filter(h=>h.level===4 && comparisons.some(b=>b.startEnd<h.from && h.to<=b.endFrom));
    const result={tree,source,tables,frontmatter,comparisons,optionHeadings,columns:columnGroups(parsed),exportEnd:parsed.exportEnd};cache.set(state.doc,result);return result;
  };
  const build = state => {
    if (actions.isOrg()) return {decorations:Decoration.none,atomic:Decoration.none};
    const {tree,tables,frontmatter,exportEnd,comparisons}=model(state), decorations=[];
    const active = node => state.selection.ranges.some(s=>s.from<=node.to && s.to>=node.from);
    for (const group of model(state).columns) {
      const parts=group.parts, part=parts.find(p=>p.from<=state.selection.main.from && state.selection.main.to<p.end);
      if (!part) continue;
      for (let i=state.doc.lineAt(part.from).number; i<=state.doc.lineAt(part.end-1).number; i++)
        decorations.push(Decoration.line({class:'ff-active-column'}).range(state.doc.line(i).from));
    }
    if (exportEnd && !active(exportEnd))
      decorations.push(Decoration.replace({widget:new ExportBoundary(),block:true}).range(exportEnd.from,exportEnd.to));
    // The settings block reads as one quiet line until the cursor goes into it.
    const settingsEnd = frontmatter ? state.doc.lineAt(Math.max(0, frontmatter - 1)).to : 0;
    if (frontmatter && !active({from:0,to:settingsEnd}))
      decorations.push(Decoration.replace({widget:new DeckSettings(state.doc.sliceString(0,frontmatter)),block:true}).range(0,settingsEnd));
    else for(let line=1;line<=state.doc.lines && state.doc.line(line).from<frontmatter;line++)
      decorations.push(Decoration.line({class:'ff-visual-metadata'}).range(state.doc.line(line).from));
    tree.iterate({enter(node) {
      if (node.name==='Document') return;
      if (node.from<frontmatter || ['FencedCode','CodeBlock','HTMLBlock','Image'].includes(node.name)) return false;
      if (tables.some(t=>node.from>=t.from && node.from<t.to)) return false;
      const heading=/^(?:ATX|Setext)Heading([1-6])$/.exec(node.name);
      if (heading) {
        const line = state.doc.lineAt(node.from), title = headingText(line);
        decorations.push(Decoration.line({class:'ff-visual-heading ff-heading-'+heading[1],
          attributes:{title:'Double-click or press F2 to rename this heading'}}).range(line.from));
        if (node.name.startsWith('ATX') && title) {
          decorations.push(Decoration.replace({}).range(line.from,title.from));
          if (title.to < line.to) decorations.push(Decoration.replace({}).range(title.to,line.to));
          if (active(node)) decorations.push(Decoration.widget({widget:new RenameHeading(),side:1}).range(line.to));
        }
      }
      const mark={StrongEmphasis:'ff-visual-strong',Emphasis:'ff-visual-em',InlineCode:'ff-visual-code',Strikethrough:'ff-visual-strike',Link:'ff-visual-link'}[node.name];
      if (node.name==='Paragraph' && node.node.parent?.name==='ListItem' &&
          comparisons.some(b=>b.startEnd<node.from && node.from<b.endFrom)) {
        // Lezer treats the closing Pandoc fence as a lazy continuation of the
        // last list paragraph. Only the visible sample text is replaceable.
        const end=state.doc.lineAt(node.from).to;
        if (/^(?:Strength|Constraint)\.$/.test(state.sliceDoc(node.from,end)))
          decorations.push(Decoration.mark({class:'ff-option-placeholder',
            attributes:{title:'Click to replace this example'}}).range(node.from,end));
      }
      if (mark) decorations.push(Decoration.mark({class:mark}).range(node.from,node.to));
      if (['HeaderMark','EmphasisMark','CodeMark','StrikethroughMark','LinkMark','URL','LinkTitle'].includes(node.name)) {
        const parent=node.node.parent;
        if (node.name==='HeaderMark' && parent.name.startsWith('ATX') && headingText(state.doc.lineAt(node.from))) return;
        // Reveal syntax only in the inline construct currently being edited.
        if (!active(parent) && (node.name!=='URL' || parent.name==='Link'))
          decorations.push(Decoration.replace({}).range(node.from,node.to));
      }
      if (node.name==='Blockquote') for (let at=state.doc.lineAt(node.from).number; at<=state.doc.lineAt(node.to).number; at++)
        decorations.push(Decoration.line({class:'ff-visual-quote'}).range(state.doc.line(at).from));
      // Hide the quote marks of a passage that is not being edited.
      if (node.name==='QuoteMark' && !active(node.node.parent)) {
        const after=state.doc.sliceString(node.to,node.to+1)===' '?1:0;
        decorations.push(Decoration.replace({}).range(node.from,node.to+after));
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
  const selectionTools = showTooltip.computeN([field, 'selection'], state => {
    const {from,to,empty} = state.selection.main;
    if (empty || !state.field(field).enabled || state.readOnly || state.selection.ranges.length !== 1) return [];
    const selected = state.sliceDoc(from,to);
    if (!selected.trim() || /[\n\[\]*_`{}<>\\|]/.test(selected)) return [];
    const tree = syntaxTree(state), paragraph = tree.resolveInner(from,1);
    if (paragraph.name !== 'Paragraph' || paragraph.to < to ||
        tree.resolveInner(to,-1).from !== paragraph.from ||
        /^\s*(?:---|[:#|])/.test(state.doc.lineAt(from).text) ||
        (state.doc.line(1).text === '---' && from < (state.doc.toString().match(/^---\n[\s\S]*?\n(?:---|\.\.\.)(?:\n|$)/)?.[0].length || 0))) return [];
    return [{pos:from,end:to,above:true,create:view => {
      const dom = document.createElement('div'); dom.className = 'selection-tools';
      dom.setAttribute('role','toolbar'); dom.setAttribute('aria-label','Selected text');
      for (const [title, icon, mark] of [['Bold', Bold, '**'], ['Italic', Italic, '*'], ['Link to heading', Link, null]]) {
        const button = document.createElement('button'); button.type='button'; button.title=title;
        if (mark) {
          const key = mark==='**'?'B':'I';
          button.title += ' ('+(/Mac|iPhone|iPad/.test(navigator.platform)?'Cmd':'Ctrl')+'+'+key+')';
          button.setAttribute('aria-keyshortcuts','Control+'+key+' Meta+'+key);
        }
        button.setAttribute('aria-label',title); button.append(createElement(icon));
        button.onmousedown=e=>e.preventDefault();
        button.onclick=()=>{
          if (!actions.enabled() || view.state.doc !== state.doc ||
              !view.state.selection.eq(state.selection)) return;
          if (!mark) { actions.linkHeading?.({from,to,label:selected}); return; }
          formatProse(view,mark);
          view.focus();
        };
        dom.append(button);
      }
      return {dom};
    }}];
  });
  const bindings = ['b','i'].flatMap(key => ['Mod','Ctrl'].map(mod=>({key:mod+'-'+key,run:view=>
    !actions.isOrg() && actions.enabled() && formatProse(view,key==='b'?'**':'*')})));
  for (const key of ['Home','End']) {
    const move=(view,extend)=>{
      const state=view.state, sel=state.selection.main, line=state.doc.lineAt(sel.head);
      if (!state.field(field).enabled || actions.isOrg() || state.selection.ranges.length!==1 ||
          state.doc.lineAt(sel.anchor).number!==line.number) return false;
      const title=editableHeading(state,line);
      // At the end of a visual list, CodeMirror's visual-line End can pass
      // the next (replaced) closing fence. Stop at the actual bullet instead.
      if (!title && key==='End' && /^\s*(?:[-+*]|\d+[.)])\s/.test(line.text) &&
          model(state).columns.some(g=>g.parts.some(p=>line.from>=p.from && line.to<p.end))) {
        view.dispatch({selection:{anchor:extend?sel.anchor:line.to,head:line.to},scrollIntoView:true});
        return true;
      }
      if (!title) return false;
      const head=key==='Home'?title.from:title.to;
      const anchor=extend?Math.max(title.from,Math.min(title.to,sel.anchor)):head;
      view.dispatch({selection:{anchor,head},scrollIntoView:true});return true;
    };
    bindings.push({key,run:view=>move(view,false),shift:view=>move(view,true)});
  }
  bindings.push({key:'F2',run:view=>{
    if (!view.state.field(field).enabled || !actions.enabled() || actions.isOrg()) return false;
    const line=view.state.doc.lineAt(view.state.selection.main.head),title=editableHeading(view.state,line);
    if (!title) return false;
    view.dispatch({selection:{anchor:title.from,head:title.to},scrollIntoView:true});return true;
  }});
  const pickText=EditorView.domEventHandlers({mousedown(event,view) {
    if (event.button!==0 || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey ||
        !view.state.field(field).enabled || !actions.enabled() || actions.isOrg()) return false;
    const placeholder=event.target.closest?.('.ff-option-placeholder');
    const heading=event.detail===2 && event.target.closest?.('.ff-visual-heading');
    const row=event.detail===1 && event.target.closest?.('.cm-line');
    if (!placeholder && row && !event.target.closest?.('button,select,a,.ff-block-label,.ff-visual-table')) {
      const line=view.state.doc.lineAt(view.posAtDOM(row,0));
      if (/^\s*(?:[-+*]|\d+[.)])\s/.test(line.text) &&
          model(view.state).columns.some(g=>g.parts.some(p=>line.from>=p.from && line.to<p.end))) {
        const edge=view.coordsAtPos(line.to,-1);
        if (edge && event.clientX>edge.right && event.clientY>=edge.top-2 && event.clientY<=edge.bottom+2) {
          event.preventDefault();
          view.dispatch({selection:{anchor:line.to}});view.focus();return true;
        }
      }
    }
    if ((!placeholder && !heading) || event.target.closest?.('button')) return false;
    const pos=view.posAtDOM(placeholder || heading);
    const range=placeholder ? {from:pos,to:pos+placeholder.textContent.length} :
      editableHeading(view.state,view.state.doc.lineAt(pos));
    if (!range) return false;
    event.preventDefault();
    view.dispatch({selection:{anchor:range.from,head:range.to}});view.focus();return true;
  }});
  return [field, selectionTools, Prec.highest(pickText), Prec.highest(keymap.of(bindings)), EditorState.transactionFilter.of(tr => {
    if (!tr.docChanged || !tr.startState.field(field).enabled || actions.isOrg()
        || tr.annotation(layoutControl) || !(tr.isUserEvent('input') || tr.isUserEvent('delete'))) return tr;
    const changes = [];
    tr.changes.iterChanges((from,to,_a,_b,insert) => changes.push({from,to,insert:insert.toString()}));
    // Backspacing at the first letter or deleting at the last must not eat
    // hidden syntax. Deliberate deletion of the whole heading still works.
    for (const c of changes) {
      const line=tr.startState.doc.lineAt(c.from), title=editableHeading(tr.startState,line);
      if (!title || (c.from<=line.from && c.to>=line.to)) continue;
      if (c.from<title.from || (title.to<line.to && c.to>title.to)) return [];
    }
    if (layoutEditAllowed(tr.startState.doc.toString(), changes)) {
      // A blank line above the next option is editable on screen, but Pandoc
      // needs that separator after prose. Keep it in the same undo transaction.
      const separators=[];
      for (const h of model(tr.startState).optionHeadings) {
        if (changes.some(c=>c.from<=h.from && c.to>=h.to)) continue;
        const old=tr.startState.doc.lineAt(h.from);
        if (old.number<2 || tr.startState.doc.line(old.number-1).text.trim()) continue;
        const line=tr.newDoc.lineAt(tr.changes.mapPos(h.from,1));
        if (line.number>1 && /^####[ \t]/.test(line.text) && tr.newDoc.line(line.number-1).text.trim())
          separators.push({from:line.from,insert:'\n'});
      }
      return separators.length ? [tr,{changes:separators,sequential:true}] : tr;
    }
    queueMicrotask(() => actions.onError?.('Layout boundary protected. Edit the words inside it, or switch to Markdown to change the structure.'));
    return [];
  }), EditorView.atomicRanges.of(view=>view.state.field(field).atomic),
    ViewPlugin.fromClass(class {
      constructor(view) { this.updateClass(view); }
      update(update) { this.updateClass(update.view); }
      updateClass(view) { view.dom.classList.toggle('ff-visual',view.state.field(field).enabled && !actions.isOrg()); }
    })];
}
