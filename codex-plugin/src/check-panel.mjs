// "What's working, what's not": a status chip and a list of plain-language
// findings with Show / Fix / Ask AI. Fixes edit the draft as one Undo step and
// never save; the check itself never renders or calls a model.
import {createElement, CircleCheck, TriangleAlert, Lightbulb, X} from 'lucide';
import {checkDeck, checkSummary, rendererFinding} from './check.mjs';
import {storyModel} from './story-model.mjs';

const $ = id => document.getElementById(id);

// Backticked words in messages are source the reader may need to type.
function prose(text) {
  const fragment = document.createDocumentFragment();
  text.split(/(`[^`]+`)/).forEach(part => {
    if (part.startsWith('`') && part.length > 2) { const code = document.createElement('code'); code.textContent = part.slice(1, -1); fragment.append(code); }
    else if (part) fragment.append(part);
  });
  return fragment;
}

export function checkPanel({editor, isOrg, enabled, renderError, show, askAgent, toggled = () => {}, changed = () => {}}) {
  const chip = $('check-status'), panel = $('check-panel'), list = $('check-list'), feedback = $('check-feedback');
  let findings = [], timer, revision = null;
  $('check-close').append(createElement(X));
  const text = () => editor.state.doc.toString();
  function compute() {
    let found;
    try { found = checkDeck(text(), isOrg()); }
    catch (error) { found = [{code: 'check', severity: 'tip', slide: null, title: '', from: null, line: null,
      message: 'The check could not read this document.', how: error.message}]; }
    // The renderer is the authority. Show its message when the check has no
    // explanation of its own, so a failed preview is never left unexplained.
    const failure = renderError();
    if (failure && !found.some(item => item.severity === 'problem')) found.unshift(rendererFinding(failure));
    return found;
  }
  function item(finding) {
    const row = document.createElement('li'), head = document.createElement('div'), body = document.createElement('p');
    const how = document.createElement('p'), actions = document.createElement('div');
    row.className = 'check-item'; row.dataset.severity = finding.severity; row.dataset.code = finding.code;
    head.className = 'check-where';
    const kind = document.createElement('span'); kind.className = 'check-kind'; kind.textContent = finding.severity === 'problem' ? 'To fix' : 'Tip';
    const place = finding.slide ? `Slide ${finding.slide}: ${finding.title}` : finding.title ? `Section: ${finding.title}`
      : finding.code === 'renderer' ? 'Preview' : 'Top of the file';
    head.append(kind, document.createTextNode(place + (finding.line ? `, line ${finding.line}` : '')));
    body.className = 'check-message'; body.append(prose(finding.message));
    how.className = 'check-how'; how.append(prose(finding.how || ''));
    actions.className = 'check-actions';
    const button = (label, title, run) => {
      const control = document.createElement('button'); control.type = 'button'; control.textContent = label; control.title = title;
      control.onclick = run; actions.append(control); return control;
    };
    if (finding.from !== null) button('Show', 'Go to this line', () => show(finding.from));
    if (finding.fix) button(finding.fix.label, 'Change the draft. Undo restores it; nothing is saved.', () => {
      if (!enabled()) { feedback.textContent = 'Wait for the current operation, then try again.'; return; }
      // Findings carry offsets into the text they were computed from.
      if (revision !== text()) { refresh(); feedback.textContent = 'The text changed. The list is up to date now; try again.'; return; }
      editor.dispatch({changes: finding.fix.changes, userEvent: 'input', scrollIntoView: true,
        selection: {anchor: Math.min(...finding.fix.changes.map(change => change.from))}});
      refresh();
      feedback.textContent = 'Changed in your draft. Undo restores it. Nothing was saved.';
    }).className = 'check-fix';
    if (finding.from !== null && askAgent) {
      const slide = storyModel(text(), isOrg()).slides.findLast(node => node.from <= finding.from);
      if (slide) button('Ask AI', 'Send this problem and the slide to the current chat', () => askAgent(slide,
        `Fix this on the slide, keeping my content and meaning: ${finding.message} ${finding.how || ''}`.replaceAll('`', '')));
    }
    row.append(head, body, ...(finding.how ? [how] : []), actions);
    return row;
  }
  function refresh() {
    clearTimeout(timer);
    revision = text(); findings = compute();
    const summary = checkSummary(findings);
    chip.dataset.kind = summary.problems ? 'problem' : summary.tips ? 'tip' : 'ok';
    $('check-icon').replaceChildren(createElement(summary.problems ? TriangleAlert : summary.tips ? Lightbulb : CircleCheck));
    $('check-label').textContent = summary.label;
    chip.title = summary.problems ? 'Some slides need fixing. Open the list.' : summary.tips ? 'Slides work. Open suggestions.' : 'No problems found in the slide structure';
    $('check-summary').textContent = !findings.length ? 'No problems found. This checks structure; still look at the slides.'
      : [summary.problems && `${summary.problems} to fix`, summary.tips && `${summary.tips} ${summary.tips === 1 ? 'tip' : 'tips'}`].filter(Boolean).join(', ');
    if (!panel.hidden) list.replaceChildren(...findings.map(item));
    changed(findings);
    return findings;
  }
  function toggle(open = panel.hidden) {
    panel.hidden = !open; chip.setAttribute('aria-expanded', String(open)); feedback.textContent = '';
    if (open) refresh();
    editor.requestMeasure(); toggled();
  }
  chip.onclick = () => toggle();
  $('check-close').onclick = () => { toggle(false); chip.focus(); };
  refresh();
  return {
    // Typing must stay cheap: recompute after a pause, not on every key.
    schedule() { clearTimeout(timer); timer = setTimeout(refresh, 300); },
    refresh, open: () => toggle(true), findings: () => findings,
  };
}
