/* Reading-only disclosure. Source, slide layout and printed output stay intact. */
(() => {
  'use strict';
  function start() {
    if (document.querySelector('.reveal')) return;
    const root = document.querySelector('main.content') || document.querySelector('main');
    if (!root) return;
    const controls = new Map();
    function expand(section) {
      section.classList.remove('ff-folded');
      const button = controls.get(section);
      if (button) { button.setAttribute('aria-expanded', 'true'); button.title = 'Collapse section'; }
    }
    const marked = root.querySelectorAll('section.collapsible, div.collapsible, section:has(> :is(h1,h2,h3,h4,h5,h6).collapsible)');
    const foldable = new Set(marked);
    // A marked region includes its subsections, not unrelated sibling sections.
    for (const region of marked) for (const section of region.querySelectorAll('section')) foldable.add(section);
    for (const section of foldable) {
      if (!section.children.length) continue;
      let heading = section.firstElementChild;
      const hasHeading = /^H[1-6]$/.test(heading.tagName);
      if (hasHeading && (section.children.length < 2 || heading.querySelector('.ff-fold-toggle'))) continue;
      const title = hasHeading ? heading.textContent.trim() : section.getAttribute('title') || 'Details';
      if (!hasHeading) {
        heading = document.createElement('div');
        section.prepend(heading);
      }
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'ff-fold-toggle' + (hasHeading ? '' : ' ff-fold-block-toggle');
      if (!hasHeading) button.textContent = title;
      button.setAttribute('aria-label', 'Section: ' + title);
      button.setAttribute('aria-expanded', 'false'); button.title = 'Expand section';
      section.classList.add('ff-folded');
      heading.classList.add('ff-fold-heading');
      button.onclick = () => {
        if (section.classList.contains('ff-folded')) expand(section);
        else { section.classList.add('ff-folded'); button.setAttribute('aria-expanded', 'false'); button.title = 'Expand section'; }
        window.dispatchEvent(new Event('resize'));
      };
      controls.set(section, button); heading.prepend(button);
    }
    function reveal(target) {
      if (!target || !root.contains(target)) return;
      for (let node = target; node && node !== root; node = node.parentElement)
        if (node.classList.contains('ff-folded')) expand(node);
    }
    function fragment(hash) {
      try { return document.getElementById(decodeURIComponent(hash.slice(1))); } catch { return null; }
    }
    document.addEventListener('click', event => {
      const link = event.target.closest('a[href]');
      if (!link) return;
      const url = new URL(link.href, location.href);
      if (url.origin === location.origin && url.pathname === location.pathname && url.hash) reveal(fragment(url.hash));
    }, true);
    window.addEventListener('hashchange', () => {
      const target = fragment(location.hash); reveal(target); target?.scrollIntoView();
    });
    root.addEventListener('focusin', event => { if (!event.target.closest('.ff-fold-toggle')) reveal(event.target); });
    root.addEventListener('matsugit-reveal', event => reveal(event.target));
    reveal(fragment(location.hash));
    // Native find-in-page must not miss folded text.
    document.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') for (const section of controls.keys()) expand(section);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
