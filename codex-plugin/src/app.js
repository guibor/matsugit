import {App, applyDocumentTheme, applyHostStyleVariables} from '@modelcontextprotocol/ext-apps';
import {hostResultData, sourceText} from './host-results.mjs';
import {cursorHost, inlineEditorHeight} from './host-view.mjs';
import {version} from '../package.json';
import {OpenAIExtensions} from '@openai/mcp-extensions/app';
import {EditorView, basicSetup} from 'codemirror';
import {keymap} from '@codemirror/view';
import {markdown} from '@codemirror/lang-markdown';
import {GFM} from '@lezer/markdown';
import {foldEffect, unfoldEffect, foldedRanges} from '@codemirror/language';
import {undo, redo, undoDepth, redoDepth, isolateHistory} from '@codemirror/commands';
import {EditorState, Compartment, Transaction, ChangeSet} from '@codemirror/state';
import {gallery} from './gallery.mjs';
import {share} from './share.mjs';
import {slideRail} from './slide-rail.mjs';
import {textChanges, savedEditHistory, planExternalEdit, wholeFileReview} from './external-edits.mjs';
import {checkPanel} from './check-panel.mjs';
import {rendererFinding} from './check.mjs';
import {createElement, SlidersHorizontal, Ellipsis, FileText, FolderOpen, Save, Download, Undo2, Redo2, RefreshCw, PanelsTopLeft, Plus, History, RotateCcw, Trash2, X, Braces, Presentation, ChevronLeft, ChevronRight, Minimize2, Maximize2, Copy, Table2, Check, LoaderCircle, GitCompareArrows} from 'lucide';
import {previewHtml, patchedHtml} from './preview.js';
import {structure, headingTargets} from './structure.mjs';
import {authoringExtensions, recipeCatalogue, compactMarkup, slideSeparators} from './authoring.mjs';
import {installRoleHelp} from './role-help.mjs';
import {delivery} from './delivery.js';
import {visualExtensions, visualMode} from './visual.mjs';
import {tableDialog} from './table-dialog.js';
import {setOutlineDepth, outlineKeys} from './outline.mjs';
import {updateThemePicker} from './theme-picker.mjs';
import {mergeResult} from './merge-result.mjs';
import {mergeDialog} from './merge-dialog.mjs';
import {saveStatus, paintSaveStatus, changeNotice} from './save-status.mjs';
import {changeReview} from './change-review.mjs';
import {publicationStatus} from './publication-status.mjs';
import {storyView} from './story.mjs';
import {slideAgent} from './slide-agent.mjs';
import {slideAgentSender} from './slide-agent-request.mjs';
import {fileDownloads} from './download.mjs';

