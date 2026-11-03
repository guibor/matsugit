/* Keep the same iframe alive when expanding: dialog top-layer escapes slide scaling. */
(() => {
  function start() {
    for (const dialog of document.querySelectorAll('.ff-canvas-dialog')) {
      const button = dialog.querySelector('.ff-canvas-expand');
      const frame = dialog.querySelector('.ff-canvas-frame');
      const title = dialog.getAttribute('aria-label');
      function toggle() {
        const expanded = dialog.matches(':modal');
        dialog.close();
        if (expanded) dialog.show(); else dialog.showModal();
        frame.inert = expanded;
        frame.tabIndex = expanded ? -1 : 0;
        button.textContent = expanded ? 'Expand' : 'Close';
        button.setAttribute('aria-label', (expanded ? 'Expand ' : 'Close ') + title);
        button.focus();
      }
      button.addEventListener('click', toggle);
      dialog.addEventListener('cancel', event => { event.preventDefault(); toggle(); });
      // Reveal's Escape handler must not take over while a canvas is expanded.
      window.addEventListener('keydown', event => {
        if (event.key === 'Escape' && dialog.matches(':modal')) {
          event.preventDefault();
          event.stopImmediatePropagation();
          toggle();
        }
      }, true);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
