/* Read-only geometry checks. Never resize text, split slides or hide content. */
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
      const report = measure(slide);
      if (report) window.dispatchEvent(new CustomEvent('matsugit-fit', {detail: report}));
    }));
  }
  window.matsugitFit = {measure, schedule};
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
