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
