import {App, applyDocumentTheme, applyHostStyleVariables} from '@modelcontextprotocol/ext-apps';
import {OpenAIExtensions} from '@openai/mcp-extensions/app';
import {EditorView, basicSetup} from 'codemirror';
import {markdown} from '@codemirror/lang-markdown';
import {undo, redo} from '@codemirror/commands';
import {EditorState, Compartment} from '@codemirror/state';
import {createElement, FileText, FolderOpen, Save, Download, Undo2, Redo2, RefreshCw, PanelsTopLeft, Plus, History, RotateCcw, Trash2, X, Braces, Presentation, ChevronLeft, ChevronRight, Minimize2} from 'lucide';
import {previewHtml, patchedHtml} from './preview.js';
import {structure, headingTargets} from './structure.mjs';
import {authoringExtensions, insertMenu, compactMarkup} from './authoring.mjs';

const $ = id => document.getElementById(id);
const app = new App({name: 'matsugit', version: '0.6.1'});
const extensions = new OpenAIExtensions(app);
const demo = window.MATSUGIT_DEMO;
const state = {name: 'Untitled.md', base: '', etag: null, writable: false, conflict: false,
  session: null, uri: null, revision: 0, renderedRevision: -1, rendering: false,
  format: 'document', layout: 'split', rendered: null, saving: false, loading: false, pendingRender: false,
  bases: {}, revisions: {}, forceFull: false,
  positions: {document: {hash: '', scroll: 0}, slides: {hash: '', scroll: 0}}};
let debounce, loadSequence = 0, previewSequence = 0, readSequence = 0, disposeUpdates, previewUrl;
let previewToken = '', followingPreview = false, followTimer, origin = 'source', outlineRevision = -1, outline;
let sourceInput = 0;
let pendingPatch;
let recoveryId, recoveryGeneration = 0, recoveryTimer, recoveryPending = false, recoveryPromise, recoveryCandidate;
let restoredPosition = false;
let presentation = null;
const text = () => editor.state.doc.toString();
const dirty = () => text() !== state.base;
const notice = (message = '') => { $('notice').hidden = !message; $('notice-text').textContent = message; $('reload').hidden = !state.conflict; };
const status = message => { $('status').textContent = message; };
const editability = new Compartment();
const editable = value => [EditorState.readOnly.of(!value), EditorView.editable.of(value)];
const editor = new EditorView({parent: $('editor'), extensions: [basicSetup, markdown(), EditorView.lineWrapping,
  authoringExtensions({isOrg: () => state.name.toLowerCase().endsWith('.org'), enabled: () => !demo && !state.loading, onError: notice}),
  editability.of(editable(!demo)),
  EditorView.contentAttributes.of({'aria-label': 'Markdown source'}),
  EditorView.domEventHandlers({focus: () => { sourceInput = Date.now(); }}),
  EditorView.updateListener.of(update => {
    if (update.docChanged && !state.loading) { state.revision++; refreshControls(); scheduleRender(); }
    if ((update.docChanged || update.selectionSet) && !state.loading) scheduleRecovery();
    if ((update.selectionSet || update.docChanged) && !state.loading && !followingPreview) {
      origin = 'source'; clearTimeout(followTimer); followTimer = setTimeout(followSource, 180);
      sourceInput = Date.now();
    }
    const line = update.state.doc.lineAt(update.state.selection.main.head);
    $('location').textContent = `Ln ${line.number}, Col ${update.state.selection.main.head - line.from + 1}`;
  }),
]});
for (const [id, icon] of Object.entries({'brand-icon': FileText, 'empty-icon': PanelsTopLeft,
  open: FolderOpen, save: Save, download: Download, undo: Undo2, redo: Redo2, refresh: RefreshCw, insert: Plus,
  recover: History, 'close-recovery': X, 'compact-markup': Braces, present: Presentation,
  'present-previous': ChevronLeft, 'present-next': ChevronRight, 'present-exit': Minimize2})) $(id).append(createElement(icon));
$('compact-markup').onclick = () => {
  const compact = $('compact-markup').getAttribute('aria-pressed') !== 'true';
  $('compact-markup').setAttribute('aria-pressed', String(compact));
  editor.dispatch({effects:compactMarkup.of(compact)});
};

