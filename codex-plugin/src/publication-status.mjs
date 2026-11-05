import {createElement, CloudUpload, Check, RefreshCw, X, LoaderCircle} from 'lucide';

export function publicationLabel(receipt, dirty, matches) {
  if (!receipt || receipt.stage === 'local') return 'Not pushed';
  if (dirty || !matches) return 'Changes not pushed';
  return ({published:'Published', building:'Building', failed:'CI failed'})[receipt.stage] || 'Pushed';
}

export function publicationStatus({call, state, hasUnsaved, demo}) {
  const $ = id => document.getElementById(id);
  let owner, receipt, loaded = false, busy = false, base, digest, sequence = 0;
  $('publication-check').replaceChildren(createElement(RefreshCw));
  $('publication-close').replaceChildren(createElement(X));
  $('publication-close').onclick = () => $('publication-dialog').close();
  function paint() {
    const label = publicationLabel(receipt, hasUnsaved(), digest === receipt?.source_sha256);
    const button = $('publication-state');
    button.disabled = demo || state.loading || state.delivering || busy || !(state.session || state.uri);
    button.title = receipt?.detail || 'Publication status';
    if (button.dataset.label !== label || button.dataset.busy !== String(busy)) {
      button.replaceChildren(createElement(busy ? LoaderCircle : label === 'Published' ? Check : CloudUpload), document.createTextNode(label));
      button.dataset.label = label; button.dataset.busy = String(busy);
    }
    $('publication-check').disabled = busy || !receipt?.revision;
    $('publication-details').textContent = receipt ? [
      receipt.detail, receipt.target && `Target: ${receipt.target}`, receipt.project_url,
      receipt.revision && `Pushed revision: ${receipt.revision}`,
      receipt.deployed_revision && `Deployed revision: ${receipt.deployed_revision}`,
      receipt.pushed_at && `Pushed: ${receipt.pushed_at}`, receipt.checked_at && `Checked: ${receipt.checked_at}`,
      receipt.pipeline_status && `Pipeline: ${receipt.pipeline_status}`, receipt.check_error,
    ].filter(Boolean).join('\n') : 'Reading local publication history...';
    for (const [id, url] of [['publication-pipeline',receipt?.pipeline_url], ['publication-site',receipt?.site_url]]) {
      let valid = false;
      try { const parsed = new URL(url); valid = parsed.protocol === 'https:' && !parsed.username && !parsed.password; } catch {}
      $(id).hidden = !valid; if (valid) $(id).href = url;
    }
  }
  async function read(check = false) {
    if (busy || demo || !(state.session || state.uri)) return;
    const current = owner, generation = sequence, session = state.session;
    busy = true; paint(); $('publication-progress').textContent = check ? 'Checking provider...' : 'Reading local history...';
    try {
      let job = await call('matsugit_action', {action:'publication-status', session:session || undefined, check});
      while (job.state === 'running') {
        await new Promise(resolve => setTimeout(resolve, 300));
        job = await call('matsugit_action_status', {job:job.job, session:session || undefined});
      }
      if (current !== owner || generation !== sequence) return;
      if (job.state !== 'ready') throw Error(job.error || 'Could not read publication status');
      receipt = job.result; loaded = true; $('publication-progress').textContent = '';
    } catch (error) {
      if (current === owner && generation === sequence) $('publication-progress').textContent = error.message;
    } finally { busy = false; paint(); }
  }
  $('publication-state').onclick = () => {
    $('publication-dialog').showModal(); if (!loaded) void read();
  };
  $('publication-check').onclick = () => read(true);
  return {
    update() {
      const next = state.session || state.uri;
      if (owner !== next) { owner = next; receipt = null; loaded = false; sequence++; base = undefined; }
      if (base !== state.base) {
        base = state.base; const expected = base, current = owner;
        digest = null;
        crypto.subtle.digest('SHA-256', new TextEncoder().encode(base)).then(hash => {
          if (current !== owner || expected !== base) return;
          digest = Array.from(new Uint8Array(hash), x => x.toString(16).padStart(2,'0')).join(''); paint();
        }).catch(() => {});
      }
      paint();
      if (owner && !loaded && !busy && !state.loading && !state.delivering) { loaded = true; void read(); }
    },
    pushed(value) { sequence++; receipt = value; loaded = true; paint(); },
  };
}
