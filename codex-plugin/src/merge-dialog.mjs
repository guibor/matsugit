import {createElement, ChevronLeft, ChevronRight} from 'lucide';
import {mergeResult} from './merge-result.mjs';

export function mergeDialog() {
  const $ = id => document.getElementById(id), dialog = $('merge-dialog');
  let plan, conflicts = [], choices = [], position = 0, apply, busy = false, cancel, applied = false;
  dialog.addEventListener('close', () => { if (!applied) cancel?.(); });
  $('merge-previous').replaceChildren(createElement(ChevronLeft));
  $('merge-next').replaceChildren(createElement(ChevronRight));
  function controls() {
    const remaining = conflicts.length - choices.filter(value => typeof value === 'string').length;
    $('merge-count').textContent = conflicts.length ? `Conflict ${position + 1} of ${conflicts.length} (${remaining} unresolved)` : 'No overlapping changes';
    $('merge-apply').disabled = busy || remaining > 0;
    $('merge-previous').disabled = busy || position === 0;
    $('merge-next').disabled = busy || position >= conflicts.length - 1;
    for (const id of ['merge-mine', 'merge-file', 'merge-both', 'merge-cancel']) $(id).disabled = busy;
    $('merge-result').readOnly = busy;
    $('merge-preview').hidden = remaining > 0;
    if (!remaining) $('merge-complete').value = mergeResult(plan, choices);
  }
  function show() {
    const conflict = conflicts[position];
    $('merge-conflict').hidden = !conflict;
    if (conflict) {
      $('merge-line').textContent = `Base line ${conflict.line}`;
      $('merge-base').value = conflict.base;
      $('merge-local').value = conflict.local;
      $('merge-incoming').value = conflict.incoming;
      $('merge-result').value = choices[position] ?? conflict.local;
    }
    controls();
  }
  function choose(value) { choices[position] = value; $('merge-result').value = value; controls(); }
  $('merge-mine').onclick = () => choose(conflicts[position].local);
  $('merge-file').onclick = () => choose(conflicts[position].incoming);
  $('merge-both').onclick = () => {
    const {local, incoming} = conflicts[position];
    choose(local + (local && incoming && !local.endsWith('\n') ? '\n' : '') + incoming);
  };
  $('merge-result').oninput = () => { choices[position] = $('merge-result').value; controls(); };
  $('merge-previous').onclick = () => { position--; show(); };
  $('merge-next').onclick = () => { position++; show(); };
  $('merge-cancel').onclick = () => dialog.close();
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('keydown', event => {
    if (event.altKey && ['ArrowLeft','ArrowRight'].includes(event.key)) {
      event.preventDefault(); $(event.key === 'ArrowLeft' ? 'merge-previous' : 'merge-next').click();
    }
  });
  $('merge-apply').onclick = async () => {
    busy = true; controls(); $('merge-status').textContent = 'Preserving draft and checking file version...';
    try { await apply(mergeResult(plan, choices)); applied = true; dialog.close(); }
    catch (error) { $('merge-status').textContent = error.message; }
    finally { busy = false; controls(); }
  };
  return {open(value, onApply, onCancel) {
    cancel = onCancel; applied = false;
    plan = value; conflicts = plan.segments.filter(segment => !('text' in segment));
    choices = []; position = 0; apply = onApply;
    $('merge-status').textContent = ''; $('merge-preview').open = false;
    show(); dialog.showModal();
  }, isOpen: () => dialog.open};
}
