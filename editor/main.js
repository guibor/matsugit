import {Editor} from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import {Table, TableRow, TableCell, TableHeader} from '@tiptap/extension-table';
import {tableExtensions, tableHTML as normalizedTableHTML} from './table-core.js';
import {createElement, Bold, Italic, Strikethrough, Code, Undo2, Redo2, Combine, Split,
  Link2, Unlink, PanelTop, List, FileCode2} from 'lucide';

const $ = (id) => document.getElementById(id);
const token = location.hash.slice(1);
const demo = new URLSearchParams(location.search).has('demo') && !token;
const client = crypto.randomUUID();
let editor, dirty = false, done = false, timer, busy = false, importOK = false, previewVersion = 0;
let revision = 0, checkpointed = 0, draftTimer, draftRequest, connected = true, failures = 0;
const controls = [];
const error = (text) => { $('error').textContent = text; $('error').hidden = !text; };
const status = (text) => { $('status').textContent = text; };
function tableHTML() {
  return normalizedTableHTML(editor);
}
async function api(path, data, keepalive = false) {
  const response = await fetch(`api/${path}`, {
    method: data === undefined ? 'GET' : 'POST',
    headers: {'Authorization': `Bearer ${token}`, 'X-matsugit-Client': client,
      ...(data === undefined ? {} : {'Content-Type': 'application/json'})},
    keepalive,
    ...(data === undefined ? {} : {body: JSON.stringify(data)}),
  });
  const result = await response.json();
  if (!response.ok) { const exception = new Error(result.error || `Request failed (${response.status})`); exception.status = response.status; throw exception; }
  return result;
}
function disconnected(exception) {
  connected = false;
  if (exception.status === 409 || ++failures >= 3) done = true;
  editor?.setEditable(false);
  error(exception.message);
  status(exception.status === 409 ? 'Replaced by another tab' : done ? 'Session ended' : 'Disconnected');
  update();
}
async function checkpoint() {
  if (demo || done || busy || !importOK || revision === checkpointed) return;
  if (draftRequest) {
    try { await draftRequest; } catch { return; }
    return checkpoint();
  }
  const version = revision;
  draftRequest = api('draft', {html: tableHTML(), revision: version});
  try {
    await draftRequest;
    checkpointed = Math.max(checkpointed, version);
    if (!busy && !done && revision === checkpointed) status('Draft saved');
  } catch (exception) {
    if (exception.status === 400) { error(exception.message); status('Draft not saved'); }
    else disconnected(exception);
  }
  finally { draftRequest = null; }
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
  for (const element of $('toolbar').querySelectorAll('button,select')) {
    element.disabled = busy || done || !connected || (demo && element.dataset.demoDisabled === 'true');
  }
  $('save').disabled = busy || done || demo || !connected || !importOK || !rowCount;
  clearTimeout(timer); timer = setTimeout(preview, 400);
}
async function initialize(html) {
  // Pandoc's thead/tbody wrappers are normalized by ProseMirror. The server
  // checks semantic equivalence after import, including spans and formatting.
  editor = new Editor({element: $('editor'), content: html,
    extensions: tableExtensions({StarterKit, Table, TableRow, TableCell, TableHeader}),
    onUpdate: () => {
      dirty = true; revision++; status(demo ? 'Demo' : 'Unsaved changes'); update();
      clearTimeout(draftTimer); draftTimer = setTimeout(checkpoint, 600);
    },
    onSelectionUpdate: () => update(),
  });
  // Exposes the existing editor API for local integration tests, not a second model.
  window.matsugitEditor = editor;
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
  if (demo) source.dataset.demoDisabled = 'true';
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
  busy = true; editor.setEditable(false); clearTimeout(draftTimer);
  update(); error(''); status(save ? 'Saving' : 'Cancelling');
  try {
    if (draftRequest) await draftRequest;
    await api(save ? 'save' : 'cancel', save ? {html: tableHTML()} : {});
    done = true; dirty = false; editor.setEditable(false); status(save ? 'Saved' : 'Cancelled');
    $('cancel').disabled = true; update(); window.close();
  } catch (exception) {
    error(exception.message); status('Not saved');
    if (exception.status === 409) disconnected(exception);
    else if (connected) editor.setEditable(true);
  }
  finally { busy = false; update(); }
}
$('save').onclick = () => finish(true);
$('cancel').onclick = () => finish(false);
window.addEventListener('beforeunload', (event) => {
  if (dirty && revision > checkpointed && !demo) { event.preventDefault(); event.returnValue = ''; }
});
window.addEventListener('blur', () => { checkpoint().catch(disconnected); });
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') checkpoint().catch(disconnected);
});
window.addEventListener('pagehide', () => {
  if (done || demo || !importOK) return;
  const latest = {html: tableHTML(), revision};
  // Keepalive bodies are bounded by browsers. Large tables use the acknowledged
  // checkpoint, with beforeunload protection for any newer, unsaved typing.
  const data = new TextEncoder().encode(JSON.stringify(latest)).length < 60000 ? latest : {};
  api('detach', data, true).catch(() => {});
});
document.addEventListener('keydown', (event) => { if ((event.ctrlKey || event.metaKey) && event.key === 's') { event.preventDefault(); finish(true); } });
try {
  const data = demo ? {name: 'Quarterly review', html: '<table><tr><th>Area</th><th>Team</th><th>Result</th></tr><tr><td>North</td><td><strong>Alpha</strong></td><td>12</td></tr><tr><td>North</td><td>Beta</td><td>18</td></tr><tr><td>South</td><td>Gamma</td><td>24</td></tr></table>'} : await api('open', {client});
  $('name').textContent = data.name; await initialize(data.html);
  if (data.recovered) { dirty = true; status('Recovered draft'); }
  if (demo) $('cancel').disabled = true;
  else setInterval(async () => {
    if (done || busy) return;
    try {
      const state = await api('ping');
      failures = 0;
      if (!connected) { connected = true; error(''); editor.setEditable(true); update(); }
      if (state.command === 'save') await finish(true);
      else await checkpoint();
    } catch (exception) { disconnected(exception); }
  }, 1000);
} catch (exception) { error(exception.message); status('Unavailable'); $('save').disabled = true; }
