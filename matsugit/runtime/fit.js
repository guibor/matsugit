/* Bounded fitting preserves authored structure; measurement remains read-only. */
(() => {
  'use strict';
  // Reveal's scroll view can display sections that retain a hidden attribute.
  // Geometry/CSS, not that attribute, determines whether they can be measured.
  const excluded = '.notes,.speaker-notes,.slide-menu,.ff-annotation-lines,.ff-canvas-dialog';
  const shown = el => !el.closest(excluded) && el.getClientRects().length && getComputedStyle(el).display !== 'none';
  function measure(slide) {
    if (!slide || !shown(slide) || !slide.offsetWidth) return null;
    const box = slide.getBoundingClientRect(), scale = box.width / slide.offsetWidth;
    if (!(scale > 0)) return null;
    const config = window.Reveal.getConfig();
    const width = Number(config.width) || 1280, height = Number(config.height) || 720;
    const tolerance = 3 * scale;
    const parts = [...slide.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,table,pre,img,svg,.ff-claim,.ff-body,.ff-takeaway')].filter(shown);
    const overflow = parts.some(el => {
      const r = el.getBoundingClientRect();
      if (r.right > box.left + width * scale + tolerance || r.left < box.left - tolerance
          || r.bottom > box.top + height * scale + tolerance || r.top < box.top - tolerance) return true;
      // Also catch a fixed-size region clipping or scrolling its own content.
      for (let parent = el; parent && parent !== slide; parent = parent.parentElement) {
        if (parent.matches('.ff-canvas,.ff-canvas *')) continue;
        const css = getComputedStyle(parent);
        if ((css.overflowY !== 'visible' && parent.scrollHeight > parent.clientHeight + 3)
            || (css.overflowX !== 'visible' && parent.scrollWidth > parent.clientWidth + 3)) return true;
      }
      return false;
    });
    const regions = [...slide.children].filter(el => shown(el) && el.matches('h1,h2,.ff-claim,.ff-body,.ff-takeaway'));
    const overlap = regions.some((el, i) => regions.slice(i + 1).some(other => {
      const a = el.getBoundingClientRect(), b = other.getBoundingClientRect();
      return Math.min(a.right, b.right) - Math.max(a.left, b.left) > tolerance
        && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > tolerance;
    }));
    return {id: slide.id, title: slide.querySelector('h1,h2')?.textContent || slide.id,
      overflow, overlap, broken: [...slide.querySelectorAll('img')].some(el => shown(el) && el.complete && !el.naturalWidth)};
  }
  const applied = new WeakMap();
  const fixed = 'h1,h2,h3,h4,h5,h6,.ff-division-heading,.ff-claim,.takeaway,.ff-takeaway,.source,.notes,.ff-media,svg,pre,.ff-relation,.ff-callout-number';
  function reset(slide) {
    for (const [el, properties] of applied.get(slide) || []) for (const [name, value, priority] of properties)
      value ? el.style.setProperty(name, value, priority) : el.style.removeProperty(name);
    applied.delete(slide);
  }
  function fitSlide(slide) {
    if (!slide || !shown(slide) || !slide.querySelector('.ff-body')) return measure(slide);
    reset(slide);
    const saved = new Map();
    const set = (el, name, value) => {
      if (!saved.has(el)) saved.set(el, []);
      if (!saved.get(el).some(item => item[0] === name))
        saved.get(el).push([name, el.style.getPropertyValue(name), el.style.getPropertyPriority(name)]);
      el.style.setProperty(name, value, 'important');
    };
    const check = () => { window.matsugitMedia?.fitSlide(slide); return measure(slide); };
    let report = check();
    slide.dataset.ffFitScale = '1';
    slide.dataset.ffFitSpacing = 'normal';
    if (!report || (!report.overflow && !report.overlap) || slide.matches('.no-fit,[data-fit="off"]')) return report;
    const body = slide.querySelector('.ff-body');
    const eligible = [...body.querySelectorAll('*')].filter(el => shown(el) && !el.closest(fixed));
    // Measure every baseline before changing styles, avoiding inherited double scaling.
    const metrics = eligible.filter(el => [...el.childNodes].some(node => node.nodeType === 3 && node.textContent.trim()))
      .map(el => ({el, font:parseFloat(getComputedStyle(el).fontSize)}));
    const spaces = eligible.filter(el => el.matches('p,ul,ol,li')).map(el => ({el,
      top:parseFloat(getComputedStyle(el).marginTop), bottom:parseFloat(getComputedStyle(el).marginBottom)}));
    for (const {el, top, bottom} of spaces) {
      if (top > 0) set(el, 'margin-top', `${top * .7}px`);
      if (bottom > 0) set(el, 'margin-bottom', `${bottom * .7}px`);
    }
    slide.dataset.ffFitSpacing = 'compact';
    report = check();
    const css = getComputedStyle(slide);
    const floor = Math.max(16, parseFloat(css.getPropertyValue('--ff-fit-min-font-size')) || 20);
    const minimum = Math.max(.8, Math.min(1, parseFloat(css.getPropertyValue('--ff-fit-min-scale')) || .88));
    // Prose is one peer group per slide. Each table is a separate complete group.
    const groups = new Map();
    for (const item of metrics) {
      const key = item.el.closest('table') || body;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    let scale = 1;
    for (let step = 1; report && (report.overflow || report.overlap) && step <= 10; step++) {
      scale = Math.max(minimum, 1 - step * .02);
      for (const members of groups.values()) {
        const groupScale = members.reduce((value, {font}) => Math.max(value, Math.min(1, floor / font)), scale);
        for (const {el, font} of members) set(el, 'font-size', `${font * groupScale}px`);
      }
      report = check();
      if (scale <= minimum) break;
    }
    applied.set(slide, saved);
    slide.dataset.ffFitScale = String(scale);
    return report && {...report, adjusted:true, scale, unresolved:report.overflow || report.overlap};
  }
  let queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    // Media allocation and Reveal layout run first; measure on the following frame.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      queued = false;
      if (!window.Reveal?.isReady()) return;
      const slide = Reveal.getCurrentSlide();
      if (slide?.querySelector('img:not([loading="lazy"])') && [...slide.querySelectorAll('img')].some(img => !img.complete)) return;
      if (slide?.querySelector('pre.mermaid')) return;
      const slides = document.documentElement.classList.contains('print-pdf') || Reveal.isScrollView?.()
        ? Reveal.getSlides() : [slide];
      for (const item of slides) fitSlide(item);
      const report = measure(slide);
      if (report) window.dispatchEvent(new CustomEvent('matsugit-fit', {detail: report}));
    }));
  }
  window.matsugitFit = {measure, schedule, fitSlide, fitAll:() => Reveal.getSlides().map(fitSlide)};
  async function start() {
    const slides = document.querySelector('.reveal .slides');
    if (!slides) return;
    await document.fonts?.ready;
    if (window.MathJax?.startup?.promise) await MathJax.startup.promise.catch(() => {});
    slides.addEventListener('load', schedule, true);
    slides.addEventListener('error', schedule, true);
    new MutationObserver(schedule).observe(slides, {childList:true, subtree:true, characterData:true});
    for (const event of ['ready','slidechanged','slidetransitionend','resize']) window.Reveal?.on(event, schedule);
    window.addEventListener('resize', schedule);
    schedule();
  }
  if (document.readyState === 'complete') start();
  else window.addEventListener('load', start, {once:true});
})();
