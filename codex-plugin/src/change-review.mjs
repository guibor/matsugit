import {structure} from './structure.mjs';

export function selectedIncoming(plan, accepted) {
  let index = 0;
  return plan.external.map(part => 'text' in part ? part.text : accepted[index++] ? part.after : part.before).join('');
}

export function changeGroups(plan, base, org = false) {
  const headings = structure(base, org).headings.filter(h => h.topLevel && h.level <= 2);
  const groups = [];
  for (const part of plan.external.filter(p => !('text' in p))) {
    const heading = headings.findLast(h => h.from <= part.offset);
    const key = heading?.from ?? -1;
    if (groups.at(-1)?.key !== key) groups.push({key, title:heading?.label || 'Document settings / opening', changes:[]});
    groups.at(-1).changes.push(part);
  }
  return groups;
}

export function changeReview() {
  const $ = id => document.getElementById(id), dialog = $('changes-dialog');
  let plan, accepted, calculate, apply, candidate = null, busy = false;
  function controls() {
    $('changes-preview').disabled = busy;
    $('changes-apply').disabled = busy || candidate === null;
    $('changes-cancel').disabled = busy;
    for (const input of $('changes-list').querySelectorAll('input')) input.disabled = busy;
  }
  $('changes-cancel').onclick = () => dialog.close();
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  $('changes-preview').onclick = async () => {
    busy = true; candidate = null; controls(); $('changes-status').textContent = 'Comparing selected changes with your current draft...';
    try {
      candidate = await calculate(selectedIncoming(plan, accepted));
      $('changes-result').value = candidate;
      $('changes-result-panel').hidden = false;
      $('changes-status').textContent = 'Preview ready. No file has been saved.';
    } catch (error) { $('changes-status').textContent = error.message; }
    finally { busy = false; controls(); }
  };
  $('changes-apply').onclick = async () => {
    busy = true; controls(); $('changes-status').textContent = 'Preserving draft and checking file version...';
    try { await apply(candidate); dialog.close(); }
    catch (error) { $('changes-status').textContent = error.message; }
    finally { busy = false; controls(); }
  };
  return {isOpen: () => dialog.open, open(value, base, org, onCalculate, onApply) {
    plan = value; calculate = onCalculate; apply = onApply; candidate = null;
    accepted = plan.external.filter(p => !('text' in p)).map(() => true);
    $('changes-result-panel').hidden = true; $('changes-status').textContent = '';
    $('changes-list').replaceChildren();
    let index = 0;
    for (const group of changeGroups(plan, base, org)) {
      const section = document.createElement('section'), heading = document.createElement('h3');
      heading.textContent = group.title; section.append(heading);
      for (const change of group.changes) {
        const id = index++, label = document.createElement('label'), checkbox = document.createElement('input');
        checkbox.type = 'checkbox'; checkbox.checked = true;
        checkbox.onchange = () => {
          accepted[id] = checkbox.checked; candidate = null; controls();
          $('changes-result-panel').hidden = true; $('changes-status').textContent = '';
        };
        label.append(checkbox, `Accept external change at line ${change.line}`);
        const diff = document.createElement('div'); diff.className = 'change-diff';
        for (const [kind, content] of [['before',change.before], ['after',change.after]]) {
          const column = document.createElement('div'), caption = document.createElement('small');
          caption.textContent = kind === 'before' ? 'Before' : 'External edit';
          const pre = document.createElement('pre'); pre.className = kind;
          pre.setAttribute('aria-label', kind === 'before' ? 'Before' : 'After');
          pre.textContent = content || '(empty)'; column.append(caption,pre); diff.append(column);
        }
        section.append(label, diff);
      }
      $('changes-list').append(section);
    }
    if (!accepted.length) $('changes-status').textContent = 'No external changes.';
    controls(); dialog.showModal();
  }};
}
