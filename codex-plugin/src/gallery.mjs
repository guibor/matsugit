// Layout picker: choose a slide or a part by picture and plain name. It inserts
// the same recipe text as the "/" completion, into the single source draft.
import {EditorView} from '@codemirror/view';
import {snippet} from '@codemirror/autocomplete';
import {createElement, X} from 'lucide';
import {storyModel} from './story-model.mjs';
import {placeInsertion, wrapElement, snippetTemplate} from './insertions.mjs';

const $ = id => document.getElementById(id);
const SVG = 'http://www.w3.org/2000/svg';
// Thumbnails on a 96x54 slide: [style, x, y, width, height]. Styles: t title,
// l text line, b outlined box, a accent, s soft accent, f faded, w white.
const T = ['t', 8, 7, 40, 5], C = ['l', 8, 15, 56, 3], F = [['f', 8, 7, 40, 5], ['f', 8, 15, 56, 3]];
const SKETCHES = {
  slide: [T, C, ['l', 8, 25, 62, 3], ['l', 8, 32, 54, 3], ['l', 8, 39, 58, 3]],
  cover: [['t', 20, 18, 56, 7], ['l', 28, 30, 40, 3], ['l', 36, 38, 24, 2]],
  section: [['a', 0, 0, 96, 54], ['w', 10, 22, 44, 7], ['w', 10, 34, 24, 3]],
  statement: [['t', 14, 19, 68, 6], ['t', 22, 29, 52, 6]],
  summary: [T, C, ['s', 8, 23, 80, 9], ['l', 8, 37, 50, 3], ['l', 8, 43, 44, 3]],
  wide: [T, C, ['b', 8, 23, 50, 24], ['b', 62, 23, 26, 24]],
  stack: [T, C, ['b', 8, 22, 80, 12], ['b', 8, 37, 80, 10]],
  table: [T, C, ['b', 8, 23, 80, 24], ['l', 8, 30, 80, 1], ['l', 8, 36, 80, 1], ['l', 8, 42, 80, 1], ['l', 34, 23, 1, 24], ['l', 60, 23, 1, 24]],
  chart: [T, C, ['l', 10, 46, 76, 1], ['s', 16, 34, 12, 12], ['a', 36, 25, 12, 21], ['s', 56, 30, 12, 16]],
  metrics: [T, C, ...[8, 37, 66].flatMap(x => [['b', x, 23, 22, 22], ['a', x + 4, 28, 12, 5], ['l', x + 4, 37, 14, 2]])],
  columns: [T, C, ['b', 8, 23, 38, 24], ['b', 50, 23, 38, 24]],
  columns3: [T, C, ['b', 8, 23, 24, 24], ['b', 36, 23, 24, 24], ['b', 64, 23, 24, 24]],
  timeline: [T, C, ['l', 10, 31, 76, 1], ...[14, 44, 74].flatMap(x => [['a', x, 28, 6, 6], ['l', x - 4, 39, 16, 2]])],
  flow: [T, C, ['b', 8, 26, 20, 12], ['a', 29, 31, 8, 2], ['b', 38, 26, 20, 12], ['a', 59, 31, 8, 2], ['b', 68, 26, 20, 12]],
  quote: [['a', 14, 13, 4, 9], ['a', 20, 13, 4, 9], ['l', 30, 16, 50, 4], ['l', 30, 24, 42, 4], ['l', 54, 37, 26, 2]],
  arrow: [T, C, ['b', 8, 23, 32, 24], ['a', 43, 34, 10, 2], ['b', 56, 23, 32, 24]],
  mapping: [T, ...[18, 28, 38].flatMap(y => [['b', 8, y, 32, 7], ['a', 43, y + 3, 10, 2], ['b', 56, y, 32, 7]])],
  annotated: [T, ['b', 8, 18, 52, 28], ['a', 30, 27, 12, 5], ['s', 64, 19, 24, 9], ['s', 64, 33, 24, 9]],
  claim: [['f', 8, 7, 40, 5], ['a', 8, 15, 56, 4], ['f', 8, 27, 60, 3], ['f', 8, 34, 50, 3]],
  takeaway: [...F, ['f', 8, 25, 60, 3], ['f', 8, 31, 50, 3], ['a', 8, 40, 80, 8]],
  region: [...F, ['t', 8, 25, 28, 4], ['l', 8, 33, 50, 3], ['l', 8, 39, 44, 3]],
  source: [...F, ['f', 8, 25, 60, 3], ['f', 8, 32, 50, 3], ['a', 8, 44, 3, 3], ['l', 14, 44, 44, 2]],
  notes: [['b', 8, 6, 80, 27], ['f', 14, 12, 30, 4], ['f', 14, 20, 50, 3], ['s', 8, 37, 80, 11], ['l', 12, 41, 50, 2]],
  break: [['b', 6, 10, 38, 34], ['t', 10, 15, 20, 3], ['a', 45, 26, 6, 2], ['b', 52, 10, 38, 34], ['t', 56, 15, 20, 3]],
  comment: [['s', 20, 12, 56, 24], ['l', 28, 19, 40, 3], ['l', 28, 26, 30, 3], ['s', 30, 36, 8, 6]],
  canvas: [['b', 8, 8, 80, 38], ['a', 40, 20, 16, 14]],
};

