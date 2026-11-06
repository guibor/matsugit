import {createElement, X} from 'lucide';
import {storyModel, moveStory, moveDestinations} from './story-model.mjs';

export function storyMove({text, org, enabled, apply}) {
  const $ = id => document.getElementById(id);
  const dialog = $('story-move-dialog'), search = $('story-move-search');
  const list = $('story-destinations'), position = $('story-move-position');
  const submit = $('story-move-apply'), status = $('story-move-status');
  let snapshot, format, model, source, candidates = [], index = 0;
  $('story-move-close').append(createElement(X));
  $('story-move-close').onclick = () => dialog.close();

  function valid() {
    if (snapshot !== text() || format !== org()) {
      status.textContent = 'Draft changed. Close this dialog and choose the destination again.';
      return false;
    }
    if (!enabled()) { status.textContent = 'Moving is unavailable while the draft is locked.'; return false; }
    return true;
  }
  function plan() {
    submit.disabled = true;
    if (!valid()) return null;
    const target = candidates[index];
    if (!target) { status.textContent = 'No matching destinations.'; return null; }
    try {
      const result = moveStory(snapshot, source.from, target.from, position.value, format);
      status.textContent = result ? `${position.selectedOptions[0].textContent}: ${target.label}` : 'Already at this position.';
      submit.disabled = !result;
      return result;
    } catch (error) { status.textContent = error.message; return null; }
  }
  function choose(next, scroll = true) {
    index = Math.max(0, Math.min(next, candidates.length-1));
    const previous = position.value;
    position.replaceChildren();
    for (const [value,label] of candidates[index]?.placements || []) {
      const option = document.createElement('option'); option.value = value; option.textContent = label;
      position.append(option);
    }
    if ([...position.options].some(o => o.value === previous)) position.value = previous;
    position.disabled = !candidates.length;
    [...list.children].forEach((el,i) => el.setAttribute('aria-selected', String(i === index)));
    const active = list.children[index];
    if (active) {
      search.setAttribute('aria-activedescendant',active.id);
      if (scroll) active.scrollIntoView({block:'nearest'});
    } else search.removeAttribute('aria-activedescendant');
    plan();
  }
  function filter() {
    candidates = moveDestinations(model,source.from,search.value);
    list.replaceChildren();
    candidates.forEach((target,i) => {
      const row = document.createElement('button');
      row.type = 'button'; row.role = 'option'; row.tabIndex = -1;
      row.id = `story-destination-${i}`; row.className = `story-destination story-destination-${target.kind}`;
      row.setAttribute('aria-label', `${target.label}. ${target.context}${target.claim ? '. '+target.claim : ''}`);
      for (const [style,value] of [['label',target.label],['context',target.context],['claim',target.claim]]) {
        if (!value) continue;
        const line = document.createElement('span'); line.className = `story-destination-${style}`;
        line.textContent = value; row.append(line);
      }
      row.onclick = () => choose(i);
      list.append(row);
    });
    list.scrollTop = 0;
    choose(0,false);
  }
  function keys(event) {
    if (event.isComposing || event.altKey || event.ctrlKey || event.metaKey) return;
    if (['ArrowDown','ArrowUp'].includes(event.key)) {
      event.preventDefault(); choose(index + (event.key === 'ArrowDown' ? 1 : -1)); search.focus();
    }
  }
  search.oninput = filter; search.onkeydown = keys; list.onkeydown = keys;
  dialog.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !event.isComposing) {
      event.preventDefault(); dialog.close();
    }
  });
  position.onchange = plan;
  $('story-move-form').onsubmit = event => {
    event.preventDefault();
    const result = plan();
    if (result) { dialog.close(); apply(result, 'Moved with all attached content. Unsaved.'); }
  };
  return {
    open(from) {
      if (!enabled()) return;
      snapshot = text(); format = org(); model = storyModel(snapshot,format);
      source = model.nodes.find(n => n.from === from);
      if (!source || !['slide','section'].includes(source.kind)) return;
      $('story-move-title').textContent = source.kind === 'slide' ? `Move slide ${source.number}` : 'Move section';
      $('story-move-source').textContent = source.label;
      search.value = ''; position.replaceChildren(); filter();
      dialog.showModal(); search.focus();
    },
    update() { if (dialog.open) plan(); },
  };
}
