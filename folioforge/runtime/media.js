/* Fit media, never shrink text or crop diagrams. Quarto owns Mermaid rendering. */
(() => {
  "use strict";
  let queued = false;
  const number = value => parseFloat(value) || 0;
  const margins = el => {
    const style = getComputedStyle(el);
    return number(style.marginTop) + number(style.marginBottom);
  };
  const visible = el => getComputedStyle(el).display !== "none" && !el.matches("aside.notes");
  const flexible = el => el.matches(".ff-media.ff-fitted") || el.querySelector(".ff-media.ff-fitted");

  function prepare(slide) {
    for (const slot of slide.querySelectorAll(".ff-media")) {
      if (slot.closest(".media-natural")) continue;
      const media = slot.querySelector("img, svg.mermaid-js");
      if (!media) continue; // Mermaid may still be rendering asynchronously.
      slot.classList.add("ff-fitted");
      for (let parent = media.parentElement; parent && parent !== slot; parent = parent.parentElement) {
        parent.classList.add("ff-media-inner");
      }
      if (media.tagName.toLowerCase() === "svg") media.setAttribute("preserveAspectRatio", "xMidYMid meet");
      slot.style.height = "0px";
      const captions = [...slot.querySelectorAll("figcaption")];
      slot.style.height = `${captions.reduce((sum, caption) => sum + caption.scrollHeight, 0)}px`;
    }
  }

  function allocate(container, budget) {
    if (container.matches(".ff-media.ff-fitted")) {
      // If prose already exceeds the slide, retain usable media and let Reveal scroll.
      container.style.height = `${Math.max(96, Math.floor(budget))}px`;
      return;
    }
    const children = [...container.children].filter(visible);
    if (container.matches(".columns")) {
      for (const child of children.filter(flexible)) allocate(child, budget);
      return;
    }
    const rows = children.filter(flexible);
    if (!rows.length) return;
    const fixed = children.filter(el => !flexible(el))
      .reduce((sum, el) => sum + el.offsetHeight + margins(el), 0);
    const minimums = rows.map(el => el.offsetHeight);
    const reserved = fixed + rows.reduce((sum, el) => sum + margins(el), 0)
      + minimums.reduce((a, b) => a + b, 0);
    const extra = Math.max(0, budget - reserved) / rows.length;
    rows.forEach((el, index) => allocate(el, minimums[index] + extra));
  }

  function fit() {
    queued = false;
    if (!window.Reveal?.isReady()) return;
    const height = Number(Reveal.getConfig().height) || 720;
    // Mobile scroll view shows neighbouring slides too; size them before scrolling.
    const slides = Reveal.isScrollView?.() ? Reveal.getSlides() : [Reveal.getCurrentSlide()];
    for (const slide of slides) {
      if (!slide?.querySelector(".ff-media") || !slide.offsetWidth || slide.classList.contains("stack")) continue;
      prepare(slide);
      const style = getComputedStyle(slide);
      allocate(slide, height - number(style.paddingTop) - number(style.paddingBottom) - 24);
      slide.dataset.ffMediaReady = "true";
    }
  }
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(fit);
  }
  function start() {
    if (!document.querySelector(".reveal")) return;
    for (const img of document.querySelectorAll(".ff-media img")) img.addEventListener("load", schedule);
    new MutationObserver(schedule).observe(document.querySelector(".reveal .slides"), {childList: true, subtree: true});
    if (window.Reveal) {
      for (const event of ["ready", "slidechanged", "slidetransitionend", "resize", "scrollviewchange"]) {
        Reveal.on(event, schedule);
      }
    }
    window.addEventListener("resize", schedule);
    document.fonts?.ready.then(schedule);
    schedule();
  }
  if (document.readyState === "complete") start();
  else window.addEventListener("load", start, {once: true});
})();
