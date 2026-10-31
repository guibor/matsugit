import {Editor} from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import {Table, TableRow, TableCell, TableHeader} from '@tiptap/extension-table';
import {createElement, Bold, Italic, Strikethrough, Code, Undo2, Redo2, Combine, Split,
  Link2, Unlink, PanelTop, List, FileCode2} from 'lucide';

const $ = (id) => document.getElementById(id);
const token = location.hash.slice(1);
const demo = new URLSearchParams(location.search).has('demo') && !token;
let editor, dirty = false, done = false, timer, busy = false, importOK = false, previewVersion = 0;
const controls = [];
const error = (text) => { $('error').textContent = text; $('error').hidden = !text; };
const status = (text) => { $('status').textContent = text; };
function tableHTML() {
  const document = new DOMParser().parseFromString(editor.getHTML(), 'text/html');
  const table = document.querySelector('table');
  if (table) {
    // Preserve the header/body distinction which ProseMirror stores as th nodes.
    const head = document.createElement('thead');
    for (const row of Array.from(table.rows)) {
      if (!row.cells.length || !Array.from(row.cells).every(cell => cell.tagName === 'TH')) break;
      head.append(row);
    }
    if (head.rows.length) table.insertBefore(head, table.tBodies[0] || null);
  }
  return document.body.innerHTML;
}
async function api(path, data) {
  const response = await fetch(`api/${path}`, {
    method: data === undefined ? 'GET' : 'POST',
    headers: {'Authorization': `Bearer ${token}`, ...(data === undefined ? {} : {'Content-Type': 'application/json'})},
    ...(data === undefined ? {} : {body: JSON.stringify(data)}),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}
function button(label, icon, command, active) {
  const element = document.createElement('button');
  element.type = 'button';
  element.title = label;
  element.setAttribute('aria-label', label);
  element.append(createElement(icon));
  element.addEventListener('mousedown', (event) => event.preventDefault());
  element.addEventListener('click', () => { error(''); command(); });
  $('toolbar').append(element);
  controls.push({element, active});
  return element;
}
function separator() { const node = document.createElement('span'); node.className = 'separator'; $('toolbar').append(node); }
function menu(label, options) {
  const select = document.createElement('select');
  select.setAttribute('aria-label', label);
  const placeholder = new Option(label, '');
  select.append(placeholder);
  for (const [value, title] of options) select.append(new Option(title, value));
  select.addEventListener('change', () => { if (select.value) editor.chain().focus()[select.value]().run(); select.value = ''; });
  $('toolbar').append(select);
}
async function preview() {
  if (demo || done || $('source-panel').hidden) return;
  const version = ++previewVersion;
  try {
    const result = await api('preview', {html: tableHTML()});
    if (version === previewVersion) $('source').textContent = result.markdown;
  } catch (exception) { error(exception.message); }
}
function update() {
  const table = editor.getJSON().content.find((node) => node.type === 'table');
  const rowCount = table?.content?.length || 0;
  const columns = table?.content?.[0]?.content?.reduce((sum, cell) => sum + (cell.attrs?.colspan || 1), 0) || 0;
  const merged = table?.content?.some((row) => row.content.some((cell) => cell.attrs?.colspan > 1 || cell.attrs?.rowspan > 1));
  $('dimensions').textContent = `${rowCount} rows · ${columns} columns · ${merged ? 'Merged cells' : 'Table'}`;
  for (const {element, active} of controls) if (active) element.setAttribute('aria-pressed', String(active()));
  $('save').disabled = busy || done || demo || !importOK || !rowCount;
  clearTimeout(timer); timer = setTimeout(preview, 400);
}
async function initialize(html) {
  const aligned = (base) => base.extend({addAttributes() {
    return {...this.parent(), textAlign: {default: null,
      parseHTML: element => element.style.textAlign || null,
      renderHTML: attrs => attrs.textAlign ? {style: `text-align: ${attrs.textAlign}`} : {},
    }};
  }});
  // Pandoc's thead/tbody wrappers are normalized by ProseMirror. The server
  // checks semantic equivalence after import, including spans and formatting.
  editor = new Editor({element: $('editor'), content: html,
    extensions: [StarterKit.configure({heading: false, blockquote: false, codeBlock: false,
      horizontalRule: false, underline: false, trailingNode: false, link: {openOnClick: false, autolink: false}}),
      Table.configure({resizable: true, lastColumnResizable: false}), TableRow, aligned(TableCell), aligned(TableHeader)],
    onUpdate: () => { dirty = true; status(demo ? 'Demo' : 'Unsaved changes'); update(); },
    onSelectionUpdate: () => update(),
  });
  // Exposes the existing editor API for local integration tests, not a second model.
  window.folioforgeEditor = editor;
  button('Undo', Undo2, () => editor.chain().focus().undo().run());
  button('Redo', Redo2, () => editor.chain().focus().redo().run());
  separator();
  for (const [label, icon, name] of [['Bold', Bold, 'bold'], ['Italic', Italic, 'italic'], ['Strikethrough', Strikethrough, 'strike'], ['Inline code', Code, 'code']]) {
    button(label, icon, () => editor.chain().focus().toggleMark(name).run(), () => editor.isActive(name));
  }
  button('Bullet list', List, () => editor.chain().focus().toggleBulletList().run(), () => editor.isActive('bulletList'));
  button('Link', Link2, () => { $('link-url').value = editor.getAttributes('link').href || ''; $('link-dialog').showModal(); });
  button('Remove link', Unlink, () => editor.chain().focus().unsetLink().run());
  separator();
  menu('Rows', [['addRowBefore', 'Insert above'], ['addRowAfter', 'Insert below'], ['deleteRow', 'Delete row']]);
  menu('Columns', [['addColumnBefore', 'Insert left'], ['addColumnAfter', 'Insert right'], ['deleteColumn', 'Delete column']]);
  button('Merge selected cells', Combine, () => editor.chain().focus().mergeCells().run());
  button('Split merged cell', Split, () => editor.chain().focus().splitCell().run());
  button('Header row', PanelTop, () => editor.chain().focus().toggleHeaderRow().run());
  separator();
  const source = button('Table source', FileCode2, () => { $('source-panel').hidden = !$('source-panel').hidden; preview(); }, () => !$('source-panel').hidden);
  if (demo) source.disabled = true;
  $('link-dialog').addEventListener('close', () => {
    if ($('link-dialog').returnValue !== 'apply') return;
    const href = $('link-url').value.trim();
    if (/^(?:javascript|data|file):/i.test(href)) { error('Unsupported link scheme'); return; }
    if (href) editor.chain().focus().extendMarkRange('link').setLink({href}).run();
    else editor.chain().focus().unsetLink().run();
  });
  if (!demo) await api('check', {html: tableHTML()});
  importOK = true;
  status(demo ? 'Demo' : 'Ready'); update();
}
async function finish(save) {
  if (busy || done || demo || (save && !importOK)) return;
  busy = true; update(); error(''); status(save ? 'Saving' : 'Cancelling');
  try {
    await api(save ? 'save' : 'cancel', save ? {html: tableHTML()} : {});
    done = true; dirty = false; editor.setEditable(false); status(save ? 'Saved' : 'Cancelled');
    $('cancel').disabled = true; update(); window.close();
  } catch (exception) { error(exception.message); status('Not saved'); }
  finally { busy = false; update(); }
}
$('save').onclick = () => finish(true);
$('cancel').onclick = () => finish(false);
window.addEventListener('beforeunload', (event) => { if (dirty && !done && !demo) { event.preventDefault(); event.returnValue = ''; } });
document.addEventListener('keydown', (event) => { if ((event.ctrlKey || event.metaKey) && event.key === 's') { event.preventDefault(); finish(true); } });
try {
  const data = demo ? {name: 'Quarterly review', html: '<table><tr><th>Area</th><th>Team</th><th>Result</th></tr><tr><td>North</td><td><strong>Alpha</strong></td><td>12</td></tr><tr><td>North</td><td>Beta</td><td>18</td></tr><tr><td>South</td><td>Gamma</td><td>24</td></tr></table>'} : await api('table');
  $('name').textContent = data.name; await initialize(data.html);
  if (demo) $('cancel').disabled = true;
  else setInterval(() => { if (!done) api('ping').catch((exception) => { error(exception.message); status('Disconnected'); }); }, 30000);
} catch (exception) { error(exception.message); status('Unavailable'); $('save').disabled = true; }
