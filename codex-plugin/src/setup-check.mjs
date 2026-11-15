import {createElement, Wrench, X, RefreshCw, LoaderCircle} from 'lucide';

const statuses = {ready: 'Ready', missing: 'Missing', unsupported: 'Unsupported', error: 'Error'};

export function setupReport(value) {
  const invalid = () => { throw Error('The server returned an invalid setup report. Update the matsugit server, then retry.'); };
  if (value?.schema !== 1 || typeof value.ready !== 'boolean' || !Array.isArray(value.checks) || !value.checks.length) invalid();
  const ids = new Set();
  for (const check of value.checks) {
    if (!check || typeof check.id !== 'string' || !check.id.trim() || ids.has(check.id)
        || typeof check.label !== 'string' || !check.label.trim() || !Object.hasOwn(statuses, check.status)
        || typeof check.required !== 'boolean' || typeof check.detail !== 'string'
        || (check.remedy !== undefined && typeof check.remedy !== 'string')) invalid();
    ids.add(check.id);
  }
  if (value.ready !== value.checks.every(check => !check.required || check.status === 'ready')) invalid();
  return value;
}

export function setupVersions(report, workspaceVersion) {
  const parts = [`Matsugit workspace ${workspaceVersion}`,
    `Server ${report?.workspace_version || 'version not reported'}`,
    `Python renderer ${report?.version || 'version not reported'}`];
  if (report?.runtime_host) parts.push(`Running on ${report.runtime_host}${report.runtime_platform ? ' (' + report.runtime_platform + ')' : ''}`);
  if (report?.workspace_version && report.workspace_version !== workspaceVersion)
    parts.push('Workspace and server versions differ. Save your draft, reload the connection and reopen this document.');
  return parts.join(' | ');
}

export function setupCheck({call, workspaceVersion}) {
  const $ = id => document.getElementById(id);
  const dialog = $('setup-dialog'), results = $('setup-results'), status = $('setup-status');
  const retry = $('setup-retry'), closeButton = $('setup-close');
  let sequence = 0, returnFocus;
  const icon = glyph => createElement(glyph, {'aria-hidden': 'true'});
  for (const id of ['setup-check', 'notice-setup']) $(id).prepend(icon(Wrench));
  closeButton.append(icon(X));

  function busy(value) {
    results.setAttribute('aria-busy', String(value));
    retry.disabled = value;
    retry.setAttribute('aria-busy', String(value));
    retry.replaceChildren(icon(value ? LoaderCircle : RefreshCw), document.createTextNode(value ? 'Checking...' : 'Retry'));
  }
  function row(check) {
    const item = document.createElement('li');
    item.dataset.status = check.status;
    item.dataset.check = check.id;
    const heading = document.createElement('div');
    heading.className = 'setup-tool-heading';
    const label = document.createElement('strong'), verdict = document.createElement('span');
    label.textContent = check.label; verdict.textContent = statuses[check.status];
    verdict.className = 'setup-verdict';
    heading.append(label, verdict);
    const detail = document.createElement('p');
    detail.textContent = check.detail;
    item.append(heading, detail);
    if (check.status !== 'ready') {
      const remedy = document.createElement('p');
      remedy.className = 'setup-remedy';
      const prefix = document.createElement('strong');
      prefix.textContent = 'Next step: ';
      const fallback = check.status === 'missing' ? `Install ${check.label} on the machine running matsugit, then retry.`
        : check.status === 'unsupported' ? `Use a supported version of ${check.label}, then retry.`
          : `Check ${check.label} on the machine running matsugit, then retry.`;
      remedy.append(prefix, document.createTextNode(check.remedy?.trim() || fallback));
      item.append(remedy);
    }
    return item;
  }
  async function run() {
    if (!dialog.open) return;
    const request = ++sequence;
    const current = () => request === sequence && dialog.open;
    results.hidden = true;
    $('setup-required').replaceChildren(); $('setup-optional').replaceChildren();
    status.textContent = 'Checking tools...'; status.dataset.kind = 'busy'; busy(true);
    $('setup-versions').textContent = setupVersions(null,workspaceVersion);
    try {
      const response = await call('matsugit_doctor', {});
      if (!current()) return;
      const report = setupReport(response);
      $('setup-versions').textContent = setupVersions(report,workspaceVersion);
      for (const required of [true, false]) {
        const group = required ? 'required' : 'optional';
        const checks = report.checks.filter(check => check.required === required);
        $('setup-' + group + '-group').hidden = !checks.length;
        $('setup-' + group).replaceChildren(...checks.map(row));
      }
      status.textContent = report.ready
        ? 'Required tools are ready.' + (report.checks.some(check => !check.required && check.status !== 'ready') ? ' Some optional tools need attention.' : '')
        : 'Required tools need attention.';
      status.dataset.kind = report.ready ? 'ready' : 'attention';
      results.hidden = false;
    } catch (error) {
      if (!current()) return;
      status.textContent = `Could not check setup. ${error?.message || String(error)} Ensure the matsugit server is connected and up to date, then retry.`;
      status.dataset.kind = 'error';
    } finally {
      if (current()) busy(false);
    }
  }
  function close() {
    sequence++; busy(false); dialog.close();
    if (returnFocus?.isConnected && !returnFocus.disabled) returnFocus.focus();
  }
  closeButton.onclick = close;
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  // Native close events are queued; an old close must not invalidate a reopening.
  dialog.addEventListener('close', () => { if (!dialog.open) { sequence++; busy(false); } });
  retry.onclick = () => { if (!retry.disabled) void run(); };
  busy(false);
  return {open(trigger = document.activeElement) {
    if (dialog.open) return;
    returnFocus = trigger;
    dialog.showModal(); closeButton.focus();
    void run();
  }};
}
