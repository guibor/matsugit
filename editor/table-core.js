// Shared table schema and HTML normalization for the browser and MCP editors.
export function tableExtensions({StarterKit, Table, TableRow, TableCell, TableHeader}) {
  const aligned = base => base.extend({addAttributes() {
    return {...this.parent(), textAlign: {default:null,
      parseHTML: element => element.style.textAlign || null,
      renderHTML: attrs => attrs.textAlign ? {style:`text-align: ${attrs.textAlign}`} : {}}};
  }});
  return [StarterKit.configure({heading:false, blockquote:false, codeBlock:false,
    horizontalRule:false, underline:false, trailingNode:false,
    link:{openOnClick:false, autolink:false}}),
    Table.configure({resizable:true, lastColumnResizable:false}), TableRow, aligned(TableCell), aligned(TableHeader)];
}

export function tableHTML(editor) {
  const doc = new DOMParser().parseFromString(editor.getHTML(), 'text/html');
  const table = doc.querySelector('table');
  if (table) {
    const head = doc.createElement('thead');
    for (const row of Array.from(table.rows)) {
      if (!row.cells.length || !Array.from(row.cells).every(cell => cell.tagName === 'TH')) break;
      head.append(row);
    }
    if (head.rows.length) table.insertBefore(head, table.tBodies[0] || null);
  }
  return doc.body.innerHTML;
}

// Coordinates are physical DOM cells, including the header. ProseMirror owns
// logical spanning, rectangular selection and table mutations.
export function focusCell(editor, row = 0, column = 0) {
  let found;
  editor.state.doc.forEach((table, offset) => {
    if (table.type.name !== 'table' || found !== undefined) return;
    let r = 0;
    table.forEach((node, rowOffset) => {
      if (r++ !== row) return;
      let c = 0;
      node.forEach((cell, cellOffset) => {
        if (c++ === column) found = offset + rowOffset + cellOffset + 4;
      });
    });
  });
  if (found !== undefined) editor.commands.setTextSelection(found);
  editor.commands.focus();
}

export function tableContext(editor, TableMap) {
  const $pos = editor.state.selection.$anchorCell || editor.state.selection.$from;
  for (let depth = $pos.depth; depth > 0; depth--) {
    const table = $pos.node(depth);
    if (table.type.name !== 'table') continue;
    const map = TableMap.get(table), start = $pos.start(depth);
    if(!$pos.nodeAfter?.type.spec.tableRole?.match(/cell/) && $pos.depth < depth+2) return null;
    const cell = $pos.nodeAfter?.type.spec.tableRole?.match(/cell/) ? $pos.pos : $pos.before(depth + 2);
    return {map, start, rect:map.findCell(cell-start)};
  }
  return null;
}

export function selectTableAxis(editor, axis, TableMap, CellSelection) {
  const context = tableContext(editor, TableMap);
  if (!context) return false;
  const {map,start,rect} = context;
  const a = axis === 'row' ? rect.top * map.width : rect.left;
  const b = axis === 'row' ? (rect.top + 1) * map.width - 1 : (map.height - 1) * map.width + rect.left;
  editor.view.dispatch(editor.state.tr.setSelection(CellSelection.create(editor.state.doc, start+map.map[a], start+map.map[b])));
  editor.commands.focus();
  return true;
}

export function alignTableColumns(editor, alignment, TableMap) {
  const context = tableContext(editor, TableMap);
  if (!context) return false;
  const {map,start,rect} = context, selection = editor.state.selection;
  const area = selection.$headCell ? map.rectBetween(selection.$anchorCell.pos-start,selection.$headCell.pos-start) : rect;
  const positions = new Set();
  for (let r=0;r<map.height;r++) for (let c=area.left;c<area.right;c++) positions.add(start+map.map[r*map.width+c]);
  const tr=editor.state.tr;
  for (const pos of positions) { const cell=tr.doc.nodeAt(pos); tr.setNodeMarkup(pos,null,{...cell.attrs,textAlign:alignment}); }
  editor.view.dispatch(tr); editor.commands.focus(); return true;
}

export function spreadsheetPaste({parseRows, Fragment, Slice, TableMap, message}) {
  const matrix=(text,$context)=>{
    if (!text.includes('\t')) return null;
    let table;
    for(let d=$context.depth;d>0;d--) if($context.node(d).type.name==='table') table=$context.node(d);
    if (!table) return null;
    if(text.length>1024*1024) return {error:'Paste is too large; the table was not changed.'};
    const rows=parseRows(text), width=rows.reduce((max,row)=>Math.max(max,row.length),0);
    const map=TableMap.get(table);
    // Conservative bound includes any growth from the insertion cell.
    if(rows.length>500 || width>100 || (map.width+width)*(map.height+rows.length)>4000)
      return {error:'Paste exceeds the table size limit; the table was not changed.'};
    return {rows,width};
  };
  return {handleDOMEvents:{paste(view,event) {
    const data=matrix(event.clipboardData?.getData('text/plain') || '',view.state.selection.$from);
    if(!data?.error)return false;
    event.preventDefault();message(data.error);return true;
  }}, clipboardTextParser(text, $context, plainText, view) {
    const data=matrix(text,$context);
    if(!data || data.error)return null;
    const {rows,width}=data;
    const {schema}=view.state;
    const nodes=rows.map(row=>schema.nodes.tableRow.create(null,Array.from({length:width},(_,i)=>{
      const lines=(row[i] || '').split(/\r?\n/), content=[];
      lines.forEach((line,n)=>{if(n)content.push(schema.nodes.hardBreak.create());if(line)content.push(schema.text(line));});
      return schema.nodes.tableCell.create(null,schema.nodes.paragraph.create(null,content));
    })));
    return new Slice(Fragment.from(schema.nodes.table.create(null,nodes)),0,0);
  }};
}
