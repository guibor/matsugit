import {Editor} from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import {Table, TableRow, TableCell, TableHeader} from '@tiptap/extension-table';
import {TableMap, CellSelection} from '@tiptap/pm/tables';
import {Fragment, Slice} from '@tiptap/pm/model';
import {tsvParseRows} from 'd3-dsv';
import {isolateHistory} from '@codemirror/commands';
import {createElement, Bold, Italic, Strikethrough, Code, Undo2, Redo2, Combine, Split,
  Link2, Unlink, PanelTop, List, X, Check, Download, Maximize2, AlignLeft, AlignCenter, AlignRight,
  Rows3, Columns3, BetweenHorizontalStart, BetweenVerticalStart} from 'lucide';
import {tableExtensions, tableHTML, focusCell, tableContext, selectTableAxis, alignTableColumns, spreadsheetPaste} from '../../editor/table-core.js';
import {tableRanges} from './visual.mjs';

export function tableDialog({editor, state, call, changed, notice, enabled}) {
  const $=id=>document.getElementById(id), dialog=$('table-dialog');
  let current=null, rich=null, busy=false, baseline='', token=0;
  let placement=null, resize=null;
  const controls=[];
  const previewCache=new Map();
  let previewQueue=Promise.resolve();
  const pending=()=>!!current?.dirty;
  const snapshot=()=>pending() ? {...current.range,format:current.format,html:rich ? tableHTML(rich) : current.html} : null;
  const message=value=>{$('table-status').textContent=value;};
  function updateControls() {
    for(const {el,can,active} of controls) {
      el.disabled=busy || !rich || (can && !can());
      if(active)el.setAttribute('aria-pressed',String(!!rich && active()));
    }
    const context=rich && tableContext(rich,TableMap);
    $('table-cell').textContent=context ? `R${context.rect.top+1} C${context.rect.left+1} / ${context.map.height} \u00d7 ${context.map.width}` : '';
  }
  function lock(value) {
    busy=value;
    $('table-apply').disabled=value || !rich;
    for(const el of $('table-toolbar').querySelectorAll('button,select')) el.disabled=value || !rich;
    rich?.setEditable(!value,false);
    updateControls();
  }
  function undock() {
    const old=placement; placement=null; resize?.disconnect(); resize=null;
    dialog.close(); document.body.append(dialog); dialog.classList.remove('table-inline');
    old?.mount.classList.remove('ff-table-editing'); old?.measure();
    $('table-expand').hidden=true;
  }
  function expand() {
    if(!placement)return;
    undock();dialog.showModal();rich?.commands.focus();
  }
  function clean() {
    token++; rich?.destroy(); rich=null; current=null; baseline=''; undock(); changed(); editor.focus();
  }
  function close() {
    if (busy) return;
    if (pending() && !confirm('Discard unapplied table edits? A recovery checkpoint may retain a copy.')) return;
    clean();
  }
  async function open(range, recovered, inline) {
    if (!enabled()) return;
    if (dialog.open) { rich?.commands.focus(); return; }
    const source=editor.state.doc.sliceString(range.from,range.to);
    if(source!==range.source) {notice('The table moved or changed. Select it again.');return;}
    const id=++token, format=recovered?.format || (state.name.toLowerCase().endsWith('.org')?'org':'markdown');
    current={range:{from:range.from,to:range.to,source},format,doc:editor.state.doc,
      dirty:!!recovered,html:recovered?.html};
    placement=inline?.mount?.isConnected ? inline : null;
    if(placement) {
      placement.mount.classList.add('ff-table-editing');placement.mount.append(dialog);
      dialog.classList.add('table-inline');dialog.show();
      resize=new ResizeObserver(()=>placement?.measure());resize.observe(dialog);placement.measure();
    } else dialog.showModal();
    $('table-expand').hidden=!placement;
    $('table-content').replaceChildren(); lock(true); message('Loading table...');
    try {
      const imported=await call('matsugit_table',{operation:'open',source,format,html:recovered?.html});
      if(id!==token) return;
      rich=new Editor({element:$('table-content'),content:imported.html,
        extensions:tableExtensions({StarterKit,Table,TableRow,TableCell,TableHeader}),
        editorProps:spreadsheetPaste({parseRows:tsvParseRows,Fragment,Slice,TableMap,message}),
        onSelectionUpdate:()=>updateControls(),
        onUpdate:()=>{current.dirty=!!recovered || tableHTML(rich)!==baseline;message(current.dirty?'Unapplied table edits':'Ready');updateControls();changed();}});
      // Initialize table resizing while editable, then block input until the
      // conversion check confirms that the source survived import unchanged.
      rich.setEditable(false,false);
      baseline=tableHTML(rich);
      await call('matsugit_table',{operation:'check',source:imported.source,format,html:baseline});
      if(id!==token)return;
      lock(false); message(recovered?'Recovered table edits':'Ready'); changed();
      focusCell(rich,inline?.cell?.row,inline?.cell?.column);
    } catch(error) {
      message(error.message); busy=false; $('table-apply').disabled=true;
      rich?.setEditable(false,false);
    }
  }
  function atSelection() {
    const source=editor.state.doc.toString(), selection=editor.state.selection.main;
    let range=tableRanges(source).find(t=>selection.head>=t.from && selection.head<=t.to);
    if(!range && !selection.empty) range={from:selection.from,to:selection.to,source:source.slice(selection.from,selection.to)};
    if(!range && state.name.toLowerCase().endsWith('.org')) {
      const line=editor.state.doc.lineAt(selection.head);
      let a=line.number,b=line.number;
      while(a>1 && /^\s*\|/.test(editor.state.doc.line(a-1).text)) a--;
      while(b<editor.state.doc.lines && /^\s*(?:\||#\+TBLFM:)/i.test(editor.state.doc.line(b+1).text)) b++;
      if(/^\s*\|/.test(line.text)) {const from=editor.state.doc.line(a).from,to=editor.state.doc.line(b).to;range={from,to,source:source.slice(from,to)};}
    }
    if(range) return open(range);
    notice('Place the cursor in a table or select one table first.');
  }
  function button(label,icon,command,can,active) {
    const el=document.createElement('button');el.type='button';el.title=label;el.setAttribute('aria-label',label);
    el.append(createElement(icon));el.onmousedown=e=>e.preventDefault();el.onclick=()=>{if(!busy)command();};
    $('table-toolbar').append(el);controls.push({el,can,active});return el;
  }
  button('Undo table edit',Undo2,()=>rich.chain().focus().undo().run(),()=>rich.can().undo());
  button('Redo table edit',Redo2,()=>rich.chain().focus().redo().run(),()=>rich.can().redo());
  for(const [label,icon,mark] of [['Bold',Bold,'bold'],['Italic',Italic,'italic'],['Strikethrough',Strikethrough,'strike'],['Inline code',Code,'code']])
    button(label,icon,()=>rich.chain().focus().toggleMark(mark).run(),null,()=>rich.isActive(mark));
  button('Bullet list',List,()=>rich.chain().focus().toggleBulletList().run());
  button('Edit link',Link2,()=>{
    const href=prompt('Link URL',rich.getAttributes('link').href || '');
    if(href===null)return;
    if(!/^(?:https?:|mailto:|tel:|[^:\s]*$)/i.test(href.trim())){message('Unsupported link scheme');return;}
    if(href.trim())rich.chain().focus().extendMarkRange('link').setLink({href:href.trim()}).run();
    else rich.chain().focus().unsetLink().run();
  });
  button('Remove link',Unlink,()=>rich.chain().focus().unsetLink().run());
  button('Select row',Rows3,()=>selectTableAxis(rich,'row',TableMap,CellSelection));
  button('Select column',Columns3,()=>selectTableAxis(rich,'column',TableMap,CellSelection));
  button('Insert row below',BetweenHorizontalStart,()=>rich.chain().focus().addRowAfter().run());
  button('Insert column right',BetweenVerticalStart,()=>rich.chain().focus().addColumnAfter().run());
  for(const [label,icon,align] of [['Align column left',AlignLeft,'left'],['Align column center',AlignCenter,'center'],['Align column right',AlignRight,'right']])
    button(label,icon,()=>alignTableColumns(rich,align,TableMap),null,()=>rich.isActive('tableCell',{textAlign:align}) || rich.isActive('tableHeader',{textAlign:align}));
  for(const [label,choices] of [['Rows',[['addRowBefore','Insert above'],['addRowAfter','Insert below'],['deleteRow','Delete row']]],
    ['Columns',[['addColumnBefore','Insert left'],['addColumnAfter','Insert right'],['deleteColumn','Delete column']]]]) {
    const menu=document.createElement('select');menu.setAttribute('aria-label',label);menu.add(new Option(label,''));
    for(const [value,title] of choices) menu.add(new Option(title,value));
    menu.onchange=()=>{if(menu.value && !busy)rich.chain().focus()[menu.value]().run();menu.value='';};$('table-toolbar').append(menu);
  }
  button('Merge selected cells',Combine,()=>rich.chain().focus().mergeCells().run(),()=>rich.can().mergeCells());
  button('Split merged cell',Split,()=>rich.chain().focus().splitCell().run(),()=>rich.can().splitCell());
  button('Header row',PanelTop,()=>rich.chain().focus().toggleHeaderRow().run());
  $('table-close').append(createElement(X));$('table-close').onclick=close;
  $('table-expand').append(createElement(Maximize2));$('table-expand').onclick=expand;
  $('table-apply').append(createElement(Check));$('table-apply').append('Apply');
  $('table-download').append(createElement(Download));$('table-download').onclick=()=>{
    const html=rich?tableHTML(rich):current?.html;
    if(!html)return;
    const url=URL.createObjectURL(new Blob([html],{type:'text/html'}));
    const link=document.createElement('a');link.href=url;link.download='table-draft.html';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  dialog.addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();}
  });
  $('table-apply').onclick=async()=>{
    if(busy || !rich || !current)return;
    const captured=current,id=token;lock(true);message('Checking table...');
    try {
      const converted=await call('matsugit_table',{operation:'serialize',source:captured.range.source,format:captured.format,html:tableHTML(rich)});
      if(id!==token)return;
      if(!editor.state.doc.eq(captured.doc)) throw Error('Document changed while the table was open. Download this table draft before closing; reopen the current table to reconcile.');
      const insert=converted.markdown.replace(/\n$/,'');
      undock();
      editor.dispatch({changes:{from:captured.range.from,to:captured.range.to,insert},
        selection:{anchor:captured.range.from},annotations:isolateHistory.of('full'),userEvent:'input.table'});
      clean();
    } catch(error) {if(!dialog.open)dialog.showModal();message(error.message);lock(false);}
  };
  return {open,atSelection,pending,snapshot,reset:clean,
    detach(root) { if(placement?.mount===root) {expand();message('Table moved or the view changed; edits retained here.');} },
    restore:record=>{if(record)open(record,record);},
    preview(source) {
      if(!previewCache.has(source)) {
        const task=previewQueue.then(()=>call('matsugit_table',{operation:'open',source,format:'markdown'})).then(data=>data.html);
        previewQueue=task.catch(()=>{});previewCache.set(source,task);
        if(previewCache.size>64)previewCache.delete(previewCache.keys().next().value);
      }
      return previewCache.get(source);
    },
    get rich(){return rich;},
  };
}