const $ = id => document.getElementById(id);
const app = new App({name: 'matsugit', version});
const extensions = new OpenAIExtensions(app);
const demo = window.MATSUGIT_DEMO;
const downloadFile = fileDownloads(demo ? null : app);
const state = {name: 'Untitled.md', base: '', etag: null, writable: false, conflict: false,
  path:null, autosave:false, editorMode:'raw', storyPreview:false, storyMode:'overview', storySize:'large',
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
let tables;
let story;
let check;
let railMoved;
let publication;
let refreshRequested = false, copying = false, feedbackTimer;
let incomingDocument = null;
let noticeMessage = '';
let lastModelContext = '', currentHostContext = {}, changingDisplayMode = false;
let mergeAttempt = null;
const savedHistory = savedEditHistory();
// True once the undo history holds a change that replaced most of the document.
let wholesaleHistory = false;
const mergeReview = mergeDialog();
const externalReview = changeReview();
let externalChange = null;
let themeCatalog = {}, themeSequence = 0;
async function refreshThemes() {
  if (demo) return;
  const sequence = ++themeSequence, documentSequence = loadSequence;
  $('theme').setAttribute('aria-busy', 'true');
  try {
    const catalog = await call('matsugit_themes', state.session ? {session: state.session} : {});
    if (sequence !== themeSequence || documentSequence !== loadSequence) return;
    themeCatalog = catalog;
    updateThemePicker($('theme'), catalog);
    $('theme').title = 'Installed themes; default follows this document\'s configuration';
  } catch (error) {
    if (sequence === themeSequence && documentSequence === loadSequence)
      $('theme').title = `Theme discovery failed: ${error.message}. Refresh to retry.`;
  } finally {
    if (sequence === themeSequence) $('theme').setAttribute('aria-busy', 'false');
  }
}
const actionTimers = new Map();
function actionFeedback(id, phase, message) {
  const button = $(id);
  clearTimeout(actionTimers.get(id));
  button.dataset.feedback = phase;
  button.setAttribute('aria-busy', String(phase === 'busy'));
  button.replaceChildren(createElement(phase === 'busy' ? LoaderCircle : phase === 'done' ? Check : phase === 'error' ? X : id === 'copy-path' ? Copy : RefreshCw));
  if (message) {
    clearTimeout(feedbackTimer);
    $('action-feedback').textContent = message;
    $('action-feedback').hidden = false;
    feedbackTimer = setTimeout(() => { $('action-feedback').hidden = true; }, 4000);
  }
  if (phase === 'done' || phase === 'error') actionTimers.set(id, setTimeout(() => actionFeedback(id, ''), 2500));
}
const text = () => editor.state.doc.toString();
const dirty = () => text() !== state.base;
function paintNotice() {
  const receipt = changeNotice(state, dirty());
  const message = noticeMessage || (incomingDocument ? 'Another document is waiting. Your current draft is retained.' : receipt?.detail || '');
  // The open Check list already says why the preview stopped; do not repeat it.
  $('notice').hidden = !message || (message === state.renderNotice && !$('check-panel').hidden);
  $('notice').dataset.kind = state.conflict ? 'review' : 'info';
  $('notice-title').hidden = !receipt;
  $('notice-title').textContent = receipt?.title || '';
  $('notice-text').textContent = message;
  $('notice-check').hidden = !state.renderError || noticeMessage !== state.renderNotice;
  $('reload').hidden = !state.conflict && !incomingDocument && !(state.fileReceipt && externalChange);
  $('reload').disabled = state.loading || state.saving || state.merging || state.delivering || tables?.pending();
  $('reload').title = state.conflict ? 'Compare your draft with the saved file before writing' : 'Review the latest file changes';
  $('notice-save').hidden = !state.fileReceipt || state.conflict || !dirty();
  $('notice-save').disabled = $('save').disabled;
  $('notice-dismiss').hidden = !state.fileReceipt || state.conflict || !!incomingDocument;
}
const notice = (message = '') => { noticeMessage = message; paintNotice(); };
const status = message => { $('status').textContent = message; };
const editability = new Compartment();
const setup = new Compartment();
const editable = value => [EditorState.readOnly.of(!value), EditorView.editable.of(value)];
const editor = new EditorView({parent: $('editor'), extensions: [setup.of(basicSetup), markdown({extensions:GFM}), EditorView.lineWrapping,
  authoringExtensions({isOrg: () => state.name.toLowerCase().endsWith('.org'), enabled: () => !demo && !state.loading, onError: notice}),
  visualExtensions({isOrg:()=>state.name.toLowerCase().endsWith('.org'), enabled:()=>!demo&&!state.loading,
    open:(range,placement)=>tables.open(range,null,placement),preview:source=>tables.preview(source),detach:root=>tables.detach(root)}),
  keymap.of([{key:'Alt-.',run:()=>{tables.atSelection();return true;}}]),
  outlineKeys(() => state.name.toLowerCase().endsWith('.org')),
  editability.of(editable(!demo)),
  EditorView.contentAttributes.of({'aria-label': 'Markdown source'}),
  EditorView.domEventHandlers({focus: () => { sourceInput = Date.now(); }}),
  EditorView.updateListener.of(update => {
    if (update.docChanged || update.transactions.some(tr => tr.effects.some(e => e.is(foldEffect) || e.is(unfoldEffect)))) {
      for (const button of document.querySelectorAll('[data-depth]'))
        button.setAttribute('aria-pressed', String(button.dataset.depth === '0' && !foldedRanges(update.state).size));
    }
    if (update.docChanged && !state.loading) { state.revision++; refreshControls(); scheduleRender(); }
    if (update.docChanged) check?.schedule();
    // Undoing such a change would also take back whatever another writer put
    // inside the replaced range, so external changes then rebase the history.
    for (const tr of update.transactions) if (tr.docChanged && !state.loading && tr.annotation(Transaction.addToHistory) !== false)
      tr.changes.iterChangedRanges((from, to) => { if (to - from > 40 && to - from >= tr.startState.doc.length / 2) wholesaleHistory = true; });
    if (update.docChanged && !state.loading) scheduleAutosave();
    if ((update.docChanged || update.selectionSet) && !state.loading) scheduleRecovery();
    if ((update.selectionSet || update.docChanged) && !state.loading && !followingPreview) {
      origin = 'source'; clearTimeout(followTimer); followTimer = setTimeout(followSource, 180);
      sourceInput = Date.now();
    }
    const line = update.state.doc.lineAt(update.state.selection.main.head);
    $('location').textContent = `Ln ${line.number}, Col ${update.state.selection.main.head - line.from + 1}`;
    story?.update(update);
    if (update.selectionSet && !update.docChanged) railMoved?.();
  }),
]});
installRoleHelp($('editor'), $('role-help'));
for (const [id, icon] of Object.entries({'brand-icon': FileText, 'empty-icon': PanelsTopLeft,
  open: FolderOpen, save: Save, download: Download, undo: Undo2, redo: Redo2, refresh: RefreshCw, insert: Plus,
  recover: History, 'close-recovery': X, 'compact-markup': Braces, present: Presentation,
  'present-previous': ChevronLeft, 'present-next': ChevronRight, 'present-exit': Minimize2,
  'copy-path':Copy, 'edit-table':Table2, 'external-review':GitCompareArrows, 'notice-dismiss':X})) $(id).append(createElement(icon));
$('insert').append('Add');
$('more').append(createElement(Ellipsis));
$('view-options').append(createElement(SlidersHorizontal));
$('view-options').onclick = () => {
  const open = $('source-pane').dataset.options !== 'true';
  $('source-pane').dataset.options = String(open); $('view-options').setAttribute('aria-pressed', String(open));
};
function moreMenu(open) {
  $('more-panel').hidden = !open; $('more').setAttribute('aria-expanded', String(open));
}
$('more').onclick = () => moreMenu($('more-panel').hidden);
$('more-panel').addEventListener('click', event => { if (event.target.closest('button')) moreMenu(false); });
document.addEventListener('pointerdown', event => { if (!$('more-wrap').contains(event.target)) moreMenu(false); });
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('more-panel').hidden) { moreMenu(false); $('more').focus(); } });
// Autosave: write the draft to its file shortly after typing stops. It uses
// the same version-checked Save, so a newer file is never overwritten; it
// waits while a table edit, merge, review or share is in progress.
let autosaveTimer;
function scheduleAutosave() {
  clearTimeout(autosaveTimer);
  if (demo || !state.autosave || !state.writable || !state.etag) return;
  autosaveTimer = setTimeout(async () => {
    if (!state.autosave || state.conflict || !dirty()) return;
    if (state.loading || state.saving || state.merging || state.delivering || tables.pending()) { scheduleAutosave(); return; }
    await save({review: false, auto: true});
  }, 1500);
}
$('autosave').onchange = () => { state.autosave = $('autosave').checked; refreshControls(); scheduleAutosave(); scheduleRecovery(); };
$('workspace-version').textContent = version;
$('workspace-version').title = `matsugit workspace ${version}`;
tables=tableDialog({editor,state,call,changed:()=>{scheduleRecovery();if(tables)refreshControls();},notice,downloadFile,enabled:()=>!demo&&!state.loading});
const agentSlide = slideAgent({
  snapshot:()=>({...state,text:text(),generation:loadSequence}),
  enabled:()=>!demo&&!state.loading&&!state.merging&&!state.saving&&!state.delivering&&!tables.pending(),
  save, read:resourceRead, notice,
  path:async()=>state.path || (await call('matsugit_path',state.session?{session:state.session}:{})).path,
  sender:()=>slideAgentSender(app,extensions),
});
story=storyView({editor,state,notice,changed:scheduleRecovery,
  askAgent:node=>agentSlide.open(node),
  enabled:()=>!demo&&!state.loading&&!state.merging&&!state.saving&&!tables.pending(),
  sourceView:from=>{
    changeLayout('source');
    const effects=[EditorView.scrollIntoView(from,{y:'center'})];
    foldedRanges(editor.state).between(0,editor.state.doc.length,(start,end)=>{
      if (from > start && from <= end) effects.push(unfoldEffect.of({from:start,to:end}));
    });
    editor.dispatch({selection:{anchor:from},effects});editor.focus();
  }});
// Show a source position, opening the editor if a preview-only view hides it.
function showSource(from) {
  if (state.layout === 'story' || state.layout === 'render') changeLayout('split');
  const effects = [EditorView.scrollIntoView(from, {y: 'center'})];
  foldedRanges(editor.state).between(0, editor.state.doc.length, (start, end) => {
    if (from > start && from <= end) effects.push(unfoldEffect.of({from: start, to: end}));
  });
  editor.dispatch({selection: {anchor: from}, effects}); editor.focus();
}
const isOrg = () => state.name.toLowerCase().endsWith('.org');
const editing = () => !demo && !state.loading && !state.merging && !state.saving && !tables.pending();
const rail = slideRail({root: $('slide-rail'), text: () => editor.state.doc.toString(), isOrg,
  position: () => editor.state.selection.main.head,
  jump: from => {
    if (state.loading) return;
    if (state.layout === 'story') changeLayout('split');
    editor.dispatch({selection: {anchor: from}, effects: EditorView.scrollIntoView(from, {y: 'start', yMargin: 8})});
    followSource(true);
    if (state.layout !== 'render') editor.focus();
  }});
railMoved = rail.moved;
check = checkPanel({editor, isOrg, enabled: editing, renderError: () => state.renderError, show: showSource, toggled: paintNotice, changed: list => rail.findings(list),
  askAgent: (slide, suggestion) => agentSlide.open(slide, suggestion)});
const layouts = gallery({editor, recipes: recipeCatalogue, isOrg, enabled: editing, notice,
  reveal: () => { if (state.layout === 'story' || state.layout === 'render') changeLayout('split'); }});
