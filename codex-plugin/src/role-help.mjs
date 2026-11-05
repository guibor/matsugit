const descriptions = {
  Section: ['Section', 'H1', 'Groups slides into a topic.'],
  Slide: ['Slide title', 'H2', 'Names a slide.'],
  Claim: ['Claim / subtitle', 'H3', 'The smaller statement directly below a slide title.'],
  Region: ['Body region', 'H4', 'A supporting-content group within a slide.'],
  takeaway: ['Takeaway', '', 'The separate conclusion beneath the supporting content.'],
  notes: ['Presenter notes', '', 'Additional presenter context, separate from the main content.'],
  source: ['Source', '', 'Supporting evidence or attribution.'],
  'agent-comment': ['Agent comment', '', 'A review request hidden from rendered output.'],
  columns: ['Columns', '', 'Supporting content arranged side by side.'],
  rows: ['Rows', '', 'Supporting content arranged vertically.'],
};

export function roleDescription(role, closing = false) {
  const [label, syntax, detail] = descriptions[role] || [role.replaceAll('-', ' '), '', 'A semantic content block.'];
  return {label: (closing ? 'End of ' : '') + label, syntax, detail};
}

export function installRoleHelp(root, popup) {
  let active, pinned = false;
  const close = () => {
    active?.removeAttribute('aria-describedby');
    active = null; pinned = false; popup.hidden = true;
  };
  const show = button => {
    close(); active = button;
    const description = roleDescription(button.dataset.role, button.dataset.closing === 'true');
    const title = document.createElement('strong'), detail = document.createElement('span');
    title.textContent = description.label + (description.syntax ? ` / ${description.syntax}` : '');
    detail.textContent = description.detail;
    popup.replaceChildren(title, detail); popup.hidden = false;
    button.setAttribute('aria-describedby', popup.id);
    const anchor = button.getBoundingClientRect(), bounds = popup.getBoundingClientRect();
    popup.style.left = Math.max(8, Math.min(anchor.right + 8, innerWidth - bounds.width - 8)) + 'px';
    popup.style.top = Math.max(8, Math.min(anchor.top, innerHeight - bounds.height - 8)) + 'px';
  };
  const marker = event => event.target.closest?.('.ff-gutter-marker');
  root.addEventListener('pointerover', event => {
    const button = marker(event);
    if (button && !pinned && active !== button) show(button);
  });
  root.addEventListener('pointerout', event => {
    if (!pinned && marker(event) && !marker(event)?.contains(event.relatedTarget)
        && !popup.contains(event.relatedTarget)) close();
  });
  root.addEventListener('focusin', event => { const button = marker(event); if (button) show(button); });
  root.addEventListener('focusout', event => { if (!pinned && marker(event)) close(); });
  root.addEventListener('click', event => {
    const button = marker(event);
    if (!button) return;
    if (active === button && pinned) close();
    else { show(button); pinned = true; }
  });
  popup.addEventListener('pointerleave', () => { if (!pinned) close(); });
  document.addEventListener('pointerdown', event => { if (!marker(event) && !popup.contains(event.target)) close(); });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && active) { close(); event.preventDefault(); event.stopPropagation(); }
  }, true);
  root.addEventListener('scroll', close, true);
  window.addEventListener('resize', close);
}
