import {createElement, X} from 'lucide';
import {previewHtml} from './preview.js';

// A read-only view of the current draft. It never changes the main preview,
// editor selection, layout, file or undo history.
export function slidePeek({call, snapshot}) {
  const dialog = document.createElement('dialog'); dialog.id = 'slide-peek';
  dialog.setAttribute('aria-labelledby','slide-peek-title');
  const header = document.createElement('header'), title = document.createElement('strong');
  title.id = 'slide-peek-title';
  const close = document.createElement('button'); close.type = 'button';
  close.title = 'Close slide preview'; close.setAttribute('aria-label',close.title); close.append(createElement(X));
  const status = document.createElement('p'); status.setAttribute('role','status');
  const frame = document.createElement('iframe'); frame.title = 'Full slide preview'; frame.setAttribute('sandbox','allow-scripts');
  header.append(title,close); dialog.append(header,status,frame); document.body.append(dialog);
  let generation = 0, url = null, origin = null, cancel = null, target = null, token = '';
  function cleanup() {
    generation++; cancel?.(); cancel = null;
    frame.removeAttribute('src'); frame.hidden = true;
    if (url) URL.revokeObjectURL(url); url = null;
  }
  close.onclick = () => dialog.close();
  dialog.addEventListener('close', () => {
    if (dialog.open) return;
    cleanup(); origin?.focus({preventScroll:true});
  });
  window.addEventListener('message', event => {
    if (!dialog.open || event.source !== frame.contentWindow || event.data?.matsugitPreview !== token) return;
    if (event.data.presentExit) { dialog.close(); return; }
    if (event.data.matsugitReady) {
      frame.contentWindow.postMessage({matsugitPreview:token, targets:[target], presenting:true}, '*');
    }
  });
  return {close:() => dialog.open && dialog.close(), async open(node) {
    cleanup(); origin = document.activeElement;
    const sequence = generation, captured = snapshot(), owner = captured.session ? {session:captured.session} : {};
    target = {key:node.key, level:node.level, occurrence:node.occurrence};
    token = crypto.randomUUID(); title.textContent = node.label;
    status.hidden = false; status.textContent = 'Preparing slide...';
    if (!dialog.open) dialog.showModal(); close.focus({preventScroll:true});
    const active = () => sequence === generation && dialog.open;
    const current = () => { const now = snapshot(); return active() && now.session === captured.session && now.text === captured.text && now.theme === captured.theme; };
    try {
      let html = captured.html;
      if (!html) {
        let job = await call('matsugit_preview', {text:captured.text,name:captured.name,format:'slides',theme:captured.theme,...owner});
        const id = job.job, stop = () => call('matsugit_preview_cancel',{job:id,...owner}).catch(() => {});
        if (!active()) { await stop(); return; }
        cancel = stop;
        const deadline = Date.now() + 240_000;
        while (job.state === 'rendering') {
          if (!current()) throw Error('The draft changed. Close and reopen this slide for its latest version.');
          if (Date.now() > deadline) throw Error('Slide preview timed out. Close and try again.');
          status.textContent = job.phase || 'Rendering slide...';
          await new Promise(resolve => setTimeout(resolve,350));
          if (!active()) return;
          job = await call('matsugit_preview_status',{job:id,...owner});
        }
        if (job.state !== 'ready') throw Error(job.error || 'Slide preview unavailable.');
        const parts = []; let offset = 0;
        while (true) {
          if (!active()) return;
          const part = await call('matsugit_preview_chunk',{job:id,format:'slides',offset,...owner});
          parts.push(part.chunk);
          if (part.next > 20 * 1024 * 1024 || (part.next <= offset && !part.done)) throw Error('Invalid slide preview response.');
          offset = part.next;
          if (part.done) break;
        }
        html = parts.join('');
      }
      if (!active()) return;
      if (!current()) throw Error('The draft changed. Close and reopen this slide for its latest version.');
      url = URL.createObjectURL(new Blob([previewHtml(html,'slides',{target,singleSlide:true},token)],{type:'text/html'}));
      frame.src = url; frame.hidden = false; status.hidden = true;
    } catch (error) { if (active()) { status.hidden = false; status.textContent = error.message; cancel?.(); cancel = null; } }
  }};
}
