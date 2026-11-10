import {createElement, Sparkles, Send, Copy, Check, X, LoaderCircle} from 'lucide';
import {slideAgentTarget, slideAgentRequest} from './slide-agent-request.mjs';

const $ = id => document.getElementById(id);

export function slideAgent({snapshot, enabled, save, read, path, sender, notice}) {
  const dialog = $('slide-agent-dialog'), prompt = $('slide-agent-prompt');
  const submit = $('slide-agent-send'), copy = $('slide-agent-copy'), close = $('slide-agent-close');
  const status = $('slide-agent-status');
  let opened, target, busy = false, delivered = false, uncertain = false, remembered;
  const identity = value => JSON.stringify([value.generation,value.session,value.uri,value.name]);
  function check() {
    const current = snapshot();
    if (!enabled() || current.conflict) throw Error('Finish saving or reviewing external changes before sending. Your prompt is retained.');
    if (identity(current) !== identity(opened) || current.text !== opened.text)
      throw Error('The document changed while this prompt was open. Close and reopen the slide action; your instructions are retained.');
    return current;
  }
  function controls() {
    const dirty = snapshot().text !== snapshot().base;
    submit.replaceChildren(createElement(busy ? LoaderCircle : delivered ? Check : Send),
      document.createTextNode(delivered ? 'Sent' : busy ? 'Sending...' : dirty ? 'Save and send' : 'Send'));
    submit.disabled = busy || delivered || uncertain || !prompt.value.trim() || !sender();
    submit.title = dirty ? 'Save all current document edits, then send this slide request to the current chat' : 'Send this slide request to the current chat';
    submit.setAttribute('aria-busy',String(busy));
    copy.disabled = busy || !prompt.value.trim(); close.disabled = busy;
    prompt.readOnly = busy || delivered || uncertain;
  }
  $('slide-agent-icon').append(createElement(Sparkles));
  close.append(createElement(X)); copy.append(createElement(Copy));
  close.onclick = () => dialog.close();
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('close', () => {
    if (!delivered && opened) remembered = {identity:identity(opened), from:target.from, prompt:prompt.value};
  });
  prompt.oninput = () => { $('slide-agent-request-panel').hidden = true; controls(); };
  async function request() {
    let current = check();
    const localPath = await path();
    current = check();
    return slideAgentRequest({target, prompt:prompt.value, path:localPath, etag:current.etag});
  }
  copy.onclick = async () => {
    if (busy) return;
    busy = true; controls();
    try {
      if (snapshot().text !== snapshot().base) throw Error('Save or merge the current draft before copying an agent request. Nothing was sent.');
      const value = await request();
      $('slide-agent-request').value = value; $('slide-agent-request-panel').hidden = false;
      try { await navigator.clipboard.writeText(value); status.textContent = 'Request copied. Nothing sent.'; }
      catch { status.textContent = 'Clipboard unavailable. Select and copy the request below.'; $('slide-agent-request').select(); }
    } catch (error) { status.textContent = error.message; }
    finally { busy = false; controls(); }
  };
  $('slide-agent-form').onsubmit = async event => {
    event.preventDefault();
    if (busy || delivered || uncertain) return;
    const send = sender();
    if (!send) { status.textContent = 'This host cannot send to chat. Copy the request instead.'; return; }
    let attempted = false;
    busy = true; controls();
    try {
      let current = check();
      // Validate before saving; clicking Send must not save for an invalid request.
      await request();
      current = check();
      if (current.text !== current.base) {
        status.textContent = 'Saving document...';
        await save();
        current = check();
        if (current.text !== current.base || current.saveError)
          throw Error('The document was not saved. Nothing sent. ' + (current.saveError || 'Review the save status and retry.'));
      }
      status.textContent = 'Checking saved slide...';
      const disk = await read();
      current = check();
      if (disk.text !== current.text || disk.etag !== current.etag)
        throw Error('The file changed outside this editor. Nothing sent. Refresh and review before retrying.');
      const message = await request();
      check(); attempted = true;
      status.textContent = 'Sending to current chat...';
      const result = await send(message);
      if (result?.isError) throw Error('The host did not confirm message delivery.');
      delivered = true; remembered = null;
      status.textContent = 'Sent to current chat.';
      notice('Slide edit request sent to current chat.');
    } catch (error) {
      uncertain = attempted;
      status.textContent = attempted
        ? 'Delivery unconfirmed. Check the chat before sending again. Your prompt is retained. ' + error.message
        : error.message;
    } finally { busy = false; controls(); }
  };
  return {open(node, suggestion = '') {
    if (busy || !enabled()) return;
    try {
      opened = snapshot();
      target = slideAgentTarget(opened.text,node.from,opened.name.toLowerCase().endsWith('.org'));
      delivered = false; uncertain = false;
      // A request started from Check arrives with the problem already written.
      prompt.value = suggestion || (remembered?.identity === identity(opened) && remembered.from === target.from ? remembered.prompt : '');
      $('slide-agent-context').textContent = [target.section,`Slide ${target.number}`,target.title].filter(Boolean).join(' / ');
      $('slide-agent-source').textContent = target.source;
      $('slide-agent-request-panel').hidden = true;
      $('slide-agent-source-panel').open = false;
      status.textContent = sender() ? '' : 'This host cannot send to chat. Copy the request instead.';
      controls(); dialog.showModal(); prompt.focus();
    } catch (error) { notice(error.message); }
  }};
}
