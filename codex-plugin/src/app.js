import {App, applyDocumentTheme, applyHostStyleVariables} from '@modelcontextprotocol/ext-apps';
import {OpenAIExtensions} from '@openai/mcp-extensions/app';
import {EditorView, basicSetup} from 'codemirror';
import {markdown} from '@codemirror/lang-markdown';
import {undo, redo} from '@codemirror/commands';
import {EditorState} from '@codemirror/state';
import {createElement, FileText, FolderOpen, Save, Download, Undo2, Redo2, RefreshCw, PanelsTopLeft} from 'lucide';
import {previewHtml} from './preview.js';

const $ = id => document.getElementById(id);
const app = new App({name: 'Folioforge', version: '0.1.0'});
const extensions = new OpenAIExtensions(app);
const demo = window.FOLIOFORGE_DEMO;
const state = {name: 'Untitled.md', base: '', etag: null, writable: false, conflict: false,
  session: null, uri: null, revision: 0, renderedRevision: -1, rendering: false,
  format: 'document', layout: 'split', rendered: null, saving: false, loading: false,
  positions: {document: {hash: '', scroll: 0}, slides: {hash: '', scroll: 0}}};
let debounce, loadSequence = 0, previewSequence = 0, disposeUpdates, previewUrl;
const text = () => editor.state.doc.toString();
const dirty = () => text() !== state.base;
const notice = (message = '') => { $('notice').hidden = !message; $('notice-text').textContent = message; $('reload').hidden = !state.conflict; };
const status = message => { $('status').textContent = message; };
const editor = new EditorView({parent: $('editor'), extensions: [basicSetup, markdown(), EditorView.lineWrapping,
  EditorState.readOnly.of(!!demo), EditorView.editable.of(!demo),
  EditorView.contentAttributes.of({'aria-label': 'Markdown source'}),
  EditorView.updateListener.of(update => {
    if (update.docChanged && !state.loading) { state.revision++; refreshControls(); scheduleRender(); }
    const line = update.state.doc.lineAt(update.state.selection.main.head);
    $('location').textContent = `Ln ${line.number}, Col ${update.state.selection.main.head - line.from + 1}`;
  }),
]});
for (const [id, icon] of Object.entries({'brand-icon': FileText, 'empty-icon': PanelsTopLeft,
  open: FolderOpen, save: Save, download: Download, undo: Undo2, redo: Redo2, refresh: RefreshCw})) $(id).append(createElement(icon));

