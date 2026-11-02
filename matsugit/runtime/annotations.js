/* Named evidence, not authored pixel coordinates. Numbered notes work without JS. */
(() => {
  "use strict";
  const ns = "http://www.w3.org/2000/svg";
  let queued = false;
  function svgElement(name, attrs) {
    const node = document.createElementNS(ns, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    return node;
  }
  function draw() {
    queued = false;
    document.querySelectorAll(".ff-annotated").forEach((group, index) => {
      group.querySelector(":scope > .ff-annotation-lines")?.remove();
      const rect = group.getBoundingClientRect();
      if (!rect.width || !rect.height || !group.clientWidth || !group.clientHeight) return;
      const evidence = group.querySelector(":scope > .ff-evidence");
      const rail = group.querySelector(":scope > .ff-callouts");
      if (!evidence || !rail || rail.getBoundingClientRect().left <= evidence.getBoundingClientRect().right) return;
      const scaleX = rect.width / group.clientWidth, scaleY = rect.height / group.clientHeight;
      const svg = svgElement("svg", {class: "ff-annotation-lines", "aria-hidden": "true",
        viewBox: `0 0 ${group.clientWidth} ${group.clientHeight}`, focusable: "false"});
      const defs = svgElement("defs", {});
      const markerId = `ff-pointer-${index}`;
      const marker = svgElement("marker", {id: markerId, viewBox: "0 0 10 10", refX: "9", refY: "5",
        markerWidth: "6", markerHeight: "6", orient: "auto-start-reverse"});
      marker.append(svgElement("path", {d: "M 0 0 L 10 5 L 0 10 z", fill: "currentColor"}));
      defs.append(marker); svg.append(defs);
      for (const note of rail.querySelectorAll(":scope > .ff-callout")) {
        const target = [...evidence.querySelectorAll("[id]"), evidence].find(el => el.id === note.dataset.target);
        if (!target) continue;
        const a = note.getBoundingClientRect(), b = target.getBoundingClientRect();
        if (!b.width || !b.height) continue;
        const sx = (a.left - rect.left) / scaleX - 6;
        const sy = (a.top + Math.min(a.height / 2, 20 * scaleY) - rect.top) / scaleY;
        const ex = (b.right - rect.left) / scaleX + 5;
        const ey = (b.top + b.height / 2 - rect.top) / scaleY;
        if (sx <= ex) continue;
        const bend = Math.min(36, (sx - ex) / 2);
        svg.append(svgElement("path", {d: `M ${sx} ${sy} C ${sx-bend} ${sy}, ${ex+bend} ${ey}, ${ex} ${ey}`,
          fill: "none", stroke: "currentColor", "stroke-width": "1.5", "marker-end": `url(#${markerId})`}));
      }
      group.append(svg);
    });
  }
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(draw);
  }
  function start() {
    const groups = [...document.querySelectorAll(".ff-annotated")];
    if (!groups.length) return;
    const observer = window.ResizeObserver ? new ResizeObserver(schedule) : null;
    groups.forEach(group => {
      observer?.observe(group);
      group.querySelectorAll(".ff-annotation-target,.ff-callout").forEach(el => observer?.observe(el));
      group.querySelectorAll("img").forEach(img => img.addEventListener("load", schedule));
      group.querySelectorAll(".ff-callout-number").forEach(link => {
        link.addEventListener("click", event => {
          if (!group.closest(".reveal")) return;
          // Reveal rewrites fragment links as slide routes; these targets are evidence, not slides.
          const targetId = link.closest(".ff-callout").dataset.target;
          const target = [...group.querySelectorAll(".ff-annotation-target")].find(el => el.id === targetId);
          if (!target) return;
          event.preventDefault(); event.stopPropagation();
          target.setAttribute("tabindex", "-1");
          target.focus({preventScroll:true});
        });
      });
    });
    for (const event of ["ready", "slidechanged", "slidetransitionend", "resize", "scrollviewchange"])
      window.Reveal?.on(event, schedule);
    window.addEventListener("resize", schedule);
    window.addEventListener("beforeprint", draw);
    document.fonts?.ready.then(schedule);
    schedule();
  }
  if (document.readyState === "complete") start();
  else window.addEventListener("load", start, {once:true});
})();
