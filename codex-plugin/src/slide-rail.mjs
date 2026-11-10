// A strip of the deck's slides under the workspace: where you are, a way to
// jump, and which slides Check has something to say about.
import {storyModel} from './story-model.mjs';

export function slideRail({root, text, isOrg, position, jump}) {
  let model = null, source = null, mode = null, previewPosition = null, marks = new Map(), current = -1;
  const read = () => {
    const value = text();
    const org = isOrg();
    if (value !== source || org !== mode) {
      source = value; mode = org; previewPosition = null; model = storyModel(value, org);
    }
    return model;
  };
  function paintCurrent() {
    const slides = read().slides, at = previewPosition ?? position();
    const index = slides.findLastIndex(slide => slide.from <= at);
    if (index === current) return;
    current = index;
    for (const chip of root.children) {
      const active = Number(chip.dataset.index) === index;
      chip.setAttribute('aria-current', String(active));
      if (active) chip.scrollIntoView({block: 'nearest', inline: 'nearest'});
    }
  }
  function paint() {
    const slides = read().slides;
    root.hidden = slides.length < 2;
    current = -2;
    root.replaceChildren(...slides.map((slide, index) => {
      const chip = document.createElement('button'), number = document.createElement('span'), label = document.createElement('span');
      chip.type = 'button'; chip.className = 'rail-slide'; chip.dataset.index = index;
      number.className = 'rail-number'; number.textContent = slide.number;
      label.className = 'rail-title'; label.textContent = slide.label || 'Untitled slide';
      const mark = marks.get(slide.number);
      if (mark) chip.dataset.mark = mark;
      chip.title = `Slide ${slide.number}: ${slide.label}` + (mark === 'problem' ? ' (needs fixing, see Check)' : mark === 'tip' ? ' (Check has a tip)' : '');
      chip.onclick = () => jump(read().slides[index]?.from ?? slide.from);
      chip.append(number, label);
      return chip;
    }));
    paintCurrent();
  }
  return {
    // Findings arrive from Check; a problem outranks a tip on the same slide.
    findings(list) {
      marks = new Map();
      for (const item of list) if (item.slide && marks.get(item.slide) !== 'problem') marks.set(item.slide, item.severity);
      paint();
    },
    moved() { previewPosition = null; paintCurrent(); },
    previewMoved(from) { previewPosition = from; paintCurrent(); },
  };
}