async function call(name, args) {
  const response = await app.callServerTool({name, arguments: args});
  if (response.isError) throw Error(response.content?.filter(item => item.type === 'text').map(item => item.text).join('\n') || 'Operation failed.');
  return {...response.structuredContent, ...response._meta};
}
function refreshControls() {
  $('dirty').hidden = !dirty();
  $('save').disabled = !!demo || state.saving || !state.writable || !state.etag || state.conflict || !dirty();
  $('refresh').disabled = !!demo || state.rendering;
  $('filename').textContent = state.name;
  $('filename').title = state.name;
  $('reload').hidden = !state.conflict;
  if (!state.rendering && !state.saving) status(state.conflict ? 'External changes detected' : dirty() ? 'Unsaved changes' : demo ? 'Read-only design preview' : state.etag ? 'Saved' : 'Local draft');
  updateModelContext();
}
function replaceText(value) {
  state.loading = true;
  editor.dispatch({changes: {from: 0, to: editor.state.doc.length, insert: value}});
  state.loading = false;
  state.revision++;
}
function changeLayout(layout) {
  state.layout = layout;
  $('workspace').dataset.layout = layout;
  for (const button of document.querySelectorAll('[data-layout]')) if (button.tagName === 'BUTTON') button.setAttribute('aria-pressed', String(button.dataset.layout === layout));
  editor.requestMeasure(); updateModelContext();
}
function showPreview() {
  if (!state.rendered) return;
  const frame = $('preview');
  // A separate opaque-origin frame runs Reveal/Mermaid, never the editor's bridge.
  // A real blob URL lets Reveal change fragments without navigating to the app itself.
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(new Blob([previewHtml(state.rendered[state.format], state.format, state.positions[state.format])], {type: 'text/html'}));
  frame.src = previewUrl + state.positions[state.format].hash;
  frame.title = state.format === 'slides' ? 'Slide preview' : 'Document preview';
  $('empty').hidden = true;
}
function changeFormat(format) {
  state.format = format;
  for (const button of document.querySelectorAll('[data-format]')) button.setAttribute('aria-pressed', String(button.dataset.format === format));
  showPreview(); updateModelContext();
}
for (const button of document.querySelectorAll('button[data-layout]')) button.onclick = () => changeLayout(button.dataset.layout);
for (const button of document.querySelectorAll('button[data-format]')) button.onclick = () => changeFormat(button.dataset.format);
window.addEventListener('message', event => {
  if (event.source !== $('preview').contentWindow) return;
  if (['slides', 'document'].includes(event.data?.folioforgeFormat)) changeFormat(event.data.folioforgeFormat);
  const position = event.data?.folioforgePosition;
  if (position && ['slides', 'document'].includes(position.format)
      && typeof position.hash === 'string' && position.hash.length < 1024
      && (!position.hash || position.hash.startsWith('#')) && Number.isFinite(position.scroll)) {
    state.positions[position.format] = {hash: position.hash, scroll: Math.max(0, position.scroll),
      h: Number.isInteger(position.h) && position.h >= 0 ? position.h : 0,
      v: Number.isInteger(position.v) && position.v >= 0 ? position.v : 0,
      slideId: typeof position.slideId === 'string' && position.slideId.length < 512 ? position.slideId : ''};
  }
});
function scheduleRender() {
  clearTimeout(debounce);
  if (!demo && $('auto').checked) debounce = setTimeout(render, 1500);
}
async function render() {
  if (demo || state.rendering) return;
  const revision = state.revision, sequence = ++previewSequence;
  state.rendering = true; refreshControls(); status('Preparing preview');
  try {
    const initial = await call('folioforge_preview', {text: text(), name: state.name,
      theme: $('theme').value.trim(), ...(state.session ? {session: state.session} : {})});
    let job = initial;
    while (job.state === 'rendering') {
      status(job.phase || 'Rendering');
      if (!state.rendered) $('empty-label').textContent = job.phase || 'Rendering';
      await new Promise(resolve => setTimeout(resolve, 800));
      job = await call('folioforge_preview_status', {job: initial.job, ...(state.session ? {session: state.session} : {})});
    }
    if (sequence !== previewSequence) return;
    if (job.state !== 'ready') throw Error(job.error || 'Preview failed.');
    const rendered = {};
    status('Loading preview');
    for (const format of ['document', 'slides']) {
      const parts = []; let offset = 0;
      while (true) {
        if (sequence !== previewSequence || revision !== state.revision) return;
        const part = await call('folioforge_preview_chunk', {job: initial.job, format, offset,
          ...(state.session ? {session: state.session} : {})});
        parts.push(part.chunk); offset = part.next;
        if (part.done) break;
      }
      rendered[format] = parts.join('');
    }
    if (revision === state.revision) {
      state.rendered = rendered; state.renderedRevision = revision; showPreview();
      if (!state.conflict) notice();
    }
  } catch (error) {
    if (sequence === previewSequence) {
      notice(error.message); $('empty-label').textContent = 'Preview unavailable';
    }
  } finally {
    if (sequence === previewSequence) {
      state.rendering = false; refreshControls();
      if (revision !== state.revision) scheduleRender();
    }
  }
}
async function resourceRead() {
  if (state.uri) {
    const response = await extensions.resources.read({uri: state.uri, representation: 'text'});
    const item = response.contents[0];
    const value = 'text' in item ? item.text : new TextDecoder('utf-8', {fatal: true}).decode(Uint8Array.from(atob(item.blob), char => char.charCodeAt(0)));
    return {text: value, etag: item.openaiMetadata?.etag, writable: item.openaiMetadata?.writable === true};
  }
  const result = await call('folioforge_read', {session: state.session});
  return {...result, text: result.source};
}
async function reload(force = false) {
  if ((!state.uri && !state.session) || state.loading || state.saving) return;
  const sequence = loadSequence;
  try {
    const data = await resourceRead();
    if (sequence !== loadSequence || data.etag === state.etag) return;
    if (dirty() && !force) {
      state.conflict = true; notice('The file changed outside this editor. Your draft is retained. Download it or reload the file.');
    } else {
      state.base = data.text; state.etag = data.etag; state.writable = data.writable;
      state.conflict = false; replaceText(data.text); notice(); scheduleRender();
    }
    refreshControls();
  } catch (error) { notice(error.message); }
}
async function save() {
  if ($('save').disabled) return;
  const value = text(), sequence = loadSequence;
  state.saving = true; refreshControls(); status('Saving');
  try {
    const result = state.uri ? await extensions.resources.write(state.uri, {text: value, ifMatch: state.etag})
      : await call('folioforge_save', {session: state.session, text: value, etag: state.etag});
    if (sequence !== loadSequence) return;
    if (result.outcome === 'saved') { state.base = value; state.etag = result.etag; notice(); }
    else if (result.outcome === 'conflict') {
      state.conflict = true; notice('Save refused: the file changed outside this editor. Your draft is retained.');
    } else throw Error(result.outcome === 'too-large' ? 'The file exceeds the host write limit.' : 'The host did not save the file.');
  } catch (error) { notice(error.message); }
  finally { state.saving = false; refreshControls(); }
}
async function load(data) {
  if (dirty() && !confirm('Discard the unsaved draft and open another document?')) return;
  const sequence = ++loadSequence;
  clearTimeout(debounce); previewSequence++; state.rendering = false;
  disposeUpdates?.(); disposeUpdates = null;
  if (state.uri) extensions.resources?.unsubscribe({uri: state.uri}).catch(() => {});
  Object.assign(state, {uri: data.file?.resourceUri || null, session: data.session || null,
    name: data.file?.name || data.name || 'Untitled.md', conflict: false, rendered: null, etag: null, writable: false,
    positions: {document: {hash: '', scroll: 0}, slides: {hash: '', scroll: 0}}});
  if (['source', 'render', 'split'].includes(data.layout)) changeLayout(data.layout);
  if (['document', 'slides'].includes(data.format)) changeFormat(data.format);
  document.querySelector('button[data-layout="source"]').textContent = state.name.toLowerCase().endsWith('.org') ? 'Org' : 'Markdown';
  $('empty').hidden = false; $('empty-label').textContent = 'Preparing preview'; $('preview').src = 'about:blank';
  if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
  try {
    if (state.uri) {
      if (!extensions.resources) throw Error('This host does not support file editing. Update Codex Desktop or use the folioforge_open tool.');
      data = await resourceRead();
    }
    if (sequence !== loadSequence) return;
    const source = data.source ?? data.text ?? '';
    if (new TextEncoder().encode(source).length > 2 * 1024 * 1024 || source.includes('\0')) throw Error('Invalid source or document exceeds the 2 MiB editor limit.');
    state.base = source; state.etag = data.etag;
    state.writable = !!data.writable; replaceText(state.base);
    notice(state.writable && !state.etag ? 'The host supplied no file version. Saving is disabled to protect concurrent edits.' : '');
    if (state.uri) {
      disposeUpdates = extensions.resources.addUpdateHandler(({params}) => { if (params.uri === state.uri) reload(); });
      extensions.resources.subscribe({uri: state.uri}).catch(() => {});
    }
    refreshControls();
    if (demo) { state.rendered = demo.rendered; showPreview(); }
    else await render();
  } catch (error) { notice(error.message); status('Cannot open document'); }
}
function download() {
  const url = URL.createObjectURL(new Blob([text()], {type: 'text/plain;charset=utf-8'}));
  const link = document.createElement('a'); link.href = url; link.download = state.name;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function updateModelContext() {
  if (!demo && app.getHostContext()) app.updateModelContext({structuredContent: {
    file: state.name, layout: state.layout, format: state.format, dirty: dirty(), revision: state.revision,
    conflict: state.conflict, previewCurrent: state.renderedRevision === state.revision,
  }}).catch(() => {});
}
function hostContext(context) {
  if (context?.theme) applyDocumentTheme(context.theme);
  if (context?.styles?.variables) applyHostStyleVariables(context.styles.variables);
  for (const side of ['top','bottom','left','right']) document.documentElement.style.setProperty(`--safe-${side}`, `${context?.safeAreaInsets?.[side] || 0}px`);
}
$('save').onclick = save; $('download').onclick = download;
$('undo').onclick = () => undo(editor); $('redo').onclick = () => redo(editor);
$('refresh').onclick = render; $('auto').onchange = scheduleRender;
$('theme').onchange = () => { state.revision++; scheduleRender(); };
$('reload').onclick = () => { if (confirm('Discard this editor draft and reload the latest file?')) reload(true); };
$('open').onclick = () => $('file').click();
$('file').onchange = async () => {
  const file = $('file').files[0]; if (!file) return;
  if (file.size > 2 * 1024 * 1024) return notice('Document exceeds the 2 MiB editor limit.');
  await load({name: file.name, text: await file.text(), writable: false});
  notice('Imported browser copy. Download source to save; relative assets require opening the repository file in Codex.');
};
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); save(); }
});
window.addEventListener('beforeunload', event => { if (dirty() && !demo) { event.preventDefault(); event.returnValue = ''; } });
function resize(value) {
  const percent = Math.max(20, Math.min(80, value));
  document.documentElement.style.setProperty(innerWidth <= 700 ? '--source-height' : '--source-size', percent + '%');
  $('divider').setAttribute('aria-valuenow', String(Math.round(percent))); editor.requestMeasure();
}
$('divider').onpointerdown = event => { $('divider').setPointerCapture(event.pointerId); };
$('divider').onpointermove = event => {
  if (!$('divider').hasPointerCapture(event.pointerId)) return;
  const bounds = $('workspace').getBoundingClientRect();
  resize(innerWidth <= 700 ? (event.clientY - bounds.top) / bounds.height * 100 : (event.clientX - bounds.left) / bounds.width * 100);
};
$('divider').onkeydown = event => {
  if (['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) { event.preventDefault(); resize(Number($('divider').getAttribute('aria-valuenow')) + (['ArrowLeft','ArrowUp'].includes(event.key) ? -5 : 5)); }
};
function dividerOrientation() { $('divider').setAttribute('aria-orientation', innerWidth <= 700 ? 'horizontal' : 'vertical'); }
window.addEventListener('resize', dividerOrientation); dividerOrientation();
document.modelContext?.registerTool({name: 'folioforge_get_source', description: 'Read the current workspace draft, including unsaved edits.',
  inputSchema: {type: 'object', properties: {}}, annotations: {readOnlyHint: true},
  async execute() { return JSON.stringify({name: state.name, text: text(), revision: state.revision, dirty: dirty()}); }});
document.modelContext?.registerTool({name: 'folioforge_replace_source', description: 'Replace the workspace draft only when its revision matches. Does not save or publish.',
  inputSchema: {type: 'object', properties: {text: {type: 'string'}, revision: {type: 'integer'}}, required: ['text','revision']},
  async execute(args) {
    if (demo || args.revision !== state.revision) throw Error('Draft changed; read the current revision first.');
    if (new TextEncoder().encode(args.text).length > 2 * 1024 * 1024) throw Error('Document exceeds 2 MiB.');
    editor.dispatch({changes: {from: 0, to: editor.state.doc.length, insert: args.text}});
    return JSON.stringify({revision: state.revision, saved: false});
  }});
// Expose only the editor model to the isolated local UI test harness.
window.folioforgeWorkspace = {editor, state, load, render, save, reload};
async function boot() {
if (demo) {
  await load(demo);
  for (const id of ['open','save','undo','redo','refresh','auto','theme']) $(id).disabled = true;
} else {
  app.addEventListener('toolinput', ({arguments: args}) => {
    if (args?.file && args.file.resourceUri !== state.uri) load(args);
  });
  app.ontoolresult = result => {
    const data = {...result.structuredContent, ...result._meta};
    if (data.file && data.file.resourceUri === state.uri) return;
    load(data);
  };
  app.addEventListener('hostcontextchanged', hostContext);
  try { await app.connect(); hostContext(app.getHostContext()); }
  catch (error) { notice(error.message); status('Host connection unavailable'); }
  setInterval(() => { if (state.session) reload(); }, 3000);
}
}
boot().catch(error => { notice(error.message); status('Workspace unavailable'); });
