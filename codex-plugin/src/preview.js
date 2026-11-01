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
function navigation(format, position) {
  document.addEventListener('click', event => {
    const anchor = event.target.closest('a');
    if (!anchor) return;
    const href = anchor.getAttribute('href') || '';
    if (/^(slides|index)\.html(?:#.*)?$/.test(href)) {
      event.preventDefault();
      parent.postMessage({folioforgeFormat: href.startsWith('slides') ? 'slides' : 'document'}, '*');
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
    pending = setTimeout(() => parent.postMessage({folioforgePosition: {
      format, hash: location.hash, scroll: window.scrollY,
      ...(format === 'slides' && window.Reveal ? {...Reveal.getIndices(), slideId: Reveal.getCurrentSlide()?.id || ''} : {}),
    }}, '*'), 100);
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
      };
      if (Reveal.isReady()) restore(); else Reveal.on('ready', restore);
    };
    attach();
  }
}

export function previewHtml(html, format, position) {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  // Reveal's embedded menu resolves a relative script URL even when all assets
  // are inline. Blob URLs are not hierarchical; this reserved base grants no network access.
  const base = parsed.createElement('base');
  base.href = 'https://folioforge.invalid/';
  parsed.head.prepend(base);
  // Quarto expects Storage; provide only ephemeral state inside the opaque frame.
  const storage = parsed.createElement('script');
  storage.textContent = `(${ephemeralStorage.toString()})();`;
  parsed.head.prepend(storage);
  const bridge = parsed.createElement('script');
  bridge.textContent = `(${navigation.toString()})(${JSON.stringify(format)},${JSON.stringify(position).replaceAll('<', '\\u003c')});`;
  parsed.body.append(bridge);
  return '<!doctype html>' + parsed.documentElement.outerHTML;
}
