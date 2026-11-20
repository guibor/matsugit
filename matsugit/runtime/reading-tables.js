// Keep native table semantics and let only the overflowing table scroll.
document.addEventListener('DOMContentLoaded', () => {
  const root = document.querySelector('main.content, main.me-content');
  if (!root) return;
  for (const table of root.querySelectorAll('table')) {
    if (table.parentElement.closest('table')) continue;
    const box = document.createElement('div');
    box.className = 'matsugit-table-scroll';
    table.before(box);
    box.append(table);
    const update = () => {
      if (box.scrollWidth > box.clientWidth + 1) {
        box.tabIndex = 0;
        box.setAttribute('role', 'region');
        box.setAttribute('aria-label', table.caption?.textContent.trim() || 'Scrollable table');
      } else {
        for (const key of ['tabindex', 'role', 'aria-label']) box.removeAttribute(key);
      }
    };
    const observer = new ResizeObserver(update);
    observer.observe(box); observer.observe(table); update();
  }
});
