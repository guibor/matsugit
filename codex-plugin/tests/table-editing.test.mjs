import {test} from 'node:test';
import assert from 'node:assert/strict';
import {getSchema} from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import {Table,TableRow,TableCell,TableHeader} from '@tiptap/extension-table';
import {EditorState,TextSelection} from '@tiptap/pm/state';
import {TableMap,CellSelection} from '@tiptap/pm/tables';
import {Fragment,Slice} from '@tiptap/pm/model';
import {tsvParseRows} from 'd3-dsv';
import {tableExtensions,focusCell,tableContext,selectTableAxis,alignTableColumns,spreadsheetPaste} from '../../editor/table-core.js';

const schema=getSchema(tableExtensions({StarterKit,Table,TableRow,TableCell,TableHeader}));
function fixture() {
  const cell=(text,header=false)=>schema.nodes[header?'tableHeader':'tableCell'].create(null,schema.nodes.paragraph.create(null,schema.text(text)));
  const row=(a,b,header=false)=>schema.nodes.tableRow.create(null,[cell(a,header),cell(b,header)]);
  const doc=schema.nodes.doc.create(null,schema.nodes.table.create(null,[row('A','B',true),row('Left','Right'),row('Other','Value')]));
  const editor={state:EditorState.create({schema,doc,selection:TextSelection.create(doc,4)}),commands:{focus(){}}};
  editor.view={dispatch:tr=>{editor.state=editor.state.apply(tr);}};
  editor.commands.setTextSelection=pos=>editor.view.dispatch(editor.state.tr.setSelection(TextSelection.create(editor.state.doc,pos)));
  return editor;
}
test('click coordinates focus the same cell; row/column selection uses table spans',()=>{
  const editor=fixture();focusCell(editor,1,1);
  assert.equal(editor.state.selection.$from.parent.textContent,'Right');
  assert.deepEqual(tableContext(editor,TableMap).rect,{left:1,right:2,top:1,bottom:2});
  selectTableAxis(editor,'row',TableMap,CellSelection);
  assert.equal(editor.state.selection.isRowSelection(),true);
  focusCell(editor,1,1);selectTableAxis(editor,'column',TableMap,CellSelection);
  assert.equal(editor.state.selection.isColSelection(),true);
});
test('column alignment covers every row, not just one inconsistent cell',()=>{
  const editor=fixture();focusCell(editor,1,1);alignTableColumns(editor,'right',TableMap);
  editor.state.doc.firstChild.forEach(row=>{
    assert.equal(row.child(0).attrs.textAlign,null);assert.equal(row.child(1).attrs.textAlign,'right');
  });
  selectTableAxis(editor,'row',TableMap,CellSelection);alignTableColumns(editor,'center',TableMap);
  editor.state.doc.firstChild.descendants(node=>{if(['tableCell','tableHeader'].includes(node.type.name))assert.equal(node.attrs.textAlign,'center');});
});
test('quoted TSV paste becomes a bounded table slice, treating markup and formulas as text',()=>{
  const editor=fixture(), props=spreadsheetPaste({parseRows:tsvParseRows,Fragment,Slice,TableMap,message:()=>{}});
  const slice=props.clipboardTextParser('"two\nlines"\t"one\ttab"\r\n<script>x</script>\t=1+2\r\n',editor.state.selection.$from,true,editor);
  const table=slice.content.firstChild;
  assert.equal(table.childCount,2);assert.equal(table.child(0).childCount,2);
  assert.equal(table.child(0).child(0).firstChild.child(1).type.name,'hardBreak');
  assert.equal(table.child(0).child(1).textContent,'one\ttab');
  assert.equal(table.child(1).child(0).textContent,'<script>x</script>');
  assert.equal(table.child(1).child(1).textContent,'=1+2');
  assert.equal(props.clipboardTextParser('A normal paragraph',editor.state.selection.$from,true,editor),null);
});
test('oversized spreadsheet paste is consumed before native paste can replace selected cells',()=>{
  const editor=fixture();selectTableAxis(editor,'row',TableMap,CellSelection);
  let message,prevented=false;
  const props=spreadsheetPaste({parseRows:tsvParseRows,Fragment,Slice,TableMap,message:m=>message=m});
  const before=editor.state.doc;
  assert.equal(props.handleDOMEvents.paste(editor,{clipboardData:{getData:()=>('a\tb\n').repeat(501)},preventDefault:()=>{prevented=true;}}),true);
  assert.equal(prevented,true);assert.match(message,/size limit/);assert.equal(editor.state.doc,before);
});