$('notice-check').onclick = () => check.open();
$('story-preview').onchange=()=>{
  state.storyPreview=$('story-preview').checked;
  changeLayout('story');
};
$('edit-table').onclick=()=>tables.atSelection();
function changeEditorMode(mode) {
  state.editorMode=state.name.toLowerCase().endsWith('.org')?'raw':mode;
  for(const button of document.querySelectorAll('[data-editor]')) {
    button.setAttribute('aria-pressed',String(button.dataset.editor===state.editorMode));
    button.disabled=button.dataset.editor==='visual' && state.name.toLowerCase().endsWith('.org');
    button.title=button.disabled?'Visual prose editing is available for Markdown; Org source is preserved':'';
  }
  const visual=state.editorMode==='visual';
  $('source-pane').dataset.mode=state.editorMode;
  $('compact-markup').setAttribute('aria-pressed',String(visual));
  editor.dispatch({effects:[visualMode.of(visual),compactMarkup.of(visual)]});scheduleRecovery();
}
for(const button of document.querySelectorAll('[data-editor]')) button.onclick=()=>changeEditorMode(button.dataset.editor);
$('slide-separators').onchange = () => {
  editor.dispatch({effects: slideSeparators.of($('slide-separators').checked)});
  scheduleRecovery();
};
$('copy-path').onclick=async()=>{
  if (copying) return;
  copying = true; actionFeedback('copy-path', 'busy'); refreshControls();
  try {
    let path=state.path;
    if(!path && (state.session || state.uri)) path=(await call('matsugit_path',state.session?{session:state.session}:{})).path;
    if(!path)throw Error('The host has not provided a local path for this document.');
    try { await navigator.clipboard.writeText(path); }
    catch {
      const input=document.createElement('textarea');input.value=path;input.style.position='fixed';input.style.opacity='0';document.body.append(input);input.select();
      const copied=document.execCommand('copy');input.remove();
      if(!copied)throw Error('Clipboard access was blocked. Document path: '+path);
    }
    status('Document path copied'); actionFeedback('copy-path', 'done', 'Document path copied');
  } catch(error){notice(error.message); actionFeedback('copy-path', 'error', 'Could not copy path');}
  finally { copying = false; refreshControls(); }
};
$('compact-markup').onclick = () => {
  const compact = $('compact-markup').getAttribute('aria-pressed') !== 'true';
  $('compact-markup').setAttribute('aria-pressed', String(compact));
  editor.dispatch({effects:compactMarkup.of(compact)});
};

