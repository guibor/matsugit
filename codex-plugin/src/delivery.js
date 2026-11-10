import {createElement, X, Upload, Plus, GitPullRequestArrow, Download} from 'lucide';
import {exportMime} from './download.mjs';
import {gitExchange} from './git-exchange.js';

export function delivery({call, state, text, theme, notice, download, downloadFile, demo, reload, load, follow, hasUnsaved, refreshControls, publication, mergeReview}) {
  const $ = id => document.getElementById(id);
  let busy = false, plan = null, options = {}, syncPlan = null;
  let prepared = null;
  $('export-download-retry').append(createElement(Download), 'Download again');
  for (const id of ['close-export', 'close-publish']) $(id).append(createElement(X));
  $('publish').append(createElement(Upload));
  $('repository-toggle').append(createElement(Plus));
  $('git-sync').append(createElement(GitPullRequestArrow));
  $('close-git-sync').append(createElement(X));
  const scope = () => state.session ? {session:state.session} : {};
  const snapshot = () => ({...scope(), text:text(), name:state.name, theme:theme() || undefined});
  async function run(action, args, progress) {
    const owner = scope();
    const view = state.session || state.uri;
    let job = await call('matsugit_action', {...owner, action, ...args});
    while (job.state === 'running') {
      await new Promise(resolve => setTimeout(resolve, 500));
      job = await call('matsugit_action_status', {...owner, job:job.job});
      progress.textContent = job.log || 'Working...';
    }
    if (job.workspace && view === (state.session || state.uri)) {
      // Publishing moved the document. Follow it; typing done meanwhile stays
      // an ordinary unsaved draft of the file at its new path.
      await follow(job.workspace);
      job.moved = job.workspace.path;
    }
    if (job.state !== 'ready') throw Error(job.error || 'Operation failed');
    return {...job, owner, view};
  }
  function lock(value) {
    busy = value;
    state.delivering = value;
    refreshControls();
    for (const id of ['export-run', 'export-download-retry', 'publish-review', 'publish-confirm', 'publish-move', 'export-format', 'export-destination', 'publish-target', 'publish-build', 'export-replace', 'repository-toggle', 'repository-provider', 'repository-host', 'repository-name', 'repository-list', 'repository-more', 'repository-connect']) $(id).disabled = value;
    $('git-sync').disabled = demo || value;
    $('git-sync-check').disabled = value;
    $('git-sync-publish').disabled = value;
    $('git-sync-apply').disabled = value || !syncPlan?.canApply;
    for (const id of ['git-exchange-start','git-exchange-confirm','git-exchange-message','close-git-sync','share-go','share-destination','share-close']) $(id).disabled = value;
    for (const input of $('git-exchange-assets').querySelectorAll('input')) input.disabled = value;
    $('git-sync-progress').setAttribute('aria-busy', String(value));
  }
  async function preferences(progress) {
    options = (await run('options', {}, progress)).result;
  }
  const syncStatus = {
    'local-changes':'Local and incoming edits overlap. Review and push compares the document versions here. Nothing was changed.',
    'staged-changes':'A staged commit is in progress. Finish it in Git, then check again. Nothing was changed.',
    diverged:'Both histories changed. Compare and merge in Git, then check again. Nothing was changed.',
    ahead:'Local commits have not been pushed. No incoming updates.',
    'up-to-date':'No incoming updates.', 'updates-available':'Updates available.', updated:'Updated from Git.',
    'source-removed':'Checkout updated; the source was removed or renamed upstream. Draft retained; reopen the correct file.'
  };
  const exchange = gitExchange({call, state, text, hasUnsaved, run, lock, isBusy:()=>busy, reload, mergeReview, publication});
  $('git-sync-dialog').addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  const fileList = (label, paths) => paths?.length
    ? `\n\n${label} (${paths.length}):\n` + paths.slice(0, 12).map(name => `  ${JSON.stringify(name)}`).join('\n') + (paths.length > 12 ? '\n  ...' : '') : '';
  $('close-git-sync').onclick = () => $('git-sync-dialog').close();
  $('git-sync-publish').onclick = () => {
    if (busy) return;
    $('git-sync-dialog').close();
    $('publish').onclick();
  };
  $('git-sync-check').onclick = async () => {
    if (busy) return;
    exchange.reset();
    syncPlan = null;
    const source = text();
    $('git-sync-check').textContent = 'Checking...';
    lock(true); $('git-sync-progress').textContent = 'Checking upstream...';
    try {
      const job = await run('sync-plan', {}, $('git-sync-progress'));
      if (job.view !== (state.session || state.uri)) throw Error('The open document changed. Check again for this document.');
      const data = job.result;
      syncPlan = {id:job.job, view:job.view, source, canApply:data.status === 'updates-available'};
      const local = data.dirty ? (syncPlan.canApply ? '\nLocal edits do not overlap these updates and will be retained.' : '\nYour local edits are retained, not published.') : '';
      $('git-sync-progress').textContent = `${data.repo}\n${data.branch}\n\n${syncStatus[data.status]}${local}\n${data.ahead} ahead, ${data.behind} behind` +
        fileList('Overlapping files', data.overlapping_changes) + fileList('Staged files', data.staged_changes) +
        fileList('Local changes', data.local_changes) + (data.changes ? `\n\nIncoming changes:\n${data.changes}` : '');
      $('git-sync-apply').title = syncPlan.canApply ? 'Pull reviewed updates; retain unrelated local edits' : syncStatus[data.status];
    } catch (error) { $('git-sync-progress').textContent = error.message; }
    finally { $('git-sync-check').textContent = 'Check again'; lock(false); }
  };
  $('git-sync').onclick = () => {
    if (demo || busy) return;
    $('git-sync-dialog').showModal(); $('git-sync-check').onclick();
  };
  $('git-sync-apply').onclick = async () => {
    if (busy || !syncPlan) return;
    if (state.conflict || hasUnsaved() || text() !== state.base || text() !== syncPlan.source || (state.session || state.uri) !== syncPlan.view) {
      $('git-sync-progress').textContent = 'Unsaved or external edits exist. Close this dialog, save/review the draft, then check again. Your draft is retained.';
      syncPlan = null; lock(false); return;
    }
    lock(true); $('git-sync-progress').textContent = 'Pulling reviewed updates...';
    try {
      const job = await run('sync', {text:text(), plan:syncPlan.id}, $('git-sync-progress'));
      $('git-sync-progress').textContent = syncStatus[job.result.status];
      if (job.view === (state.session || state.uri)) await reload();
    } catch (error) { $('git-sync-progress').textContent = error.message; }
    finally { syncPlan = null; lock(false); }
  };
  $('download').onclick = async () => {
    if (demo) { download(); return; }
    if (busy) return;
    $('export-dialog').showModal();
    $('export-progress').textContent = '';
    prepared = null; $('export-ready').hidden = true;
    $('export-destination').value = 'download';
    $('export-replace').checked = false; $('export-replace-row').hidden = true;
    lock(true);
    try {
      await preferences($('export-progress'));
      $('sync-destination').disabled = !options.export_directory;
      $('sync-destination').textContent = options.export_directory ? 'Synced folder' : 'Synced folder (not configured)';
      $('export-folder').textContent = options.export_directory || '';
      $('export-progress').textContent = '';
    } catch (error) { $('export-progress').textContent = error.message; }
    finally { lock(false); $('export-format').onchange(); }
  };
  $('close-export').onclick = () => $('export-dialog').close();
  $('export-destination').onchange = () => {
    $('export-replace-row').hidden = $('export-destination').value !== 'sync';
    $('export-replace').checked = false;
  };
  $('export-format').onchange = () => {
    const source = $('export-format').value === 'source';
    if (source) $('export-destination').value = 'download';
    $('export-destination').disabled = source;
    $('export-replace-row').hidden = source || $('export-destination').value !== 'sync';
    $('pptx-warning').hidden = $('export-format').value !== 'pptx';
  };
  async function sendPrepared() {
    $('export-ready').hidden = false;
    $('export-filename').textContent = `${prepared.name} (${Math.ceil(prepared.blob.size / 1024)} KiB)`;
    $('export-progress').textContent = 'Sending to host downloads...';
    try {
      const message = await downloadFile(prepared);
      $('export-progress').textContent = [message, ...(prepared.warnings || [])].join('\n\n');
    } catch (error) {
      $('export-progress').textContent = `Download not completed: ${error.message}\n\nThe prepared file is retained. Download again does not rebuild the export.`;
    }
  }
  $('export-download-retry').onclick = async () => {
    if (busy || !prepared) return;
    lock(true);
    try { await sendPrepared(); }
    finally { lock(false); $('export-format').onchange(); }
  };
  $('export-run').onclick = async () => {
    if (busy) return;
    const format = $('export-format').value;
    const args = snapshot(), sync = $('export-destination').value === 'sync';
    prepared = null; $('export-ready').hidden = true;
    lock(true); $('export-progress').textContent = 'Preparing export...';
    try {
      if (format === 'source') {
        prepared = {name:args.name,blob:new Blob([args.text],{type:'text/plain;charset=utf-8'})};
        await sendPrepared(); return;
      }
      const job = await run('export', {...args, format, sync_folder:sync, replace:$('export-replace').checked}, $('export-progress'));
      if (!sync) {
        const chunks = []; let offset = 0, done = false;
        while (!done) {
          const part = await call('matsugit_export_chunk', {...job.owner, job:job.job, offset});
          chunks.push(Uint8Array.from(atob(part.chunk), c => c.charCodeAt(0)));
          offset = part.next; done = part.done;
          $('export-progress').textContent = `Receiving export: ${Math.round(offset / 1024)} KiB`;
        }
        prepared = {name:args.name.replace(/\.[^.]+$/, '') + '.' + format,
          blob:new Blob(chunks,{type:exportMime[format]}),warnings:job.result.warnings};
        await sendPrepared();
      } else {
        $('export-progress').textContent = [job.result.path, job.result.sync, ...(job.result.warnings || [])].filter(Boolean).join('\n\n');
      }
    } catch (error) { $('export-progress').textContent = error.message; }
    finally { lock(false); $('export-format').onchange(); }
  };
  function invalidate() { plan = null; $('publish-confirmation').hidden = true; }
  let repositoryPage = 0;
  $('repository-toggle').onclick = () => { invalidate(); $('repository-picker').hidden = !$('repository-picker').hidden; };
  const clearRepositories = () => { repositoryPage = 0; $('repository-options').replaceChildren(); $('repository-more').hidden = true; $('repository-name').value = ''; };
  $('repository-provider').onchange = () => {
    $('repository-host').value = $('repository-provider').value === 'github' ? 'github.com' : 'gitlab.com';
    clearRepositories();
  };
  $('repository-host').oninput = clearRepositories;
  async function repositories(more = false) {
    if (busy) return;
    lock(true); invalidate();
    try {
      const job = await run('repositories', {provider:$('repository-provider').value, host:$('repository-host').value.trim(), page:more ? repositoryPage + 1 : 1}, $('publish-progress'));
      if (!more) $('repository-options').replaceChildren();
      for (const repository of job.result.repositories) $('repository-options').append(new Option(repository.name, repository.name));
      repositoryPage = job.result.page; $('repository-more').hidden = !job.result.more;
      $('publish-progress').textContent = `${$('repository-options').children.length} repositories available. Select or enter owner/repository.`;
    } catch (error) { $('publish-progress').textContent = error.message; }
    finally { lock(false); }
  }
  $('repository-list').onclick = () => repositories();
  $('repository-more').onclick = () => repositories(true);
  $('repository-connect').onclick = async () => {
    if (busy) return;
    lock(true); invalidate(); $('publish-progress').textContent = 'Preparing local checkout...';
    try {
      const job = await run('connect-repository', {provider:$('repository-provider').value, host:$('repository-host').value.trim(), repository:$('repository-name').value.trim()}, $('publish-progress'));
      await preferences($('publish-progress'));
      const select = $('publish-target');
      if (![...select.options].some(item => item.value === job.result.target)) select.add(new Option(job.result.target, job.result.target));
      select.value = job.result.target; select.onchange();
      $('repository-picker').hidden = true;
      $('publish-progress').textContent = job.result.status;
    } catch (error) { $('publish-progress').textContent = error.message; }
    finally { lock(false); }
  };
  $('publish-build').onchange = invalidate;
  $('publish-move').onchange = invalidate;
  $('publish-target').onchange = () => {
    invalidate();
    $('publish-build').value = $('publish-target').value ? options.targets[$('publish-target').value]?.build || 'local' : options.build || 'local';
  };
  $('publish').onclick = async () => {
    if (demo || busy) return;
    invalidate(); $('publish-move').checked = false; $('repository-picker').hidden = true; $('publish-dialog').showModal(); lock(true);
    $('publish-progress').textContent = 'Reading targets...';
    try {
      await preferences($('publish-progress'));
      const select = $('publish-target'); select.replaceChildren(new Option('Project default', ''));
      for (const name of Object.keys(options.targets || {}).sort()) select.add(new Option(name, name));
      select.value = options.default || '';
      $('publish-target').onchange();
      $('publish-progress').textContent = '';
    } catch (error) { $('publish-progress').textContent = error.message; }
    finally { lock(false); }
  };
  $('close-publish').onclick = () => $('publish-dialog').close();
  $('publish-review').onclick = async () => {
    if (busy) return;
    invalidate(); lock(true);
    const args = {...snapshot(), target:$('publish-target').value || undefined, build:$('publish-build').value, move_source:$('publish-move').checked};
    try {
      const job = await run('plan', args, $('publish-progress'));
      plan = {id:job.job, args};
      const data = job.result;
      $('publish-plan').textContent = [`Repository: ${data.project_url}`, `Checkout: ${data.repo}`, `Branch: ${data.branch}`,
        `Build: ${data.build === 'ci' ? 'Source to CI' : 'Local render'}`, `Output: ${data.directory}`, `Theme: ${data.theme}`, data.site_url ? `Site: ${data.site_url}` : '', data.warning].filter(Boolean).join('\n');
      if (data.relocation) $('publish-plan').textContent += '\n\nMove and leave symlinks:\n' + data.relocation.moves.map(m => `${m.source}\n  -> ${m.destination}`).join('\n');
      $('publish-confirmation').hidden = false;
      $('publish-progress').textContent = '';
    } catch (error) { $('publish-progress').textContent = error.message; }
    finally { lock(false); }
  };
  $('publish-confirm').onclick = async () => {
    if (busy || !plan) return;
    const checked = plan;
    if (checked.args.text !== text() || checked.args.theme !== (theme() || undefined) || checked.args.session !== state.session && (checked.args.session || state.session)) {
      invalidate(); $('publish-progress').textContent = 'The draft changed. Save it and review the target again.'; return;
    }
    lock(true);
    try {
      const job = await run('publish', {...checked.args, plan:checked.id, deploy:$('publish-deploy').checked}, $('publish-progress'));
      if (job.result.publication && job.view === (state.session || state.uri)) publication?.pushed(job.result.publication);
      const moved = job.moved ? `\nThis document now lives at ${job.moved}. The workspace follows it; the old location is a link to it.` : '';
      $('publish-progress').textContent = `${job.result.status}\n${job.result.revision}${moved}`;
      notice(job.result.status + moved);
    } catch (error) { $('publish-progress').textContent = error.message; }
    finally { invalidate(); lock(false); }
  };
  if (demo) { $('publish').disabled = true; $('git-sync').disabled = true; }
  return {run, lock, isBusy: () => busy, snapshot};
}
