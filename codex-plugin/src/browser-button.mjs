import {createElement, Globe, X} from 'lucide';

export function browserBlocker(state) {
  if (!state.path || !state.etag) return 'Open a local Markdown or Org file first.';
  if (state.pendingTable) return 'Apply or cancel the table edit first. Your draft is unchanged.';
  if (state.incomingReady || state.externalPending || state.conflict)
    return 'Accept or review the file changes first. Your draft is unchanged.';
  if (state.loading || state.saving || state.merging || state.delivering)
    return 'Wait for the current operation to finish.';
  return '';
}

export function browserButton({current, save, call}) {
  const $ = id => document.getElementById(id);
  const trigger = $('browser-open'), dialog = $('browser-dialog'), action = $('browser-confirm');
  const status = $('browser-status'), link = $('browser-link');
  let busy = false, origin;
  trigger.append(createElement(Globe));
  $('browser-close').append(createElement(X));
  function close() { dialog.close(); trigger.focus(); }
  $('browser-close').onclick = close;
  $('browser-cancel').onclick = close;
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  async function run(consent = false) {
    if (busy) return;
    link.hidden = true;
    $('browser-cancel').textContent = 'Cancel';
    action.hidden = false;
    const before = current(), problem = browserBlocker(before);
    if (problem || before.path !== origin) {
      status.textContent = problem || 'The open document changed. Close this dialog and try again.';
      action.hidden = true;
      return;
    }
    if (before.dirty && !consent) {
      status.textContent = 'Save your draft to this file before opening it in the browser?';
      action.textContent = 'Save and open';
      action.focus();
      return;
    }
    busy = true; action.disabled = true; trigger.disabled = true;
    action.setAttribute('aria-busy', 'true');
    status.textContent = before.dirty ? 'Saving your draft...' : 'Opening browser workspace...';
    try {
      if (before.dirty && !await save({review:false}))
        throw Error('Not opened: the draft could not be saved. Your writing is still in this window.');
      const now = current();
      if (browserBlocker(now) || now.path !== origin || now.dirty)
        throw Error('Not opened: the document changed during saving. Review it and try again.');
      const result = await call('matsugit_browser', {path:now.path, etag:now.etag,
        layout:now.layout, format:now.format, editor:now.editorMode, autosave:false});
      if (!/^http:\/\/127\.0\.0\.1:\d+\/[\w-]{32}\/$/.test(result.url || ''))
        throw Error('The server did not return a valid local browser address.');
      if (!dialog.open) return;
      status.textContent = `Browser workspace ready on ${result.runtime_host || 'the computer running matsugit'}. ` +
        'The link works on that computer only. No document was published.';
      link.href = result.url; link.hidden = false; action.hidden = true;
      $('browser-cancel').textContent = 'Done';
      link.focus();
    } catch (error) {
      if (dialog.open) {
        status.textContent = error.message;
        action.textContent = current().dirty ? 'Save and retry' : 'Retry';
      }
    } finally {
      busy = false; action.disabled = false; trigger.disabled = !current().path;
      action.setAttribute('aria-busy', 'false');
    }
  }
  action.onclick = () => void run(true);
  trigger.onclick = () => {
    if (busy || dialog.open) return;
    origin = current().path;
    action.textContent = 'Open in browser';
    dialog.showModal(); void run();
  };
}