async function call(name, args) {
  const response = await app.callServerTool({name, arguments: args});
  return hostResultData(response);
}
function refreshControls() {
  story?.refresh();
  publication?.update();
  $('external-review').disabled = !externalChange || state.loading || state.saving || state.merging || tables.pending();
  const headings = sourceOutline();
  const maxDepth = Math.max(0, ...headings.map(h => h.level));
  for (const button of document.querySelectorAll('[data-depth]')) {
    const depth = Number(button.dataset.depth);
    button.hidden = depth > maxDepth;
    button.disabled = state.loading || (depth > 0 && !headings.some(h => h.level <= depth));
  }
  $('edit-table').disabled=demo || state.loading;
  for(const button of document.querySelectorAll('.ff-visual-table>div:first-child>button')) button.disabled=demo || state.loading;
  $('copy-path').disabled=copying || (!state.path&&!state.uri&&!state.session);
  $('copy-path').title=state.path?'Copy document path: '+state.path:'Copy document path';
  $('present').title = state.format === 'slides' ? 'Present slides' : 'Present document';
  $('present').setAttribute('aria-label', $('present').title);
  $('dirty').hidden = !dirty();
  paintSaveStatus($('save-state'), saveStatus(state, dirty(), tables.pending()));
  $('save').disabled = !!demo || state.loading || state.saving || state.merging || state.delivering || tables.pending() || !state.writable || !state.etag || (!state.conflict && !dirty());
  $('save').title = tables.pending() ? 'Apply table edits to the draft first' : state.conflict ? 'Review changes before saving' : 'Save file';
  $('save').setAttribute('aria-label', $('save').title);
  $('refresh').disabled = !!demo || state.loading || state.refreshing || state.saving || state.merging;
  $('refresh').title = state.rendering ? 'Queue latest preview' : 'Refresh from file (Shift: rebuild preview)';
  $('refresh').setAttribute('aria-label', $('refresh').title);
  // A published source is always called source.md; its folder is its name.
  const folder = /^source\.(md|org)$/.test(state.name) && state.path ? state.path.split(/[\\/]/).at(-2) + '/' : '';
  $('filename').textContent = folder + state.name;
  $('filename').title = state.path || state.name;
  paintNotice();
  if (!state.rendering && !state.saving) status(state.conflict ? 'External changes detected'
    : state.rendered && state.renderedRevision !== state.revision ? 'Preview out of date'
    : dirty() ? 'Unsaved draft' : demo ? 'Read-only design preview' : state.etag ? 'Saved to file' : 'Local draft');
  updateModelContext();
}
for (const button of document.querySelectorAll('[data-depth]')) button.onclick = () => {
  setOutlineDepth(editor, Number(button.dataset.depth), state.name.toLowerCase().endsWith('.org'));
  for (const other of document.querySelectorAll('[data-depth]')) other.setAttribute('aria-pressed', String(other === button));
};
function replaceText(value, {baseline = false} = {}) {
  const selection = editor.state.selection.main;
  const wasLoading = state.loading;
  state.loading = true;
  // A new file baseline starts a new undo history. Never map old undo entries
  // through a whole-file disk replacement, or join it with the user's typing.
  if (baseline) { editor.dispatch({effects: setup.reconfigure([])}); wholesaleHistory = false; }
  editor.dispatch({changes: {from: 0, to: editor.state.doc.length, insert: value},
    annotations: [isolateHistory.of('full'), Transaction.addToHistory.of(!baseline)],
    selection: {anchor: Math.min(selection.anchor, value.length), head: Math.min(selection.head, value.length)}});
  if (baseline) editor.dispatch({effects: setup.reconfigure(basicSetup)});
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
function followSource(explicit = false) {
  if ((!explicit && (!$('sync').checked || origin !== 'source')) || !state.rendered) return;
  $('preview').contentWindow?.postMessage({matsugitPreview: previewToken,
    targets: headingTargets(sourceOutline(), editor.state.selection.main.head)}, '*');
}
function changeLayout(layout) {
  if (layout !== 'story') story?.finish();
  state.layout = layout;
  $('workspace').dataset.layout = layout;
  $('workspace').dataset.storyPreview = String(state.storyPreview);
  $('app').dataset.storyFocused = String(layout === 'story' && !state.storyPreview);
  $('story-pane').hidden = layout !== 'story';
  $('story-preview').checked = !!state.storyPreview;
  story?.refresh();
  for (const button of document.querySelectorAll('[data-layout]')) if (button.tagName === 'BUTTON') button.setAttribute('aria-pressed', String(button.dataset.layout === layout));
  editor.requestMeasure(); updateModelContext();
  scheduleRecovery();
  if (!demo && !state.loading && previewVisible() && state.renderedRevision !== state.revision) render();
}
function previewVisible() { return state.layout !== 'source' && (state.layout !== 'story' || state.storyPreview); }
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
  for (const [id, label] of [['present-previous', 'Previous'], ['present-next', 'Next']]) {
    $(id).title = label + (state.format === 'slides' ? ' slide' : ' page');
    $(id).setAttribute('aria-label', $(id).title);
  }
  $('present-position').textContent = state.format === 'slides' ? String((state.positions.slides.h || 0) + 1) : '';
  state.loading = true;
  changeLayout('render');
  state.loading = false;
  if (!demo && state.renderedRevision !== state.revision) render();
  presentationMessage(); $('preview').focus();
  // Embedded hosts may forbid fullscreen; the content-only view still works.
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
  const wanted = event.data.matsugitEdit;
  if (wanted && !presentation && wanted.heading && typeof wanted.text === 'string') {
    // Find the double-clicked words inside the slide they were shown on.
    const outline = sourceOutline(), matches = outline.filter(h => h.key === wanted.heading.key && h.level === wanted.heading.level);
    const heading = matches[wanted.heading.occurrence] || matches[0];
    if (heading) {
      const next = outline.find(h => h.from > heading.from && h.level <= Math.min(2, heading.level));
      const body = text().slice(heading.from, next ? next.from : undefined), words = wanted.text.split(' ').filter(Boolean);
      let at = -1;
      for (const count of [8, 5, 3, 2, 1]) if (at < 0 && words.length >= Math.min(count, 1)) at = body.indexOf(words.slice(0, count).join(' '));
      showSource(heading.from + Math.max(0, at));
    }
    return;
  }
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
    if (position.userNavigation && position.heading
        && Number.isFinite(position.inputTime) && position.inputTime >= sourceInput) {
      const target = position.heading;
      const matches = sourceOutline().filter(h => h.key === target.key && h.level === target.level);
      const heading = matches[target.occurrence] || matches[0];
      if (heading) {
        if ($('sync').checked) {
          origin = 'preview'; followingPreview = true;
          editor.dispatch({selection: {anchor: heading.from}, effects: EditorView.scrollIntoView(heading.from, {y: 'start'})});
          followingPreview = false;
        }
        rail.previewMoved(heading.from);
      }
    }
  }
});
function scheduleRender() {
  clearTimeout(debounce);
  if (!demo && previewVisible() && $('auto').checked) debounce = setTimeout(() => render(false), 450);
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
  actionFeedback('refresh', 'busy');
  let completed = false;
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
      if (!themeCatalog.default && !$('theme').value && job.theme) {
        themeCatalog.default = job.theme;
        updateThemePicker($('theme'), themeCatalog);
      }
      state.renderError = null; $('preview-stale').hidden = true; check.refresh();
      if (!state.conflict) notice();
      completed = true;
    }
  } catch (error) {
    if (current()) {
// Say it in slide words, keep the last good preview visibly marked as old,
      // and point at the list that explains where the problem is.
      state.renderError = error.message;
      state.renderNotice = "The preview can't update yet. " + check.refresh().find(item => item.severity === 'problem').message;
      notice(state.renderNotice); $('empty-label').textContent = 'Preview unavailable';
      $('preview-stale').hidden = !state.rendered?.[format];
      if (refreshRequested) { refreshRequested = false; actionFeedback('refresh', 'error', 'Preview failed'); }
    }
  } finally {
    if (sequence === previewSequence) {
      state.rendering = false; refreshControls();
      if (completed && !state.pendingRender && current() && refreshRequested) {
        refreshRequested = false; actionFeedback('refresh', 'done', 'Preview refreshed');
      } else if (!state.pendingRender && $('refresh').dataset.feedback === 'busy') actionFeedback('refresh', '');
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
  return {...result, text: sourceText(result)};
}
async function reload(force = false, manual = false, expectedEtag = null) {
  if ((!state.uri && !state.session) || state.loading || state.saving || state.merging || (state.refreshing && !manual)) return false;
  const sequence = loadSequence;
  const read = ++readSequence;
  const revision = state.revision, table = JSON.stringify(tables.snapshot());
  try {
    const data = await resourceRead();
    if (sequence !== loadSequence || read !== readSequence || state.saving) return false;
    if (force && expectedEtag !== null && data.etag !== expectedEtag) {
      notice('The incoming file changed again. Nothing was replaced; review the new version first.');
      return false;
    }
    if (force && (state.revision !== revision || JSON.stringify(tables.snapshot()) !== table)) {
      notice('Your draft changed while reading the file. Nothing was replaced; review the versions again.');
      return false;
    }
    if (!force && data.etag === state.etag) return !state.conflict;
    if (!force && data.text !== state.base && externalChange?.data.etag !== data.etag) {
      externalChange = {base:state.base, local:text(), incoming:data.text, data, appliedText:null};
    }
    if ((state.conflict || dirty() || savedHistory.pending || tables.pending() || undoDepth(editor.state) || redoDepth(editor.state)) && data.text !== text() && !force) {
      // The author has typed here and another writer changed the file. Combine
      // the two without asking whenever they do not touch the same lines.
      const key = `${state.revision}:${data.etag}`;
      const settled = !redoDepth(editor.state) && !tables.pending() && !incomingDocument
        && !$('incoming-dialog').open && !mergeReview.isOpen() && !externalReview.isOpen();
      if (!settled || mergeAttempt === key) { state.conflict = true; notice(); }
      else {
        mergeAttempt = key;
        const snapshot = mergeSnapshot();
        state.merging = true; refreshControls();
        let retry = false;
        try {
          const decision = await planExternalEdit({base:snapshot.base, local:snapshot.text, incoming:data.text,
            history:savedHistory, merge:async (base, local, incoming) => {
              checkMergeSnapshot(snapshot);
              return (await call('matsugit_merge', {base, local, incoming})).merge;
            }});
          checkMergeSnapshot(snapshot);
          if (decision.review) {
            state.ancestor = decision.base; state.reviewWhole = !!decision.whole;
            state.ambiguousExternal = !!decision.ambiguous; state.conflict = true; notice();
          } else await applyExternal(data, decision.text, snapshot, decision.versions);
        } catch(error) {
          // Typing during the merge is not a conflict: try again in a moment.
          if (sequence === loadSequence && state.revision !== snapshot.revision) { mergeAttempt = null; retry = true; }
          else if (sequence === loadSequence) { state.conflict = true; notice(`Draft retained. ${error.message}`); }
        }
        finally { state.merging = false; }
        if (retry) setTimeout(() => reload(), 500);
      }
    } else {
      if (force) savedHistory.clear();
      state.base = data.text; state.etag = data.etag; state.writable = data.writable;
      state.saveError = null; state.lastSavedAt = null;
      state.conflict = false; state.ancestor = null; state.reviewWhole = false; state.ambiguousExternal = false;
      if (data.text !== text()) { tables.reset(); replaceText(data.text, {baseline:true}); state.fileReceipt = 'updated'; }
      if (externalChange?.data.etag === data.etag) externalChange.appliedText = data.text;
      notice(); scheduleRender();
      scheduleRecovery();
    }
    refreshControls();
    return !state.conflict;
  } catch (error) { if (sequence === loadSequence && read === readSequence) notice(error.message); return false; }
}
function mergeSnapshot() {
  return {sequence:loadSequence, revision:state.revision, text:text(), base:state.base,
    mergeBase:state.ancestor ?? state.base, reviewWhole:state.reviewWhole, view:viewState()};
}
function checkMergeSnapshot(snapshot) {
  if (snapshot.sequence !== loadSequence || snapshot.revision !== state.revision || snapshot.base !== state.base
      || JSON.stringify(snapshot.view.tableDraft) !== JSON.stringify(tables.snapshot()) || incomingDocument)
    throw Error('The draft changed. Nothing was replaced; review the versions again.');
  if (tables.pending()) throw Error('Apply or cancel the table edit before merging.');
}
async function applyMerged(data, merged, snapshot, receipt = 'reviewed') {
  checkMergeSnapshot(snapshot);
  if (!data.etag) throw Error('The host did not provide a file version; cannot safely apply this merge.');
  if (new TextEncoder().encode(merged).length > 2 * 1024 * 1024) throw Error('Merged draft exceeds the 2 MiB editor limit.');
  const copy = await call('matsugit_recovery_begin', {...recoveryScope(), name:state.name});
  await call('matsugit_recovery_checkpoint', {...recoveryScope(), id:copy.id, generation:0,
    text:snapshot.text, base:snapshot.base, view:snapshot.view});
  const latest = await resourceRead();
  checkMergeSnapshot(snapshot);
  if (latest.etag !== data.etag || latest.text !== data.text)
    throw Error('The file changed again. Draft retained; reopen Review changes for the latest version.');
  // Rebase undo onto the incoming file. Undo removes only our merged edits,
  // never the agent's newly accepted changes or the entire initial document.
  replaceText(latest.text, {baseline:true});
  state.base = latest.text; state.etag = latest.etag; state.writable = latest.writable;
  state.saveError = null; state.lastSavedAt = null;
  if (merged !== latest.text) replaceText(merged);
  if (externalChange?.data.etag === data.etag) externalChange.appliedText = merged;
  state.conflict = false; state.ancestor = null; state.reviewWhole = false; state.ambiguousExternal = false; savedHistory.clear();
  state.fileReceipt = receipt;
  notice();
  scheduleRecovery(); scheduleRender(); refreshControls();
}
// Bring another writer's change into the open editor as small edits, so the
// cursor stays put, typing continues, and Undo still undoes only the author's
// own changes. `merged` is the incoming file, plus the author's text when the
// two were combined; a difference from the file is then saved as usual.
async function applyExternal(data, merged, snapshot, history) {
  checkMergeSnapshot(snapshot);
  if (!data.etag) throw Error('The host did not provide a file version; cannot safely combine the changes.');
  if (new TextEncoder().encode(merged).length > 2 * 1024 * 1024) throw Error('Combined draft exceeds the 2 MiB editor limit.');
  if (snapshot.text !== data.text && (snapshot.text !== snapshot.base || savedHistory.pending)) {
    const copy = await call('matsugit_recovery_begin', {...recoveryScope(), name:state.name});
    await call('matsugit_recovery_checkpoint', {...recoveryScope(), id:copy.id, generation:0,
      text:snapshot.text, base:snapshot.base, view:snapshot.view});
  }
  const latest = await resourceRead();
  checkMergeSnapshot(snapshot);
  if (latest.etag !== data.etag || latest.text !== data.text) throw Error('The file changed again.');
  const changes = textChanges(text(), merged);
  if (changes.length && !wholesaleHistory) {
    // Outside the undo history: Undo keeps taking back the author's own edits.
    const wasLoading = state.loading;
    state.loading = true;
    editor.dispatch({changes, annotations: Transaction.addToHistory.of(false)});
    state.loading = wasLoading; state.revision++;
  } else if (changes.length) {
    // Rebase undo onto the incoming file, as one step for the author's part,
    // so Undo can never erase the other writer's change. Keep the cursor.
    const moved = ChangeSet.of(changes, editor.state.doc.length), selection = editor.state.selection.main;
    const anchor = moved.mapPos(selection.anchor), head = moved.mapPos(selection.head);
    replaceText(latest.text, {baseline:true});
    if (merged !== latest.text) replaceText(merged);
    editor.dispatch({selection: {anchor: Math.min(anchor, merged.length), head: Math.min(head, merged.length)}});
  }
  state.base = latest.text; state.etag = latest.etag; state.writable = latest.writable;
  state.saveError = null; state.lastSavedAt = null; state.conflict = false; state.ancestor = null;
  state.reviewWhole = false; state.ambiguousExternal = false;
  savedHistory.rebase(history);
  if (externalChange?.data.etag === data.etag) externalChange.appliedText = merged;
  state.fileReceipt = merged === latest.text ? 'updated' : 'merged';
  notice();
  scheduleRecovery(); scheduleRender(); refreshControls(); check?.schedule(); scheduleAutosave();
}
async function refresh(forceFull = false) {
  if ($('refresh').disabled) return;
  void refreshThemes();
  const sequence = loadSequence;
  state.refreshing = true; refreshControls();
  actionFeedback('refresh', 'busy', 'Checking for file changes');
  status('Checking for file changes');
  const ready = !state.uri && !state.session || await reload(false, true);
  state.refreshing = false; refreshControls();
  if (sequence !== loadSequence) { actionFeedback('refresh', ''); return; }
  if (!ready) {
    actionFeedback('refresh', 'error', state.conflict ? 'External changes: your draft is retained' : 'Could not refresh from file');
    return;
  }
  state.forceFull ||= forceFull;
  refreshRequested = true;
  await render();
}
async function save({review = true, auto = false} = {}) {
  if ($('save').disabled) return false;
  if (state.conflict) { if (review) await reviewForSave(); return false; }
  const value = text(), sequence = loadSequence;
  readSequence++;
  state.saving = true; refreshControls(); status('Saving');
  try {
    const result = state.uri ? await extensions.resources.write(state.uri, {text: value, ifMatch: state.etag})
      : await call('matsugit_save', {session: state.session, text: value, etag: state.etag});
    if (sequence !== loadSequence) return false;
    if (result.outcome === 'saved') {
      if (state.base !== value) savedHistory.remember(state.base);
      state.ancestor = null;
      state.base = value; state.etag = result.etag; state.conflict = false; state.saveError = null; state.lastSavedAt = Date.now();
      if (!auto || state.fileReceipt !== 'merged') state.fileReceipt = null;
      if (externalChange) externalChange.data = {text:value,etag:result.etag,writable:state.writable};
      notice();
      return true;
    }
    else if (result.outcome === 'conflict' && auto) {
      // Another writer got there first. Nothing was written; combine and try again.
      setTimeout(() => reload(), 0);
    }
    else if (result.outcome === 'conflict') {
      state.conflict = true; notice('The file changed before Save completed. Your draft is retained; review before saving.');
    } else throw Error(result.outcome === 'too-large' ? 'The file exceeds the host write limit.' : 'The host did not save the file.');
  } catch (error) { if (sequence === loadSequence) { state.saveError = error.message; notice(error.message); } }
  finally { if (sequence === loadSequence) { readSequence++; state.saving = false; refreshControls(); scheduleRecovery(); await flushRecovery(); } }
  if (review && sequence === loadSequence && state.conflict) await reviewForSave();
  return false;
}
function offerIncoming(data) {
  incomingDocument = data;
  notice('An incoming document was not opened because you have a draft. Review the versions or keep editing.');
}
function applyOpenView(data) {
  if (['source', 'render', 'split', 'story'].includes(data.layout)) changeLayout(data.layout);
  if (['document', 'slides'].includes(data.format)) changeFormat(data.format);
  if (['raw', 'visual'].includes(data.editor)) changeEditorMode(data.editor);
  if (typeof data.autosave === 'boolean') { state.autosave = data.autosave; $('autosave').checked = data.autosave; }
}
async function load(data, {acceptRevision = null} = {}) {
  if (state.saving || state.merging) { notice('Wait for the current save or merge before opening another document.'); return; }
  if ((dirty() || tables.pending() || undoDepth(editor.state) || redoDepth(editor.state)) && acceptRevision !== state.revision) { offerIncoming(data); return; }
  const before = state.revision, table = JSON.stringify(tables.snapshot()), previousLoad = loadSequence;
  await flushRecovery();
  if (previousLoad !== loadSequence) return;
  if (before !== state.revision || table !== JSON.stringify(tables.snapshot())) { offerIncoming(data); return; }
  incomingDocument = null;
  mergeAttempt = null; savedHistory.clear(); state.ancestor = null; state.reviewWhole = false; state.ambiguousExternal = false;
  externalChange = null;
  noticeMessage = '';
  story.reset();
  tables.reset();
  const suppliedRecovery = data.recovery, requestedView = data;
  const sequence = ++loadSequence;
  refreshRequested = false; actionFeedback('refresh', '');
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
    name: data.file?.name || data.name || 'Untitled.md', path:data.path || null, conflict: false, rendered: null, renderedRevision: -1,
    resolvedTheme: null, etag: null, writable: false, pendingRender: false, saving: false, saveError:null, lastSavedAt:null, fileReceipt:null,
    bases: {}, revisions: {}, forceFull: false,
    positions: {document: {hash: '', scroll: 0}, slides: {hash: '', scroll: 0}}});
  themeCatalog = {}; themeSequence++;
  updateThemePicker($('theme'), themeCatalog, ''); $('theme').title = 'Theme';
  state.renderError = null; state.renderNotice = null; $('preview-stale').hidden = true;
  // Newcomers meet formatted text first. Org stays in source; an explicit
  // open option or a restored session still chooses its own mode below.
  changeEditorMode('visual');
  if (['source', 'render', 'split', 'story'].includes(data.layout)) changeLayout(data.layout);
  if (['document', 'slides'].includes(data.format)) changeFormat(data.format);
  $('empty').hidden = false; $('empty-label').textContent = 'Preparing preview'; $('preview').src = 'about:blank';
  if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
  try {
    if (state.uri) {
      if (!extensions.resources) throw Error('This host does not support file editing. Use the matsugit_open tool for the selected local file.');
      data = await resourceRead();
    } else if (state.session && typeof data.source !== 'string' && typeof data.text !== 'string') {
      data = await resourceRead();
    }
    if (sequence !== loadSequence) return;
    const source = sourceText(data);
    if (new TextEncoder().encode(source).length > 2 * 1024 * 1024 || source.includes('\0')) throw Error('Invalid source or document exceeds the 2 MiB editor limit.');
    state.base = source; state.etag = data.etag;
    state.writable = !!data.writable; replaceText(state.base, {baseline:true});
    editor.dispatch({selection: {anchor: 0}});
    if (!demo) {
      try {
        const recovered = await call('matsugit_recovery_begin', {...recoveryScope(), name: state.name});
        if (sequence !== loadSequence) return;
        recoveryId = recovered.id;
        const candidate = suppliedRecovery || recovered.candidate;
        if (candidate && !suppliedRecovery) {
          applyView(candidate.view);
          if ((candidate.text !== candidate.base && candidate.text !== state.base) || candidate.view?.tableDraft) {
            recoveryCandidate = candidate;
            $('recovery-message').textContent = `Unsaved recovery copy from ${new Date(candidate.updated).toLocaleString()}`;
            $('recovery-banner').hidden = false;
          }
        }
      } catch (error) { recoveryFailure(error); }
    }
    // Restoring an existing copy must not depend on creating another backup.
    if (suppliedRecovery) applyRecovery(suppliedRecovery);
    else applyOpenView(requestedView);
    state.loading = false;
    editor.dispatch({effects: editability.reconfigure(editable(!demo))});
    notice(state.writable && !state.etag ? 'The host supplied no file version. Saving is disabled to protect concurrent edits.' : '');
    if (state.conflict) notice('Recovered draft differs from the saved file. Both versions are retained for review.');
    else if (suppliedRecovery) notice(state.writable ? 'Recovered local draft. The source file was not changed.' : 'Recovered local copy. Download to keep it; the original file is unavailable here.');
    if (state.uri) {
      disposeUpdates = extensions.resources.addUpdateHandler(({params}) => { if (params.uri === state.uri && !state.delivering) reload(); });
      extensions.resources.subscribe({uri: state.uri}).catch(() => {});
    }
    refreshControls();
    // Do not replace the latest recovery with the file before a pending choice.
    if (!recoveryCandidate) scheduleRecovery();
    if (demo) { state.rendered = demo.rendered; showPreview(); }
    else { void refreshThemes(); if (state.layout !== 'story' || state.storyPreview) await render(); }
  } catch (error) {
    if (sequence === loadSequence) {
      state.loading = false;
      editor.dispatch({effects: editability.reconfigure(editable(!demo))});
      notice(error.message); refreshControls(); status('Cannot open document');
    }
  }
}
// The reviewed publication moved this file. Keep working on it at its new
// path: same draft, undo history and view; only the file identity changes.
async function follow(workspace) {
  disposeUpdates?.(); disposeUpdates = null;
  if (state.uri) extensions.resources?.unsubscribe({uri: state.uri}).catch(() => {});
  await flushRecovery();
  Object.assign(state, {uri: null, session: workspace.session, name: workspace.name, path: workspace.path,
    base: workspace.text, etag: workspace.etag, writable: true, conflict: false, saveError: null, fileReceipt: null});
  externalChange = null; mergeAttempt = null; readSequence++;
  try {
    recoveryId = (await call('matsugit_recovery_begin', {...recoveryScope(), name: state.name})).id;
    recoveryGeneration = 0;
  } catch (error) { recoveryFailure(error); }
  refreshControls(); scheduleRecovery(); void refreshThemes();
}
async function download() {
  status('Sending download...');
  try { status(await downloadFile({name:state.name,blob:new Blob([text()],{type:'text/plain;charset=utf-8'})})); }
  catch (error) { status('Download not completed'); notice(error.message); }
}
function recoveryScope() {
  return {...(state.session ? {session: state.session} : {}), ...(state.uri ? {resourceUri: state.uri} : {})};
}
function viewState() {
  const style = document.documentElement.style;
  return {layout: state.layout, storyPreview:state.storyPreview, storyMode:state.storyMode, storySize:state.storySize, format: state.format, theme: $('theme').value, auto: $('auto').checked, sync: $('sync').checked,
    editorMode:state.editorMode,autosave:state.autosave,slideSeparators:$('slide-separators').checked,tableDraft:tables.snapshot(),
    anchor: editor.state.selection.main.anchor, head: editor.state.selection.main.head, editorScroll: editor.scrollDOM.scrollTop,
    width: parseFloat(style.getPropertyValue('--source-size')) || 50, height: parseFloat(style.getPropertyValue('--source-height')) || 50,
    positions: state.positions};
}
function applyView(view) {
  if (!view) return;
  const loading = state.loading; state.loading = true;
  updateThemePicker($('theme'), themeCatalog, view.theme || ''); $('auto').checked = view.auto !== false; $('sync').checked = view.sync !== false;
  state.storyPreview = view.storyPreview === true;
  state.storyMode = view.storyMode === 'walkthrough' ? 'walkthrough' : 'overview';
  state.storySize = view.storySize === 'compact' ? 'compact' : 'large';
  changeLayout(view.layout); changeFormat(view.format);
  changeEditorMode(view.editorMode==='visual'?'visual':'raw');
  if (typeof view.autosave === 'boolean') { state.autosave = view.autosave; $('autosave').checked = view.autosave; }
  $('slide-separators').checked = view.slideSeparators === true;
  editor.dispatch({effects: slideSeparators.of($('slide-separators').checked)});
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
  if(record.view?.tableDraft)setTimeout(()=>tables.restore(record.view.tableDraft),0);
}
function recoveryFailure(error) {
  $('recovery-status').textContent = 'Draft backup unavailable';
  $('recovery-status').title = error.message; $('recovery-status').dataset.error = 'true';
}
function scheduleRecovery() {
  if (demo || state.loading || !recoveryId) return;
  if (recoveryCandidate && !dirty()) return;
  recoveryPending = true;
  $('recovery-status').textContent = 'Backing up draft...';
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
      $('recovery-status').textContent = recoveryPending ? 'Backing up draft...' : 'Draft backed up';
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
  const revision = state.revision, table = JSON.stringify(tables.snapshot()), before = loadSequence;
  await flushRecovery();
  if (before !== loadSequence || revision !== state.revision || table !== JSON.stringify(tables.snapshot())) {
    notice('The draft changed during recovery. Nothing was replaced.'); return;
  }
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
  notice(state.conflict ? 'Recovered draft differs from the saved file. Both versions are retained for review.' : 'Recovered local draft. The source file was not changed.');
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
  if (demo || !app.getHostContext() || cursorHost(app.getHostContext(), app.getHostVersion())) return;
  // Cursor turns passive context updates into composer edits and can steal focus.
  // Explicit slide AI requests send their own context and remain available.
  const structuredContent = {
    file: state.name, layout: state.layout, format: state.format, dirty: dirty(), revision: state.revision,
    conflict: state.conflict, previewCurrent: state.renderedRevision === state.revision,
  };
  const next = JSON.stringify(structuredContent);
  if (next === lastModelContext) return;
  lastModelContext = next;
  app.updateModelContext({structuredContent}).catch(() => {
    if (lastModelContext === next) lastModelContext = '';
  });
}
function hostContext(context) {
  currentHostContext = {...currentHostContext, ...context};
  context = currentHostContext;
  if (context?.theme) applyDocumentTheme(context.theme);
  if (context?.styles?.variables) applyHostStyleVariables(context.styles.variables);
  for (const side of ['top','bottom','left','right']) document.documentElement.style.setProperty(`--safe-${side}`, `${context?.safeAreaInsets?.[side] || 0}px`);
  const height = inlineEditorHeight(context);
  document.documentElement.dataset.displayMode = context.displayMode || '';
  if (height !== null) document.documentElement.style.setProperty('--inline-editor-height', `${height}px`);
  else document.documentElement.style.removeProperty('--inline-editor-height');
  const modes = context.availableDisplayModes || [];
  const expanded = context.displayMode === 'fullscreen';
  const button = $('expand-workspace');
  button.hidden = !modes.includes(expanded ? 'inline' : 'fullscreen');
  button.title = expanded ? 'Exit expanded workspace' : 'Expand workspace';
  button.setAttribute('aria-label', button.title);
  button.replaceChildren(createElement(expanded ? Minimize2 : Maximize2));
  const host = app.getHostVersion();
  $('workspace-version').title = `matsugit workspace ${version}; ${host?.name || context.userAgent || 'host'} ${host?.version || ''}; ${context.displayMode || 'default'} view`;
  editor.requestMeasure();
}
$('expand-workspace').onclick = async () => {
  if (changingDisplayMode) return;
  changingDisplayMode = true;
  $('expand-workspace').disabled = true;
  try {
    const mode = currentHostContext.displayMode === 'fullscreen' ? 'inline' : 'fullscreen';
    if (!currentHostContext.availableDisplayModes?.includes(mode)) return;
    const result = await app.requestDisplayMode({mode});
    hostContext({displayMode:result.mode});
    if (result.mode !== mode) notice('The editor host kept the current workspace size.');
  } catch (error) { notice('Could not resize the workspace: ' + error.message); }
  finally { changingDisplayMode = false; $('expand-workspace').disabled = false; }
};
$('save').onclick = () => save();
$('notice-save').onclick = () => save();
$('notice-dismiss').onclick = () => { state.fileReceipt = null; notice(); };
let sharing;
publication = publicationStatus({call,state,hasUnsaved:()=>dirty() || tables.pending(),demo,painted:(label,busy)=>sharing?.painted(label,busy)});
const delivering = delivery({call, state, text, theme:() => $('theme').value.trim(), notice, download, downloadFile, demo, reload, load, follow,
  hasUnsaved:() => dirty() || tables.pending(), refreshControls, publication, mergeReview});