function sketch(name) {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 96 54'); svg.setAttribute('aria-hidden', 'true'); svg.classList.add('gallery-sketch');
  for (const [style, x, y, width, height] of SKETCHES[name] || SKETCHES.slide) {
    const rect = document.createElementNS(SVG, 'rect');
    for (const [key, value] of Object.entries({x, y, width, height, rx: style === 'b' ? 1.5 : .8})) rect.setAttribute(key, value);
    rect.classList.add('sk-' + style); svg.append(rect);
  }
  return svg;
}

export function gallery({editor, recipes, isOrg, enabled, reveal, notice}) {
  const dialog = $('gallery-dialog'), search = $('gallery-search'), groups = $('gallery-groups'), status = $('gallery-status');
  const entries = Object.entries(recipes).filter(([, recipe]) => recipe.title).sort((a, b) => a[1].rank - b[1].rank);
  $('gallery-close').append(createElement(X));
  $('gallery-close').onclick = () => dialog.close();
  const tableSelected = () => {
    const selection = editor.state.selection.main;
    const text = editor.state.sliceDoc(selection.from, selection.to).trim();
    return !!text && text.split('\n').every(line => /^\s*\|.*\|\s*$/.test(line));
  };
  function target() {
    const model = storyModel(editor.state.doc.toString(), isOrg()), position = editor.state.selection.main.head;
    const current = model.nodes.filter(node => node.kind !== 'claim').findLast(node => node.from <= position);
    const slide = current?.kind === 'slide' ? current : model.slides.find(item => item.from >= position) || model.slides.at(-1);
    const name = node => `slide ${node.number}: ${node.label}`;
    return {
      slide: current?.kind === 'slide' ? `Added after ${name(current)}` : current ? `Added at the start of the section "${current.label}"` : 'Added at the end of the deck',
      part: slide ? `Added to ${name(slide)}` : 'Added at the end of the document',
    };
  }
  function choose(name, recipe) {
    const org = isOrg(), selection = editor.state.selection.main;
    let change;
    try {
      const wrap = name === 'chart-block' ? 'chart-barh' : name === 'takeaway' ? 'takeaway' : null;
      if (wrap && !selection.empty && (wrap === 'takeaway' || tableSelected()))
        change = {from: selection.from, to: selection.to, insert: wrapElement(wrap, editor.state.sliceDoc(selection.from, selection.to), org), placeholders: false};
      else change = placeInsertion(editor.state.doc.toString(), selection.head, name, recipe, org);
    } catch (error) { status.textContent = error.message; return; }
    dialog.close(); reveal();
    if (change.insert === undefined) {
      editor.dispatch({selection: {anchor: change.select.from, head: change.select.to}, effects: EditorView.scrollIntoView(change.select.from, {y: 'center'})});
      notice(change.message);
    } else if (change.placeholders === false) {
      editor.dispatch({changes: {from: change.from, to: change.to, insert: change.insert}, userEvent: 'input',
        selection: change.select ? {anchor: change.select.from, head: change.select.to} : {anchor: change.from + change.insert.length},
        effects: EditorView.scrollIntoView(change.from, {y: 'center'})});
    } else {
      const text = change.insert.replaceAll('review-INSERT_ID', 'review-' + crypto.randomUUID().replaceAll('-', '').slice(0, 12));
      snippet(snippetTemplate(text))(editor, null, change.from, change.to);
      editor.dispatch({effects: EditorView.scrollIntoView(editor.state.selection.main.head, {y: 'center'})});
    }
    editor.focus();
  }
  function paint() {
    const terms = search.value.toLowerCase().split(/\s+/).filter(Boolean), where = target();
    groups.replaceChildren();
    let shown = 0;
    for (const [group, heading] of [['slide', 'New slide'], ['part', 'Add to this slide']]) {
      const cards = entries.filter(([name, recipe]) => recipe.group === group
        && terms.every(term => `${recipe.title} ${recipe.when} ${name}`.toLowerCase().includes(term)));
      if (!cards.length) continue;
      const section = document.createElement('section'), title = document.createElement('h3'), note = document.createElement('span');
      title.textContent = heading; note.textContent = where[group]; title.append(note);
      const grid = document.createElement('div'); grid.className = 'gallery-grid';
      for (const [name, recipe] of cards) {
        const card = document.createElement('button'), copy = document.createElement('span');
        const label = document.createElement('strong'), when = document.createElement('small');
        card.type = 'button'; card.className = 'gallery-card'; card.dataset.recipe = name;
        label.textContent = name === 'chart-block' && tableSelected() ? 'Chart from the selected table' : recipe.title;
        when.textContent = recipe.when; copy.append(label, when);
        card.append(sketch(recipe.sketch), copy);
        card.onclick = () => choose(name, recipe);
        grid.append(card); shown++;
      }
      section.append(title, grid); groups.append(section);
    }
    status.textContent = shown ? '' : 'Nothing matches. Try another word, or describe what you want to the AI in chat.';
  }
  search.oninput = paint;
  search.onkeydown = event => {
    const cards = groups.querySelectorAll('.gallery-card');
    if (event.key === 'Enter' && cards.length === 1) { event.preventDefault(); cards[0].click(); }
    if (event.key === 'ArrowDown' && cards.length) { event.preventDefault(); cards[0].focus(); }
  };
  return {open() {
    if (!enabled()) return;
    search.value = ''; paint(); dialog.showModal(); search.focus();
  }};
}