async function call(name, args) {
  const response = await app.callServerTool({name, arguments: args});
  if (response.isError) throw Error(response.content?.filter(item => item.type === 'text').map(item => item.text).join('\n') || 'Operation failed.');
  return {...response.structuredContent, ...response._meta};
}
function refreshControls() {
  $('dirty').hidden = !dirty();
  $('save').disabled = !!demo || state.saving || !state.writable || !state.etag || state.conflict || !dirty();
  $('refresh').disabled = !!demo || state.loading;
  $('refresh').title = state.rendering ? 'Queue latest preview' : 'Refresh preview (Shift: rebuild)';
  $('filename').textContent = state.name;
  $('filename').title = state.name;
  $('reload').hidden = !state.conflict;
  if (!state.rendering && !state.saving) status(state.conflict ? 'External changes detected'
    : state.rendered && state.renderedRevision !== state.revision ? 'Preview out of date'
    : dirty() ? 'Unsaved changes' : demo ? 'Read-only design preview' : state.etag ? 'Saved' : 'Local draft');
  updateModelContext();
}
function replaceText(value) {
  const selection = editor.state.selection.main;
  const wasLoading = state.loading;
  state.loading = true;
  editor.dispatch({changes: {from: 0, to: editor.state.doc.length, insert: value},
    selection: {anchor: Math.min(selection.anchor, value.length), head: Math.min(selection.head, value.length)}});
  state.loading = wasLoading;
  state.revision++;
}
function sourceOutline() {
  if (outlineRevision !== state.revision) {
    outline = structure(text(), state.name.toLowerCase().endsWith('.org'));
    outlineRevision = state.revision;
  }
  return outline.headings;
}
function followSource() {
  if (!$('sync').checked || !state.rendered || origin !== 'source') return;
  $('preview').contentWindow?.postMessage({matsugitPreview: previewToken,
    targets: headingTargets(sourceOutline(), editor.state.selection.main.head)}, '*');
}
function changeLayout(layout) {
  state.layout = layout;
  $('workspace').dataset.layout = layout;
  for (const button of document.querySelectorAll('[data-layout]')) if (button.tagName === 'BUTTON') button.setAttribute('aria-pressed', String(button.dataset.layout === layout));
  editor.requestMeasure(); updateModelContext();
  scheduleRecovery();
  if (!demo && !state.loading && layout !== 'source' && state.renderedRevision !== state.revision) render();
}
function showPreview() {
  if (!state.rendered?.[state.format]) return;
  const frame = $('preview');
  // A separate opaque-origin frame runs Reveal/Mermaid, never the editor's bridge.
  // A real blob URL lets Reveal change fragments without navigating to the app itself.
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewToken = crypto.randomUUID();
  previewUrl = URL.createObjectURL(new Blob([previewHtml(state.rendered[state.format], state.format, state.positions[state.format], previewToken, state.bases[state.format])], {type: 'text/html'}));
  frame.src = previewUrl + state.positions[state.format].hash;
  frame.title = state.format === 'slides' ? 'Slide preview' : 'Document preview';
  $('empty').hidden = true;
}
function changeFormat(format) {
  if (format === state.format && state.rendered?.[format]) return;
  state.format = format;
  state.renderedRevision = state.revisions[format] ?? -1;
  for (const button of document.querySelectorAll('[data-format]')) button.setAttribute('aria-pressed', String(button.dataset.format === format));
  if (state.rendered?.[format]) showPreview();
  else { $('preview').src = 'about:blank'; $('empty').hidden = false; }
  if (!demo && !state.loading && state.renderedRevision !== state.revision) render();
  refreshControls(); updateModelContext();
  scheduleRecovery();
}
function presentationMessage(extra = {}) {
  $('preview').contentWindow?.postMessage({matsugitPreview: previewToken, presenting: !!presentation, ...extra}, '*');
}
function exitPresentation() {
  if (!presentation) return;
  const previous = presentation; presentation = null;
  presentationMessage();
  document.body.classList.remove('presenting');
  $('presentation-controls').hidden = true;
  $('sync').checked = previous.sync;
  changeFormat(previous.format); changeLayout(previous.layout);
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  $('present').focus();
}
$('present').onclick = () => {
  if (presentation || state.loading) return;
  presentation = {format: state.format, layout: state.layout, sync: $('sync').checked};
  $('sync').checked = false;
  document.body.classList.add('presenting');
  $('presentation-controls').hidden = false;
  state.loading = true;
  changeFormat('slides'); changeLayout('render');
  state.loading = false;
  if (!demo && state.renderedRevision !== state.revision) render();
  presentationMessage(); $('preview').focus();
  // Embedded hosts may forbid fullscreen; the slide-only view still works.
  document.documentElement.requestFullscreen?.().catch(() => {});
};
$('present-exit').onclick = exitPresentation;
$('present-previous').onclick = () => presentationMessage({presentNavigate: 'prev'});
$('present-next').onclick = () => presentationMessage({presentNavigate: 'next'});
document.addEventListener('fullscreenchange', () => {
  if (!document.fullscreenElement) exitPresentation();
});
document.addEventListener('keydown', event => {
  if (!presentation) return;
  const direction = {ArrowLeft:'prev', ArrowUp:'prev', PageUp:'prev', ArrowRight:'next', ArrowDown:'next', PageDown:'next', ' ':'next'}[event.key];
  if (event.key === 'Escape') { event.preventDefault(); exitPresentation(); }
  else if (direction) { event.preventDefault(); presentationMessage({presentNavigate: direction}); }
});
for (const button of document.querySelectorAll('button[data-layout]')) button.onclick = () => changeLayout(button.dataset.layout);
for (const button of document.querySelectorAll('button[data-format]')) button.onclick = () => changeFormat(button.dataset.format);
window.addEventListener('message', event => {
  if (event.source !== $('preview').contentWindow || event.data?.matsugitPreview !== previewToken) return;
  if (event.data.presentExit) { exitPresentation(); return; }
  if (event.data.patched && pendingPatch?.id === event.data.patched) {
    pendingPatch.finish(event.data.patchError); pendingPatch = null;
  }
  if (event.data.matsugitReady) { if (!restoredPosition) followSource(); restoredPosition = false; presentationMessage(); }
  if (['slides', 'document'].includes(event.data?.matsugitFormat)) changeFormat(event.data.matsugitFormat);
  const position = event.data?.matsugitPosition;
  if (position && ['slides', 'document'].includes(position.format)
      && typeof position.hash === 'string' && position.hash.length < 1024
      && (!position.hash || position.hash.startsWith('#')) && Number.isFinite(position.scroll)) {
    state.positions[position.format] = {hash: position.hash, scroll: Math.max(0, position.scroll),
      h: Number.isInteger(position.h) && position.h >= 0 ? position.h : 0,
      v: Number.isInteger(position.v) && position.v >= 0 ? position.v : 0,
      slideId: typeof position.slideId === 'string' && position.slideId.length < 512 ? position.slideId : ''};
    if (position.format === 'slides') $('present-position').textContent = String((position.h || 0) + 1);
    scheduleRecovery();
    if ($('sync').checked && position.userNavigation && position.heading
        && Number.isFinite(position.inputTime) && position.inputTime >= sourceInput) {
      const target = position.heading;
      const matches = sourceOutline().filter(h => h.key === target.key && h.level === target.level);
      const heading = matches[target.occurrence] || matches[0];
      if (heading) {
        origin = 'preview'; followingPreview = true;
        editor.dispatch({selection: {anchor: heading.from}, effects: EditorView.scrollIntoView(heading.from, {y: 'start'})});
        followingPreview = false;
      }
    }
  }
});
function scheduleRender() {
  clearTimeout(debounce);
  if (!demo && state.layout !== 'source' && $('auto').checked) debounce = setTimeout(() => render(false), 450);
}
async function render(manual = true) {
  if (demo || state.loading) return;
  clearTimeout(debounce);
  if (state.rendering) {
    state.pendingRender ||= manual;
    if (manual) status('Latest preview queued');
    return;
  }
  const revision = state.revision, sequence = ++previewSequence;
  const format = state.format;
  const session = state.session;
  const owner = session ? {session} : {};
  const current = () => sequence === previewSequence && revision === state.revision && format === state.format;
  const cancel = job => call('matsugit_preview_cancel', {job, ...owner}).catch(() => {});
  state.pendingRender = false;
  state.rendering = true; refreshControls(); status('Preparing preview');
  try {
    const base = state.forceFull ? undefined : state.bases[format];
    state.forceFull = false;
    const initial = await call('matsugit_preview', {text: text(), name: state.name, format, base,
      theme: $('theme').value.trim(), ...owner});
    let job = initial;
    while (job.state === 'rendering') {
      if (!current()) { await cancel(initial.job); return; }
      status(job.phase || 'Rendering');
      if (!state.rendered) $('empty-label').textContent = job.phase || 'Rendering';
      await new Promise(resolve => setTimeout(resolve, base ? 100 : 350));
      if (!current()) { await cancel(initial.job); return; }
      job = await call('matsugit_preview_status', {job: initial.job, ...owner});
    }
    if (!current()) return;
    if (job.state !== 'ready') throw Error(job.error || 'Preview failed.');
    status('Loading preview');
    const parts = []; let offset = 0;
    while (true) {
      if (!current()) return;
      const part = await call('matsugit_preview_chunk', {job: initial.job, format, offset, ...owner});
      parts.push(part.chunk); offset = part.next;
      if (part.done) break;
    }
    if (current()) {
      const result = parts.join('');
      if (job.kind === 'patch') {
        try {
          if (job.base !== state.bases[format]) throw Error('Preview base expired');
          const {changes} = JSON.parse(result);
          const updated = patchedHtml(state.rendered[format], changes);
          await new Promise((resolve, reject) => {
            const timer = setTimeout(() => { pendingPatch = null; reject(Error('Preview did not acknowledge update')); }, 3000);
            pendingPatch = {id: job.job, finish: error => { clearTimeout(timer); error ? reject(Error(error)) : resolve(); }};
            $('preview').contentWindow.postMessage({matsugitPreview: previewToken,
              patch: {base: job.base, next: job.job, changes}}, '*');
          });
          // Even if the source changed during the acknowledgement, the iframe
          // now has this base. Retain it so the next patch uses the correct DOM.
          if (sequence !== previewSequence || format !== state.format) return;
          state.rendered[format] = updated;
        } catch (error) {
          if (sequence === previewSequence) { state.forceFull = true; state.pendingRender = true; }
          return;
        }
      } else {
        state.rendered ||= {};
        state.rendered[format] = result;
      }
      state.bases[format] = job.job; state.revisions[format] = revision;
      state.renderedRevision = revision;
      state.lastRefresh = {kind: job.kind, changed: job.changed, format};
      if (job.kind !== 'patch') showPreview();
      state.resolvedTheme = job.theme;
      $('theme').placeholder = job.theme ? `${job.theme} (default)` : 'Project default';
      $('theme').title = job.theme ? `Resolved theme: ${job.theme}` : 'Theme';
      if (!state.conflict) notice();
    }
  } catch (error) {
    if (current()) {
      notice(error.message); $('empty-label').textContent = 'Preview unavailable';
    }
  } finally {
    if (sequence === previewSequence) {
      state.rendering = false; refreshControls();
      if (state.pendingRender) { state.pendingRender = false; debounce = setTimeout(() => render(), 0); }
      else if (revision !== state.revision || format !== state.format) scheduleRender();
    }
  }
}
async function resourceRead({uri = state.uri, session = state.session} = {}) {
  if (uri) {
    const response = await extensions.resources.read({uri, representation: 'text'});
    const item = response.contents[0];
    const value = 'text' in item ? item.text : new TextDecoder('utf-8', {fatal: true}).decode(Uint8Array.from(atob(item.blob), char => char.charCodeAt(0)));
    return {text: value, etag: item.openaiMetadata?.etag, writable: item.openaiMetadata?.writable === true};
  }
  const result = await call('matsugit_read', {session});
  return {...result, text: result.source};
}
async function reload(force = false) {
  if ((!state.uri && !state.session) || state.loading || state.saving) return;
  const sequence = loadSequence;
  const read = ++readSequence;
  try {
    const data = await resourceRead();
    if (sequence !== loadSequence || read !== readSequence || state.saving || (!force && data.etag === state.etag)) return;
    if (dirty() && data.text !== text() && !force) {
      state.conflict = true; notice('The file changed outside this editor. Your draft is retained. Download it or reload the file.');
    } else {
      state.base = data.text; state.etag = data.etag; state.writable = data.writable;
      state.conflict = false; replaceText(data.text); notice(); scheduleRender();
      scheduleRecovery();
    }
    refreshControls();
  } catch (error) { if (sequence === loadSequence && read === readSequence) notice(error.message); }
}
async function save() {
  if ($('save').disabled) return;
  const value = text(), sequence = loadSequence;
  readSequence++;
  state.saving = true; refreshControls(); status('Saving');
  try {
    const result = state.uri ? await extensions.resources.write(state.uri, {text: value, ifMatch: state.etag})
      : await call('matsugit_save', {session: state.session, text: value, etag: state.etag});
    if (sequence !== loadSequence) return;
    if (result.outcome === 'saved') { state.base = value; state.etag = result.etag; state.conflict = false; notice(); }
    else if (result.outcome === 'conflict') {
      state.conflict = true; notice('Save refused: the file changed outside this editor. Your draft is retained.');
    } else throw Error(result.outcome === 'too-large' ? 'The file exceeds the host write limit.' : 'The host did not save the file.');
  } catch (error) { if (sequence === loadSequence) notice(error.message); }
  finally { if (sequence === loadSequence) { readSequence++; state.saving = false; refreshControls(); scheduleRecovery(); await flushRecovery(); } }
}
async function load(data) {
  if (state.saving) { notice('Wait for the current save before opening another document.'); return; }
  if (dirty() && !confirm('Discard the unsaved draft and open another document?')) return;
  await flushRecovery();
  const suppliedRecovery = data.recovery;
  const sequence = ++loadSequence;
  readSequence++;
  state.loading = true;
  recoveryId = null; recoveryGeneration = 0; recoveryPending = false; recoveryCandidate = null;
  clearTimeout(recoveryTimer); $('recovery-banner').hidden = true; $('recovery-status').textContent = '';
  editor.dispatch({effects: editability.reconfigure(editable(false))});
  origin = 'source'; outlineRevision = -1;
  clearTimeout(debounce); previewSequence++; state.rendering = false;
  disposeUpdates?.(); disposeUpdates = null;
  if (state.uri) extensions.resources?.unsubscribe({uri: state.uri}).catch(() => {});
  Object.assign(state, {uri: data.file?.resourceUri || null, session: data.session || null,
    name: data.file?.name || data.name || 'Untitled.md', conflict: false, rendered: null, renderedRevision: -1,
    resolvedTheme: null, etag: null, writable: false, pendingRender: false, saving: false,
    bases: {}, revisions: {}, forceFull: false,
    positions: {document: {hash: '', scroll: 0}, slides: {hash: '', scroll: 0}}});
  $('theme').value = ''; $('theme').placeholder = 'Project default'; $('theme').title = 'Theme';
  if (['source', 'render', 'split'].includes(data.layout)) changeLayout(data.layout);
  if (['document', 'slides'].includes(data.format)) changeFormat(data.format);
  document.querySelector('button[data-layout="source"]').textContent = state.name.toLowerCase().endsWith('.org') ? 'Org' : 'Markdown';
  $('empty').hidden = false; $('empty-label').textContent = 'Preparing preview'; $('preview').src = 'about:blank';
  if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
  try {
    if (state.uri) {
      if (!extensions.resources) throw Error('This host does not support file editing. Update Codex Desktop or use the matsugit_open tool.');
      data = await resourceRead();
    }
    if (sequence !== loadSequence) return;
    const source = data.source ?? data.text ?? '';
    if (new TextEncoder().encode(source).length > 2 * 1024 * 1024 || source.includes('\0')) throw Error('Invalid source or document exceeds the 2 MiB editor limit.');
    state.base = source; state.etag = data.etag;
    state.writable = !!data.writable; replaceText(state.base);
    editor.dispatch({selection: {anchor: 0}});
    if (!demo) {
      try {
        const recovered = await call('matsugit_recovery_begin', {...recoveryScope(), name: state.name});
        if (sequence !== loadSequence) return;
        recoveryId = recovered.id;
        const candidate = suppliedRecovery || recovered.candidate;
        if (candidate && !suppliedRecovery) {
          applyView(candidate.view);
          if (candidate.text !== candidate.base && candidate.text !== state.base) {
            recoveryCandidate = candidate;
            $('recovery-message').textContent = `Unsaved recovery copy from ${new Date(candidate.updated).toLocaleString()}`;
            $('recovery-banner').hidden = false;
          }
        }
      } catch (error) { recoveryFailure(error); }
    }
    // Restoring an existing copy must not depend on creating another backup.
    if (suppliedRecovery) applyRecovery(suppliedRecovery);
    state.loading = false;
    editor.dispatch({effects: editability.reconfigure(editable(!demo))});
    notice(state.writable && !state.etag ? 'The host supplied no file version. Saving is disabled to protect concurrent edits.' : '');
    if (state.conflict) notice('Recovered draft differs from the current file. Download the draft or reload the file; Save is blocked.');
    else if (suppliedRecovery) notice(state.writable ? 'Recovered local draft. The source file was not changed.' : 'Recovered local copy. Download to keep it; the original file is unavailable here.');
    if (state.uri) {
      disposeUpdates = extensions.resources.addUpdateHandler(({params}) => { if (params.uri === state.uri) reload(); });
      extensions.resources.subscribe({uri: state.uri}).catch(() => {});
    }
    refreshControls();
    // Do not replace the latest recovery with the file before a pending choice.
    if (!recoveryCandidate) scheduleRecovery();
    if (demo) { state.rendered = demo.rendered; showPreview(); }
    else await render();
  } catch (error) {
    if (sequence === loadSequence) {
      state.loading = false;
      editor.dispatch({effects: editability.reconfigure(editable(!demo))});
      notice(error.message); refreshControls(); status('Cannot open document');
    }
  }
}
function download() {
  const url = URL.createObjectURL(new Blob([text()], {type: 'text/plain;charset=utf-8'}));
  const link = document.createElement('a'); link.href = url; link.download = state.name;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function recoveryScope() {
  return {...(state.session ? {session: state.session} : {}), ...(state.uri ? {resourceUri: state.uri} : {})};
}
function viewState() {
  const style = document.documentElement.style;
  return {layout: state.layout, format: state.format, theme: $('theme').value, auto: $('auto').checked, sync: $('sync').checked,
    anchor: editor.state.selection.main.anchor, head: editor.state.selection.main.head, editorScroll: editor.scrollDOM.scrollTop,
    width: parseFloat(style.getPropertyValue('--source-size')) || 50, height: parseFloat(style.getPropertyValue('--source-height')) || 50,
    positions: state.positions};
}
function applyView(view) {
  if (!view) return;
  const loading = state.loading; state.loading = true;
  $('theme').value = view.theme || ''; $('auto').checked = view.auto !== false; $('sync').checked = view.sync !== false;
  changeLayout(view.layout); changeFormat(view.format);
  state.positions = view.positions; restoredPosition = true; origin = 'preview';
  document.documentElement.style.setProperty('--source-size', view.width + '%');
  document.documentElement.style.setProperty('--source-height', view.height + '%');
  $('divider').setAttribute('aria-valuenow', String(innerWidth <= 700 ? view.height : view.width));
  editor.dispatch({selection: {anchor: Math.min(view.anchor, text().length), head: Math.min(view.head, text().length)}});
  editor.requestMeasure({read: () => null, write: () => { editor.scrollDOM.scrollTop = view.editorScroll; }});
  state.loading = loading;
}
function applyRecovery(record) {
  const current = state.base;
  replaceText(record.text);
  state.conflict = state.writable && current !== record.base && current !== record.text;
  state.base = current === record.text ? current : record.base;
  applyView(record.view); recoveryCandidate = null; $('recovery-banner').hidden = true;
}
function recoveryFailure(error) {
  $('recovery-status').textContent = 'Recovery unavailable';
  $('recovery-status').title = error.message; $('recovery-status').dataset.error = 'true';
}
function scheduleRecovery() {
  if (demo || state.loading || !recoveryId) return;
  if (recoveryCandidate && !dirty()) return;
  recoveryPending = true;
  $('recovery-status').textContent = 'Recovery pending';
  clearTimeout(recoveryTimer); recoveryTimer = setTimeout(flushRecovery, 600);
}
async function flushRecovery() {
  clearTimeout(recoveryTimer);
  if (recoveryPromise) { await recoveryPromise; if (recoveryPending) return flushRecovery(); return; }
  if (demo || state.loading || !recoveryId || !recoveryPending) return;
  const id = recoveryId, sequence = loadSequence;
  recoveryPending = false;
  const snapshot = {id, generation: ++recoveryGeneration, ...recoveryScope(), text: text(), base: state.base, view: viewState()};
  recoveryPromise = (async () => {
    try {
      const result = await call('matsugit_recovery_checkpoint', snapshot);
      if (sequence !== loadSequence) return;
      $('recovery-status').dataset.error = 'false';
      $('recovery-status').textContent = recoveryPending ? 'Recovery pending' : 'Recovery saved';
      $('recovery-status').title = `Private recovery copy: ${new Date(result.updated).toLocaleString()}. Original file not saved.`;
    } catch (error) { if (sequence === loadSequence) recoveryFailure(error); }
  })();
  try { await recoveryPromise; } finally { recoveryPromise = null; }
}
async function recoveryPicker() {
  await flushRecovery();
  const container = $('recovery-items'); container.replaceChildren();
  if (!$('recovery-dialog').open) $('recovery-dialog').showModal();
  try {
    const result = await call('matsugit_recovery_list', recoveryScope());
    if (!result.items.length) container.textContent = 'No recovery copies.';
    if (result.unreadable) { const warning = document.createElement('p'); warning.textContent = `${result.unreadable} unreadable copies retained on disk.`; container.append(warning); }
    for (const item of result.items) {
      const row = document.createElement('div'); row.className = 'recovery-entry';
      const label = document.createElement('div'); label.className = 'recovery-label'; label.textContent = item.name;
      const detail = document.createElement('small'); detail.textContent = `${item.dirty ? 'Unsaved draft' : 'Saved workspace'} | ${new Date(item.updated).toLocaleString()}`;
      label.append(detail);
      if (item.owner) { const owner = document.createElement('small'); owner.textContent = item.owner; label.append(owner); }
      const restore = document.createElement('button'); restore.title = restore.ariaLabel = 'Restore ' + item.name; restore.append(createElement(RotateCcw));
      restore.onclick = async () => {
        try {
          const result = await call('matsugit_recovery_restore', {...recoveryScope(), id: item.id});
          $('recovery-dialog').close();
          if (state.uri) await restoreCopy(result.recovery);
          else await load({...result.workspace, recovery: result.recovery});
        } catch (error) { notice(error.message); }
      };
      const remove = document.createElement('button'); remove.title = remove.ariaLabel = 'Delete recovery copy'; remove.append(createElement(Trash2));
      remove.onclick = async () => {
        if (!confirm(`Delete the recovery copy of ${item.name}? The original file will not be changed.`)) return;
        try {
          await call('matsugit_recovery_forget', {...recoveryScope(), id: item.id, token: item.token});
          if (item.id === recoveryId) { recoveryId = null; recoveryPending = false; $('recovery-status').textContent = 'Recovery paused'; }
          await recoveryPicker();
        } catch (error) { notice(error.message); }
      };
      row.append(label, restore, remove); container.append(row);
    }
  } catch (error) { container.textContent = error.message; }
}
$('recover').onclick = recoveryPicker;
$('close-recovery').onclick = () => $('recovery-dialog').close();
async function restoreCopy(record) {
  if (!record || state.loading || state.saving) return;
  if (dirty() && !confirm('Replace the current draft with this recovery copy?')) return;
  await flushRecovery();
  const sequence = loadSequence;
  state.loading = true; readSequence++;
  editor.dispatch({effects: editability.reconfigure(editable(false))});
  // Re-read disk before restoring so a change during the offer cannot bypass Save checks.
  try {
    if (state.uri || state.session) {
      const current = await resourceRead();
      if (sequence !== loadSequence) return;
      state.base = current.text; state.etag = current.etag; state.writable = current.writable;
    }
    applyRecovery(record);
  } catch (error) { notice(error.message); return; }
  finally {
    if (sequence === loadSequence) {
      state.loading = false; editor.dispatch({effects: editability.reconfigure(editable(!demo))});
    }
  }
  notice(state.conflict ? 'Recovered draft differs from the current file. Download it or reload the file; Save is blocked.' : 'Recovered local draft. The source file was not changed.');
  scheduleRecovery(); refreshControls(); await flushRecovery(); render();
}
$('restore-draft').onclick = async () => {
  if (!recoveryCandidate) return;
  try {
    const result = await call('matsugit_recovery_restore', {...recoveryScope(), id: recoveryCandidate.id});
    await restoreCopy(result.recovery);
  } catch (error) { notice(error.message); }
};
$('dismiss-recovery').onclick = () => { recoveryCandidate = null; $('recovery-banner').hidden = true; scheduleRecovery(); };
editor.scrollDOM.addEventListener('scroll', scheduleRecovery, {passive: true});
document.addEventListener('visibilitychange', () => { if (document.hidden) flushRecovery(); });
window.addEventListener('pagehide', flushRecovery);
setInterval(() => { if (recoveryPending) flushRecovery(); }, 2000);
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
$('insert').onclick = () => insertMenu(editor);
$('undo').onclick = () => undo(editor); $('redo').onclick = () => redo(editor);
$('refresh').onclick = event => { state.forceFull ||= event.shiftKey; render(); }; $('auto').onchange = () => { scheduleRender(); scheduleRecovery(); };
$('sync').onchange = () => { if ($('sync').checked) { origin = 'source'; followSource(); } scheduleRecovery(); };
$('theme').onchange = () => { state.revision++; refreshControls(); scheduleRender(); scheduleRecovery(); };
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
window.addEventListener('beforeunload', event => { flushRecovery(); if (dirty() && !demo) { event.preventDefault(); event.returnValue = ''; } });
function resize(value) {
  const percent = Math.max(20, Math.min(80, value));
  document.documentElement.style.setProperty(innerWidth <= 700 ? '--source-height' : '--source-size', percent + '%');
  $('divider').setAttribute('aria-valuenow', String(Math.round(percent))); editor.requestMeasure();
  scheduleRecovery();
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
document.modelContext?.registerTool({name: 'matsugit_get_source', description: 'Read the current workspace draft, including unsaved edits.',
  inputSchema: {type: 'object', properties: {}}, annotations: {readOnlyHint: true},
  async execute() { return JSON.stringify({name: state.name, text: text(), revision: state.revision, dirty: dirty()}); }});
document.modelContext?.registerTool({name: 'matsugit_replace_source', description: 'Replace the workspace draft only when its revision matches. Does not save or publish.',
  inputSchema: {type: 'object', properties: {text: {type: 'string'}, revision: {type: 'integer'}}, required: ['text','revision']},
  async execute(args) {
    if (demo || state.loading || args.revision !== state.revision) throw Error('Draft changed or is loading; read the current revision first.');
    if (new TextEncoder().encode(args.text).length > 2 * 1024 * 1024) throw Error('Document exceeds 2 MiB.');
    editor.dispatch({changes: {from: 0, to: editor.state.doc.length, insert: args.text}});
    return JSON.stringify({revision: state.revision, saved: false});
  }});
// Expose only the editor model to the isolated local UI test harness.
window.matsugitWorkspace = {editor, state, load, render, save, reload, flushRecovery};
async function boot() {
if (demo) {
  await load(demo);
  for (const id of ['open','save','undo','redo','refresh','auto','theme','insert','recover']) $(id).disabled = true;
} else {
  app.addEventListener('toolinput', ({arguments: args}) => {
    if (args?.file && args.file.resourceUri !== state.uri) load(args);
  });
  app.ontoolresult = result => {
    const data = {...result.structuredContent, ...result._meta};
    if (data.file && data.file.resourceUri === state.uri) return;
    if (data.session && data.session === state.session) { reload(); return; }
    if (!data.file && !(data.name && (typeof data.source === 'string' || typeof data.text === 'string'))) return;
    load(data);
  };
  app.addEventListener('hostcontextchanged', hostContext);
  try { await app.connect(); hostContext(app.getHostContext()); }
  catch (error) { notice(error.message); status('Host connection unavailable'); }
  setInterval(() => { if (state.session || state.uri) reload(); }, 3000);
}
}
boot().catch(error => { notice(error.message); status('Workspace unavailable'); });