sharing = share({call, state, text, dirty: () => dirty() || tables.pending(), save: () => save({review: false}), ...delivering,
  mergeReview, publication, reload, notice, demo});
publication.update();
$('insert').onclick = () => layouts.open();
$('undo').onclick = () => undo(editor); $('redo').onclick = () => redo(editor);
$('refresh').onclick = event => refresh(event.shiftKey); $('auto').onchange = () => { scheduleRender(); scheduleRecovery(); };
$('sync').onchange = () => { if ($('sync').checked) { origin = 'source'; followSource(); } scheduleRecovery(); };
$('theme').onchange = () => { state.revision++; refreshControls(); scheduleRender(); scheduleRecovery(); };
$('reload').onclick = () => incomingDocument ? reviewIncoming() : state.conflict ? reviewForSave() : reviewAllChanges();
$('external-review').onclick = reviewAllChanges;
$('incoming-review').onclick = () => { $('incoming-dialog').close(); void reviewAllChanges(); };
async function resolvePlan(plan) {
  if (!plan.conflicts) return mergeResult(plan);
  return new Promise((resolve, reject) => mergeReview.open(plan, resolve,
    () => reject(Error('Merge canceled; draft retained.'))));
}
async function reviewForSave() {
  if (state.loading || state.saving || state.merging || state.delivering || incomingDocument) return;
  if (tables.pending()) { notice('Your table draft is retained. Apply or close the table edit before reviewing file changes.'); return; }
  const snapshot = mergeSnapshot();
  state.merging = true; refreshControls();
  try {
    const data = await resourceRead();
    const computed = await call('matsugit_merge', {base:snapshot.mergeBase, local:snapshot.text, incoming:data.text});
    const merge = snapshot.reviewWhole ? wholeFileReview(computed.merge, snapshot.base, snapshot.text, data.text) : computed.merge;
    checkMergeSnapshot(snapshot);
    if (!externalChange || externalChange.data.etag !== data.etag)
      externalChange = {base:snapshot.base, local:snapshot.text, incoming:data.text, data, appliedText:null};
    let prepared = null;
    mergeReview.open(merge, async candidate => {
      if (state.loading || state.saving || state.merging || state.delivering) throw Error('Wait for the current operation.');
      if (prepared) {
        if (state.revision !== prepared.revision || state.etag !== prepared.etag || text() !== prepared.text || state.conflict)
          throw Error('The versions changed after review. Your draft is retained; review the latest file.');
      }
      if (!prepared || text() !== candidate) {
        state.merging = true; refreshControls();
        try {
          await applyMerged(data, candidate, prepared ? mergeSnapshot() : snapshot);
          prepared = {revision:state.revision, etag:state.etag, text:candidate};
        } finally { state.merging = false; refreshControls(); }
      }
      // A failed write leaves the reviewed result in the draft for retry, never
      // re-applies an older snapshot over subsequent typing or another file edit.
      if (!dirty() && !state.conflict) { state.fileReceipt = null; notice(); return; }
      if (!await save({review:false})) throw Error(state.conflict
        ? 'The file changed again before saving. Your reviewed draft is retained; review the latest file.'
        : `Reviewed draft retained, not saved. ${state.saveError || 'Save is unavailable.'}`);
    }, undefined, {save:true, context:`File: ${state.path || state.name}\n${state.ambiguousExternal ? 'The file may come from an older version. Check the proposed result; nothing has been combined yet.\n' : ''}Only the reviewed version will be saved. Git publication is unchanged.`, recheck:reviewForSave, versions:reviewIncoming});
  } catch (error) { notice(error.message); }
  finally { state.merging = false; refreshControls(); }
}
async function reviewAllChanges() {
  if (!externalChange || state.saving || state.merging || tables.pending()) return;
  const record = externalChange, snapshot = mergeSnapshot();
  try {
    const {merge} = await call('matsugit_merge', {base:record.base, local:record.local, incoming:record.incoming});
    checkMergeSnapshot(snapshot);
    externalReview.open(merge, record.base, state.name.endsWith('.org'), async selected => {
      checkMergeSnapshot(snapshot);
      const original = await call('matsugit_merge', {base:record.base, local:record.local, incoming:selected});
      const desired = await resolvePlan(original.merge);
      // Reversing a previously auto-merged hunk must retain subsequent typing.
      const rebased = await call('matsugit_merge', {base:record.appliedText ?? record.local,
        local:snapshot.text, incoming:desired});
      const candidate = await resolvePlan(rebased.merge);
      checkMergeSnapshot(snapshot);
      return candidate;
    }, async candidate => {
      if (state.saving || state.merging) throw Error('Wait for the current operation.');
      state.merging = true; refreshControls();
      try {
        await applyMerged(record.data, candidate, snapshot);
        externalChange = null;
      } finally { state.merging = false; refreshControls(); }
    });
  } catch (error) { notice(error.message); }
}
let reviewedIncoming;
async function reviewIncoming() {
  const sequence = loadSequence, requested = incomingDocument;
  try {
    const data = requested?.file?.resourceUri ? await resourceRead({uri:requested.file.resourceUri})
      : requested ? {text:requested.source ?? requested.text ?? ''} : await resourceRead();
    if (sequence !== loadSequence || requested !== incomingDocument) return;
    reviewedIncoming = {requested, data, sequence};
    $('incoming-status').textContent = '';
    $('incoming-local').value = text(); $('incoming-file').value = data.text;
    $('incoming-name').textContent = requested?.name || requested?.file?.name || state.name;
    $('incoming-merge').disabled = !!requested || tables.pending();
    $('incoming-review').disabled = !!requested || tables.pending();
    if (!requested && externalChange?.data.etag !== data.etag)
      externalChange = {base:state.base, local:text(), incoming:data.text, data, appliedText:null};
    $('incoming-merge').title = requested ? 'Different documents do not have a shared merge base' : tables.pending() ? 'Apply or cancel the table edit before merging' : 'Merge changes from the last shared version';
    $('incoming-dialog').showModal();
  } catch(error) { notice(error.message); }
}
$('incoming-keep').onclick = () => $('incoming-dialog').close();
$('incoming-download').onclick = download;
$('incoming-merge').onclick = async () => {
  const choice = reviewedIncoming, snapshot = mergeSnapshot();
  if (!choice || choice.requested || choice.sequence !== loadSequence || state.merging) return;
  state.merging = true; refreshControls(); $('incoming-merge').disabled = true;
  $('incoming-status').textContent = 'Comparing changes...';
  try {
    checkMergeSnapshot(snapshot);
    const computed = await call('matsugit_merge', {base:snapshot.mergeBase, local:snapshot.text, incoming:choice.data.text});
    const merge = snapshot.reviewWhole ? wholeFileReview(computed.merge, snapshot.base, snapshot.text, choice.data.text) : computed.merge;
    checkMergeSnapshot(snapshot);
    $('incoming-dialog').close();
    mergeReview.open(merge, async merged => {
      if (state.saving || state.merging) throw Error('Wait for the current operation.');
      state.merging = true; refreshControls();
      try { await applyMerged(choice.data, merged, snapshot); }
      finally { state.merging = false; refreshControls(); }
    });
  } catch(error) { $('incoming-status').textContent = error.message; }
  finally { state.merging = false; $('incoming-merge').disabled = false; refreshControls(); }
};
$('incoming-use').onclick = async () => {
  const choice = reviewedIncoming;
  if (!choice || choice.sequence !== loadSequence || state.saving || state.loading) return;
  const revision = state.revision, snapshot = {text:text(), base:state.base, view:viewState()};
  $('incoming-use').disabled = true;
  try {
    // Retain a separate recovery copy: normal checkpointing must not overwrite
    // the draft the user explicitly replaced while resolving this conflict.
    const copy = await call('matsugit_recovery_begin', {...recoveryScope(), name:state.name});
    await call('matsugit_recovery_checkpoint', {...recoveryScope(), id:copy.id, generation:0, ...snapshot});
    if (choice.sequence !== loadSequence || revision !== state.revision || JSON.stringify(snapshot.view.tableDraft) !== JSON.stringify(tables.snapshot())) {
      $('incoming-status').textContent = 'The draft changed during backup. Nothing was replaced; review it again.'; return;
    }
    if (choice.requested) await load(choice.requested, {acceptRevision:revision});
    else if (!await reload(true, true, choice.data.etag)) {
      $('incoming-status').textContent = $('notice-text').textContent; return;
    }
    $('incoming-dialog').close();
  } catch(error) { $('incoming-status').textContent = 'Draft retained: could not save a safety copy. '+error.message; }
  finally { $('incoming-use').disabled = false; }
};
$('open').onclick = () => $('file').click();
$('file').onchange = async () => {
  const file = $('file').files[0]; if (!file) return;
  if (file.size > 2 * 1024 * 1024) return notice('Document exceeds the 2 MiB editor limit.');
  await load({name: file.name, text: await file.text(), writable: false});
  notice('Imported browser copy. Download source to save; relative assets require opening the repository file with matsugit_open.');
};
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault();
    if($('table-dialog').open)$('table-apply').click();else save();
  }
});
window.addEventListener('beforeunload', event => { flushRecovery(); if ((dirty() || tables.pending()) && !demo) { event.preventDefault(); event.returnValue = ''; } });
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
    editor.dispatch({changes: {from: 0, to: editor.state.doc.length, insert: args.text}, annotations:isolateHistory.of('full')});
    return JSON.stringify({revision: state.revision, saved: false});
  }});
