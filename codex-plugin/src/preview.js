function ephemeralStorage() {
  for (const name of ['localStorage', 'sessionStorage']) {
    try { void window[name].length; }
    catch {
      const values = new Map();
      Object.defineProperty(window, name, {value: {
        get length() { return values.size; },
        key(index) { return [...values.keys()][index] ?? null; },
        getItem(key) { return values.get(String(key)) ?? null; },
        setItem(key, value) { values.set(String(key), String(value)); },
        removeItem(key) { values.delete(String(key)); },
        clear() { values.clear(); },
      }});
    }
  }
}
import {headingKey} from './structure.mjs';

export function applyChanges(document, changes) {
  if (!Array.isArray(changes)) throw Error('Invalid preview patch');
  const markers = new Map(), walker = document.createTreeWalker(document, 128);
  while (walker.nextNode()) {
    const match = /^ff-preview-(start|end):(ffp-\d+)$/.exec(walker.currentNode.data);
    if (match) { const key = match[1] + ':' + match[2]; markers.set(key, [...(markers.get(key) || []), walker.currentNode]); }
  }
  const updates = changes.map(({id, html}) => {
    if (!/^ffp-\d+$/.test(id) || typeof html !== 'string') throw Error('Invalid preview region');
    const matches = document.querySelectorAll(`[data-ff-preview="${id}"]`);
    const start = markers.get('start:' + id) || [], end = markers.get('end:' + id) || [];
    if (!(matches.length === 1 && !start.length && !end.length)
        && !(matches.length === 0 && start.length === 1 && end.length === 1
          && start[0].parentNode === end[0].parentNode && (start[0].compareDocumentPosition(end[0]) & 4))) {
      throw Error('Preview region changed; rebuilding');
    }
    const template = document.createElement('template'); template.innerHTML = html;
    for (const el of template.content.querySelectorAll('*')) {
      if (!['A', 'EM', 'STRONG', 'S', 'DEL', 'SUP', 'SUB', 'U', 'SPAN', 'BR'].includes(el.tagName)) throw Error('Unsupported preview markup');
      for (const attr of el.attributes) {
        if (!['href', 'title', 'class'].includes(attr.name)) throw Error('Unsupported preview attribute');
        if (attr.name === 'href' && !/^(https?:\/\/|mailto:|tel:|#)/.test(attr.value)) throw Error('Unsupported preview link');
      }
    }
    return {el: matches[0], start: start[0], end: end[0], content: template.content};
  });
  // Validate the entire patch before mutating any region.
  const slides = new Set();
  for (const {el, start, end, content} of updates) {
    slides.add((el || start.parentElement).closest('section'));
    if (el) el.replaceChildren(content);
    else {
      const range = document.createRange(); range.setStartAfter(start); range.setEndBefore(end);
      range.deleteContents(); range.insertNode(content);
    }
  }
  return slides;
}

export function patchedHtml(html, changes) {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  applyChanges(parsed, changes);
  return '<!doctype html>' + parsed.documentElement.outerHTML;
}

function navigation(format, position, token, headingKey, base, applyChanges) {
  let lastInput = 0, suppressUntil = 0, currentTarget;
  const post = data => parent.postMessage({...data, folioforgePreview: token}, '*');
  window.addEventListener('message', event => {
    if (event.source !== parent || event.data?.folioforgePreview !== token || !event.data.patch) return;
    const patch = event.data.patch;
    try {
      if (patch.base !== base) throw Error('Preview revision changed');
      const slides = applyChanges(document, patch.changes);
      if (format === 'slides' && window.Reveal?.isReady()) {
        for (const slide of slides) if (slide) Reveal.syncSlide(slide);
        Reveal.layout();
      }
      base = patch.next;
      window.dispatchEvent(new Event('resize'));
      post({patched: patch.next});
    } catch (error) { post({patched: patch.next, patchError: error.message}); }
  });
  const headings = () => [...document.querySelectorAll(format === 'slides'
    ? '.reveal .slides h1,.reveal .slides h2,.reveal .slides h3,.reveal .slides [role="heading"]'
    : 'main h1,main h2,main h3,main h4,main h5,main h6,main [role="heading"]')]
    .filter(el => !el.closest('.notes,.slide-menu'));
  const info = el => {
    if (!el) return null;
    const copy = el.cloneNode(true); copy.querySelectorAll('.anchorjs-link,.anchor').forEach(a => a.remove());
    return {key: headingKey(copy.textContent), level: Number(el.getAttribute('aria-level') || el.tagName.slice(1))};
  };
  const currentHeading = () => {
    const list = headings();
    const el = format === 'slides' ? window.Reveal?.getCurrentSlide()?.querySelector('h1,h2,h3,[role="heading"]')
      : list.filter(el => el.getBoundingClientRect().top <= 120).at(-1) || list[0];
    const current = info(el);
    if (!current) return null;
    return {...current, occurrence: list.filter(item => {
      const other = info(item); return other.key === current.key && other.level === current.level;
    }).indexOf(el)};
  };
  for (const name of ['pointerdown', 'wheel', 'keydown', 'touchstart']) document.addEventListener(name, () => {
    lastInput = Date.now(); currentTarget = null; suppressUntil = 0;
  }, {passive: true, capture: true});
  window.addEventListener('message', event => {
    if (event.source !== parent || event.data?.folioforgePreview !== token || !Array.isArray(event.data.targets)) return;
    const list = headings();
    for (const target of event.data.targets.slice(0, 8)) {
      if (typeof target.key !== 'string' || target.key.length > 4096) continue;
      let matches = list.filter(el => info(el).key === target.key && info(el).level === target.level);
      if (!matches.length) matches = list.filter(el => info(el).key === target.key);
      const el = matches[target.occurrence] || matches[0];
      if (!el) continue;
      if (el === currentTarget) break;
      currentTarget = el;
      suppressUntil = Date.now() + 1000;
      if (format === 'slides' && window.Reveal?.isReady()) {
        const indices = Reveal.getIndices(el.closest('section'));
        Reveal.slide(indices.h, indices.v);
      } else if (format === 'document') el.scrollIntoView({block: 'start'});
      break;
    }
  });
  document.addEventListener('click', event => {
    const anchor = event.target.closest('a');
    if (!anchor) return;
    const href = anchor.getAttribute('href') || '';
    if (/^(slides|index)\.html(?:#.*)?$/.test(href)) {
      event.preventDefault();
      post({folioforgeFormat: href.startsWith('slides') ? 'slides' : 'document'});
    } else {
      event.preventDefault();
      if (href.startsWith('#')) {
        location.hash = href;
        if (format === 'document') {
          try { document.getElementById(decodeURIComponent(href.slice(1)))?.scrollIntoView(); } catch {}
        }
      }
    }
  });
  let pending;
  const report = () => {
    clearTimeout(pending);
    pending = setTimeout(() => post({folioforgePosition: {
      format, hash: location.hash, scroll: window.scrollY,
      heading: currentHeading(), inputTime: lastInput,
      userNavigation: Date.now() - lastInput < 1500 && Date.now() > suppressUntil,
      ...(format === 'slides' && window.Reveal ? {...Reveal.getIndices(), slideId: Reveal.getCurrentSlide()?.id || ''} : {}),
    }}), 100);
  };
  window.addEventListener('hashchange', report);
  window.addEventListener('scroll', report, {passive: true});
  if (format === 'document' && position.scroll) window.addEventListener('load', () => {
    requestAnimationFrame(() => window.scrollTo(0, position.scroll));
  });
  if (format === 'slides') {
    let attempts = 0;
    const attach = () => {
      if (!window.Reveal?.on) { if (++attempts < 100) setTimeout(attach, 100); return; }
      Reveal.on('slidechanged', report);
      const restore = () => {
        const slide = position.slideId && document.getElementById(position.slideId);
        const indices = slide ? Reveal.getIndices(slide) : position;
        Reveal.slide(indices.h || 0, indices.v || 0);
        post({folioforgeReady: true});
      };
      if (Reveal.isReady()) restore(); else Reveal.on('ready', restore);
    };
    attach();
  } else window.addEventListener('load', () => post({folioforgeReady: true}));
}

export function previewHtml(html, format, position, token = '', base = null) {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  // Remove preview-only wrappers before display so theme selectors such as
  // `p > strong` retain exactly the export DOM hierarchy.
  for (const el of parsed.querySelectorAll('[data-ff-preview]')) {
    const id = el.getAttribute('data-ff-preview');
    if (/^ffp-\d+$/.test(id)) el.replaceWith(parsed.createComment('ff-preview-start:' + id),
      ...el.childNodes, parsed.createComment('ff-preview-end:' + id));
  }
  // Reveal's embedded menu resolves a relative script URL even when all assets
  // are inline. Blob URLs are not hierarchical; this reserved base grants no network access.
  const baseElement = parsed.createElement('base');
  baseElement.href = 'https://folioforge.invalid/';
  parsed.head.prepend(baseElement);
  // Quarto expects Storage; provide only ephemeral state inside the opaque frame.
  const storage = parsed.createElement('script');
  storage.textContent = `(${ephemeralStorage.toString()})();`;
  parsed.head.prepend(storage);
  const bridge = parsed.createElement('script');
  bridge.textContent = `(${navigation.toString()})(${JSON.stringify(format)},${JSON.stringify(position).replaceAll('<', '\\u003c')},${JSON.stringify(token)},${headingKey.toString()},${JSON.stringify(base)},${applyChanges.toString()});`;
  parsed.body.append(bridge);
  return '<!doctype html>' + parsed.documentElement.outerHTML;
}
