import {createElement, GripVertical, ArrowUp, ArrowDown, ArrowRightLeft, ChevronLeft, ChevronRight, ChevronDown, Code, Plus, FolderPlus, X} from 'lucide';
import {undo, redo, isolateHistory} from '@codemirror/commands';
import {Transaction} from '@codemirror/state';
import {storyModel, titleRange, moveStory, adjacentMove, insertStory, insertClaim} from './story-model.mjs';

const $ = id => document.getElementById(id);
function button(icon, name, run) {
  const el = document.createElement('button');
  el.type = 'button'; el.title = name; el.setAttribute('aria-label', name);
  el.append(createElement(icon)); el.onclick = run;
  return el;
}

export function storyView({editor, state, enabled, notice, sourceView, changed}) {
  const panel = $('story-pane'), list = $('story-list');
  let model, renderedSource = '', editing = null, ownInput = false, drag = null, frame, scrollFrame;
  const collapsed = new Set();
  const text = () => editor.state.doc.toString();
  const org = () => state.name.toLowerCase().endsWith('.org');
  const active = () => state.layout === 'story';
  const walkthrough = () => state.storyMode === 'walkthrough';
  const say = message => { $('story-status').textContent = message; };
  const refresh = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(render); };
  const select = from => editor.dispatch({selection:{anchor:from}});
  const fields = () => [...model.nodes, ...model.slides.flatMap(n => n.claims.filter(c => c.block))];
  const owner = node => node?.kind === 'claim' ? node.parent : node;
  function focus(from) {
    const row = list.querySelector(`[data-from="${from}"]`);
    row?.focus({preventScroll:true}); row?.scrollIntoView({block:walkthrough() ? 'start' : 'nearest'});
  }
  function currentSlide() {
    const selected = owner(model?.nodes.findLast(n => n.from <= editor.state.selection.main.head));
    return selected?.kind === 'slide' ? selected : selected?.children.find(n => n.kind === 'slide') || model?.slides[0];
  }
  function navigation() {
    const index = model?.slides.indexOf(currentSlide()) ?? -1;
    $('story-navigation').hidden = !walkthrough();
    $('story-position').textContent = `${index + 1} / ${model?.slides.length || 0}`;
    $('story-previous').disabled = index <= 0;
    $('story-next').disabled = index < 0 || index >= model.slides.length - 1;
  }
  function visit(direction) {
    finishEdit(); render();
    const index = model.slides.indexOf(currentSlide()), next = model.slides[index + direction];
    if (next) focus(next.from);
  }
  function visibleSlide() {
    const bounds = list.getBoundingClientRect(), rows = [...list.querySelectorAll('.story-slide')];
    const target = bounds.top + Math.min(120, bounds.height / 3);
    const visible = rows.filter(row => {
      const box = row.getBoundingClientRect(); return box.bottom > bounds.top && box.top < bounds.bottom;
    });
    return visible.find(row => {
      const box = row.getBoundingClientRect(); return box.top <= target && box.bottom >= target;
    }) || visible[0];
  }
  for (const control of panel.querySelectorAll('[data-story-mode]')) control.onclick = () => {
    finishEdit();
    const current = list.querySelector('.story-selected'), bounds = list.getBoundingClientRect();
    const box = current?.getBoundingClientRect();
    const anchor = box && box.bottom > bounds.top && box.top < bounds.bottom ? Number(current.dataset.from)
      : Number(visibleSlide()?.dataset.from ?? currentSlide()?.from ?? 0);
    state.storyMode = control.dataset.storyMode;
    // A slide remains in view when returning to an overview with folded sections.
    const node = model.nodes.find(n => n.from === anchor);
    if (node?.parent) collapsed.delete(node.parent.from);
    render(); focus(anchor); changed();
  };
  $('story-previous').append(createElement(ChevronLeft)); $('story-previous').onclick = () => visit(-1);
  $('story-next').append(createElement(ChevronRight)); $('story-next').onclick = () => visit(1);
  list.addEventListener('scroll', () => {
    cancelAnimationFrame(scrollFrame);
    scrollFrame = requestAnimationFrame(() => {
      if (!active() || !walkthrough() || editing || renderedSource !== text()) return;
      const row = visibleSlide();
      if (row && Number(row.dataset.from) !== currentSlide()?.from) select(Number(row.dataset.from));
    });
  }, {passive:true});
  function apply(result, message) {
    if (!result) return;
    if (!enabled()) return;
    collapsed.clear();
    editor.dispatch({changes:result.changes, selection:{anchor:result.anchor},
      annotations:[isolateHistory.of('full'), Transaction.userEvent.of('move.story')]});
    render(); focus(result.anchor); say(message);
  }
  function move(from, target, placement) {
    try { apply(moveStory(text(), from, target, placement, org()), 'Moved with all attached content. Unsaved.'); }
    catch (error) { notice(error.message); }
  }
  function step(from, direction) {
    try { apply(adjacentMove(text(), from, direction, org()), 'Moved with all attached content. Unsaved.'); }
    catch (error) { notice(error.message); }
  }
  function finishEdit() {
    if (!editing) return;
    if (!editing.input.value.trim()) say('Empty title was not applied.');
    editing = null;
    editor.dispatch({annotations:isolateHistory.of('after')});
    refresh();
  }
  function edit(node) {
    if (!enabled()) return;
    finishEdit();
    render();
    node = fields().find(n => n.from === node.from);
    const body = node && list.querySelector(`[data-heading="${node.from}"]`);
    if (!body) return;
    let range;
    try { range = titleRange(text(), node, org()); }
    catch (error) { notice(error.message); return; }
    const input = document.createElement('textarea');
    input.rows = 1; input.value = range.text; input.setAttribute('aria-label', `Edit ${node.kind} title`);
    input.className = 'story-edit'; input.spellcheck = true;
    const current = {input, ...range, heading:node.from, snapshot:text()};
    editing = current;
    editor.dispatch({annotations:isolateHistory.of('before')});
    body.replaceChildren(input);
    const size = () => { input.style.height = 'auto'; input.style.height = `${input.scrollHeight}px`; };
    input.oninput = () => {
      if (editing !== current || text() !== current.snapshot || !enabled()) {
        notice('The source changed while editing this title. Your earlier edits remain in the draft.'); finishEdit(); return;
      }
      const value = input.value.replace(/[\r\n\u0000]+/g, ' ');
      if (value !== input.value) input.value = value;
      size();
      if (!value.trim()) { input.setCustomValidity('A title cannot be empty.'); return; }
      input.setCustomValidity('');
      ownInput = true;
      try {
        editor.dispatch({changes:{from:current.from,to:current.to,insert:value},
          selection:{anchor:current.from + Math.min(input.selectionEnd, value.length)},
          annotations:Transaction.userEvent.of('input.story')});
        current.to = current.from + value.length; current.snapshot = text();
      } finally { ownInput = false; }
    };
    input.onblur = finishEdit;
    input.onkeydown = event => {
      if (event.isComposing) return;
      if (event.key === 'Enter' || event.key === 'Escape') {
        event.preventDefault(); finishEdit(); render(); focus(owner(node)?.from);
      } else if (event.key === 'Tab') {
        const items = [...list.querySelectorAll('[data-heading]')];
        const index = items.indexOf(body), next = items[index + (event.shiftKey ? -1 : 1)];
        if (next) {
          event.preventDefault();
          const heading = fields().find(n => n.from === Number(next.dataset.heading));
          edit(heading);
        }
      } else if ((event.metaKey || event.ctrlKey) && ['z','y'].includes(event.key.toLowerCase())) {
        event.preventDefault(); finishEdit();
        (event.shiftKey || event.key.toLowerCase() === 'y' ? redo : undo)(editor); render();
      }
    };
    input.focus(); size(); input.select();
  }
  function addClaim(node) {
    const result = insertClaim(text(),node,org());
    apply(result, 'Claim added. Unsaved.');
    const claim = model.nodes.find(n => n.from === result.anchor);
    if (claim) edit(claim);
  }
  function destination(node) {
    const dialog = $('story-move-dialog'), select = $('story-destination');
    const snapshot = text(); select.replaceChildren();
    for (const section of model.sections) {
      const option = document.createElement('option'); option.value = String(section.from);
      option.textContent = section.label || 'Untitled section';
      option.selected = section.from === node.parent?.from; select.append(option);
    }
    $('story-move-apply').onclick = () => {
      if (snapshot !== text()) { notice('The draft changed. Choose the destination again.'); dialog.close(); return; }
      move(node.from, Number(select.value), 'inside'); dialog.close();
    };
    dialog.showModal();
  }
  $('story-move-close').append(createElement(X));
  $('story-move-close').onclick = () => $('story-move-dialog').close();
  $('story-new-close').append(createElement(X));
  $('story-new-close').onclick = () => $('story-new-dialog').close();
  function newSlide() {
    if (!enabled()) return;
    const snapshot = text(), position = editor.state.selection.main.head;
    const dialog = $('story-new-dialog'), title = $('story-new-slide-title'), claim = $('story-new-claim');
    title.value = ''; claim.value = '';
    $('story-new-form').onsubmit = event => {
      event.preventDefault();
      if (!enabled()) return;
      if (snapshot !== text()) { notice('The draft changed. Close this form and choose the insertion point again.'); return; }
      try {
        const result = insertStory(text(),position,'slide',org(),{title:title.value,claim:claim.value.replace(/[\r\n]+/g,' ')});
        dialog.close(); apply(result,'Slide added with an empty body. Unsaved.');
      } catch (error) { notice(error.message); }
    };
    dialog.showModal(); title.focus();
  }
  for (const [kind, icon] of [['slide',Plus],['section',FolderPlus]]) {
    const el = $(`story-add-${kind}`); el.append(createElement(icon));
    if (kind === 'slide') el.append('Add slide');
    el.onclick = () => {
      try {
        finishEdit();
        if (kind === 'slide') { newSlide(); return; }
        const result = insertStory(text(),editor.state.selection.main.head,kind,org());
        apply(result,`${kind === 'slide' ? 'Slide' : 'Section'} added. Unsaved.`);
        const node = model.nodes.find(n => n.from === result.anchor);
        if (node) edit(node);
      } catch (error) { notice(error.message); }
    };
  }
  function render() {
    if (!active() || editing) return;
    const source = text(); renderedSource = source; model = storyModel(source, org());
    const focused = list.contains(document.activeElement) ? document.activeElement.closest('[data-from]')?.dataset.from : null;
    const scrollTop = list.scrollTop;
    panel.dataset.storyMode = walkthrough() ? 'walkthrough' : 'overview';
    for (const control of panel.querySelectorAll('[data-story-mode]'))
      control.setAttribute('aria-pressed',String(control.dataset.storyMode === panel.dataset.storyMode));
    list.replaceChildren();
    for (const kind of ['slide','section']) $(`story-add-${kind}`).disabled = !enabled();
    const empty = model.slides.filter(n => n.empty).length;
    $('story-count').textContent = `${model.slides.length} slides${empty ? ` / ${empty} empty` : ''}`;
    $('story-empty').hidden = !!model.sections.length || !!model.slides.length;
    const selected = owner(model.nodes.findLast(n => n.from <= editor.state.selection.main.head));
    for (const node of model.nodes) {
      if (node.kind === 'claim') continue;
      let parent = node.parent, hidden = false;
      while (parent) { if (!walkthrough() && collapsed.has(parent.from)) hidden = true; parent = parent.parent; }
      if (hidden) continue;
      const row = document.createElement('div');
      row.className = `story-row story-${node.kind}`; row.dataset.from = node.from;
      row.classList.toggle('story-nested',node.kind === 'slide' && node.parent?.kind === 'section');
      row.tabIndex = 0; row.setAttribute('role','listitem');
      row.addEventListener('click', event => {
        if (text() !== renderedSource) { event.preventDefault(); event.stopPropagation(); refresh(); }
      },true);
      row.addEventListener('keydown', event => {
        if (!event.target.matches('textarea') && text() !== renderedSource) { event.preventDefault(); event.stopPropagation(); refresh(); }
      },true);
      row.setAttribute('aria-label', `${node.kind}: ${node.label}`);
      row.classList.toggle('story-selected', selected?.from === node.from);
      row.onfocus = () => select(node.from);
      const marker = document.createElement('div'); marker.className = 'story-marker';
      marker.title = node.kind === 'slide' ? 'Slide title (H2)' : 'Section (H1)';
      if (node.kind === 'section') {
        const toggle = button(collapsed.has(node.from) ? ChevronRight : ChevronDown, 'Fold section', () => {
          collapsed.has(node.from) ? collapsed.delete(node.from) : collapsed.add(node.from); render(); focus(node.from);
        });
        toggle.setAttribute('aria-expanded',String(!collapsed.has(node.from))); marker.append(toggle);
      } else marker.textContent = String(node.number).padStart(2,'0');
      const context = document.createElement('div'); context.className = 'story-context';
      context.textContent = node.kind === 'slide' ? node.parent?.label || '' : '';
      const body = document.createElement('div'); body.className = 'story-body';
      function field(heading) {
        const slot = document.createElement('div'); slot.dataset.heading = heading.from;
        slot.className = heading.kind === 'claim' ? 'story-claim' : 'story-heading';
        const title = document.createElement('button'); title.type = 'button'; title.className = 'story-title';
        title.textContent = heading.label || 'Untitled'; title.title = `Edit ${heading.kind} title`;
        title.disabled = !enabled(); title.onclick = () => { select(heading.from); edit(heading); };
        slot.append(title); body.append(slot);
      }
      field(node);
      if (node.kind === 'section') {
        const count = document.createElement('small'), slides = node.children.filter(c => c.kind === 'slide').length;
        count.textContent = `${slides} slide${slides === 1 ? '' : 's'}`;
        body.append(count);
      } else {
        for (const claim of node.claims) field(claim);
        if (!node.claims.length) {
          const add = button(Plus,'Add claim',() => addClaim(node));
          add.className = 'story-add-claim'; add.append('Claim'); add.disabled = !enabled(); body.append(add);
        }
        if (node.empty || node.continuations) {
          const count = document.createElement('small');
          count.textContent = node.empty ? 'Empty body' : `+ ${node.continuations} continuation${node.continuations > 1 ? 's' : ''}`;
          count.className = 'story-detail'; body.append(count);
        }
      }
      const actions = document.createElement('div'); actions.className = 'story-actions';
      if (node.kind !== 'claim') {
        const handle = button(GripVertical, `Drag ${node.kind}`, () => { select(node.from); focus(node.from); });
        handle.draggable = enabled(); handle.dataset.drag = 'true'; actions.append(handle);
        const siblings = (node.parent?.children || model.roots).filter(n => n.kind === node.kind);
        const index = siblings.indexOf(node);
        for (const [direction, icon, label] of [[-1,ArrowUp,'Move up'],[1,ArrowDown,'Move down']]) {
          const control = button(icon, label, () => step(node.from,direction));
          control.disabled = !enabled() || !siblings[index+direction]; actions.append(control);
        }
        if (node.kind === 'slide') {
          const control = button(ArrowRightLeft, 'Move to section', () => destination(node));
          control.disabled = !enabled() || !model.sections.length; actions.append(control);
        }
        handle.disabled = !enabled();
        handle.ondragstart = event => {
          if (!enabled() || renderedSource !== text()) { event.preventDefault(); refresh(); return; }
          drag = {from:node.from, kind:node.kind, snapshot:text()};
          event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', node.label);
        };
        handle.ondragend = () => { drag = null; list.querySelectorAll('[data-drop]').forEach(el => delete el.dataset.drop); };
        row.ondragover = event => {
          if (!drag || drag.from === node.from || !enabled()) return;
          if (drag.kind !== node.kind && !(drag.kind === 'slide' && node.kind === 'section')) return;
          event.preventDefault(); event.dataTransfer.dropEffect = 'move';
          row.dataset.drop = drag.kind !== node.kind ? 'inside'
            : event.clientY > row.getBoundingClientRect().top + row.clientHeight / 2 ? 'after' : 'before';
        };
        row.ondragleave = event => { if (!row.contains(event.relatedTarget)) delete row.dataset.drop; };
        row.ondrop = event => {
          const placement = row.dataset.drop; delete row.dataset.drop;
          if (!drag || !placement) return;
          event.preventDefault();
          if (drag.snapshot !== text()) notice('The draft changed during the drag. Move it again.');
          else move(drag.from,node.from,placement);
          drag = null;
        };
      }
      actions.append(button(Code, 'Open in source', () => sourceView(node.from)));
      row.append(marker,context,body,actions);
      row.onkeydown = event => {
        if (event.target.matches('textarea,select')) return;
        if (walkthrough() && ['PageUp','PageDown'].includes(event.key)) {
          event.preventDefault(); visit(event.key === 'PageUp' ? -1 : 1);
        } else if (event.altKey && ['ArrowUp','ArrowDown'].includes(event.key)) {
          event.preventDefault(); step(node.from,event.key === 'ArrowUp' ? -1 : 1);
        } else if (event.target === row && ['ArrowUp','ArrowDown'].includes(event.key)) {
          event.preventDefault(); (event.key === 'ArrowUp' ? row.previousElementSibling : row.nextElementSibling)?.focus();
        } else if (event.target === row && event.key === 'Enter') {
          event.preventDefault(); edit(node);
        } else if (!walkthrough() && event.target === row && ['ArrowLeft','ArrowRight'].includes(event.key) && node.kind === 'section') {
          event.preventDefault(); event.key === 'ArrowLeft' ? collapsed.add(node.from) : collapsed.delete(node.from); render(); focus(node.from);
        }
      };
      list.append(row);
    }
    list.scrollTop = scrollTop;
    if (focused) list.querySelector(`[data-from="${focused}"]`)?.focus({preventScroll:true});
    navigation();
  }
  panel.addEventListener('keydown', event => {
    if (event.target.matches('textarea')) return;
    if ((event.metaKey || event.ctrlKey) && ['z','y'].includes(event.key.toLowerCase())) {
      event.preventDefault(); if (enabled()) (event.shiftKey || event.key.toLowerCase() === 'y' ? redo : undo)(editor);
    }
  });
  return {
    refresh,
    finish:finishEdit,
    update(update) {
      if (ownInput) {
        // Inline edits change offsets for later rows. Keep their handlers current
        // without replacing the active textarea (or interrupting composition).
        for (const node of fields()) {
          node.from = update.changes.mapPos(node.from,-1);
          node.to = update.changes.mapPos(node.to,1);
          node.end = update.changes.mapPos(node.end,1);
          if (node.block) {
            node.startEnd = update.changes.mapPos(node.startEnd,-1);
            node.endFrom = update.changes.mapPos(node.endFrom,1);
          }
        }
        for (const row of list.children) row.dataset.from = update.changes.mapPos(Number(row.dataset.from),-1);
        for (const slot of list.querySelectorAll('[data-heading]')) slot.dataset.heading = update.changes.mapPos(Number(slot.dataset.heading),-1);
        const mapped = [...collapsed].map(pos => update.changes.mapPos(pos,-1));
        collapsed.clear(); mapped.forEach(pos => collapsed.add(pos));
        renderedSource = text();
        return;
      }
      if (update.docChanged) {
        editing = null;
        const mapped = [...collapsed].map(pos => update.changes.mapPos(Math.min(pos, update.startState.doc.length)));
        collapsed.clear(); mapped.forEach(pos => collapsed.add(pos));
        refresh();
      } else if (update.selectionSet && active() && !editing) {
        const node = owner(model?.nodes.findLast(n => n.from <= update.state.selection.main.head));
        for (const row of list.children) row.classList.toggle('story-selected',Number(row.dataset.from) === node?.from);
        navigation();
      }
    },
    reset() { editing = null; collapsed.clear(); cancelAnimationFrame(scrollFrame); say(''); refresh(); },
  };
}