// Expose only the editor model to the isolated local UI test harness.
window.matsugitWorkspace = {editor, state, load, render, save, reload, flushRecovery, tables};
async function boot() {
if (demo) {
  await load(demo);
  for (const id of ['open','save','undo','redo','refresh','auto','theme','insert','recover']) $(id).disabled = true;
} else {
  app.addEventListener('toolinput', ({arguments: args}) => {
    if (args?.file && args.file.resourceUri !== state.uri) load(args);
  });
  app.ontoolresult = async result => {
    try {
      const data = hostResultData(result);
      if (data.file && data.file.resourceUri === state.uri) return;
      if (data.session && data.session === state.session) { await reload(); applyOpenView(data); return; }
      if (!data.file && !data.session && !(data.name && (typeof data.source === 'string' || typeof data.text === 'string'))) return;
      await load(data);
    } catch (error) { notice(error.message); status('Could not open document'); }
  };
  app.addEventListener('hostcontextchanged', hostContext);
  try { await app.connect(); hostContext(app.getHostContext()); }
  catch (error) { notice(error.message); status('Host connection unavailable'); }
  setInterval(() => { if ((state.session || state.uri) && !state.delivering) reload(); }, 3000);
}
}
boot().catch(error => { notice(error.message); status('Workspace unavailable'); });
