import {createElement, X, Upload, Plus} from 'lucide';

export function delivery({call, state, text, theme, notice, download, demo}) {
  const $ = id => document.getElementById(id);
  let busy = false, plan = null, options = {};
  for (const id of ['close-export', 'close-publish']) $(id).append(createElement(X));
  $('publish').append(createElement(Upload));
  $('repository-toggle').append(createElement(Plus));
  const scope = () => state.session ? {session:state.session} : {};
  const snapshot = () => ({...scope(), text:text(), name:state.name, theme:theme() || undefined});
  async function run(action, args, progress) {
    const owner = scope();
    let job = await call('matsugit_action', {...owner, action, ...args});
    while (job.state === 'running') {
      await new Promise(resolve => setTimeout(resolve, 500));
      job = await call('matsugit_action_status', {...owner, job:job.job});
      progress.textContent = job.log || 'Working...';
    }
    if (job.state !== 'ready') throw Error(job.error || 'Operation failed');
    return {...job, owner};
  }
  function lock(value) {
    busy = value;
    for (const id of ['export-run', 'publish-review', 'publish-confirm', 'export-format', 'export-destination', 'publish-target', 'publish-build', 'export-replace', 'repository-toggle', 'repository-provider', 'repository-host', 'repository-name', 'repository-list', 'repository-more', 'repository-connect']) $(id).disabled = value;
  }
  async function preferences(progress) {
    options = (await run('options', {}, progress)).result;
  }
  $('download').onclick = async () => {
    if (demo) { download(); return; }
    if (busy) return;
    $('export-dialog').showModal();
    $('export-progress').textContent = '';
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
  $('export-run').onclick = async () => {
    if (busy) return;
    const format = $('export-format').value;
    if (format === 'source') { download(); $('export-dialog').close(); return; }
    const args = snapshot(), sync = $('export-destination').value === 'sync';
    lock(true); $('export-progress').textContent = 'Preparing export...';
    try {
      const job = await run('export', {...args, format, sync_folder:sync, replace:$('export-replace').checked}, $('export-progress'));
      if (!sync) {
        const chunks = []; let offset = 0, done = false;
        while (!done) {
          const part = await call('matsugit_export_chunk', {...job.owner, job:job.job, offset});
          chunks.push(Uint8Array.from(atob(part.chunk), c => c.charCodeAt(0)));
          offset = part.next; done = part.done;
          $('export-progress').textContent = `Downloading ${Math.round(offset / 1024)} KiB`;
        }
        const url = URL.createObjectURL(new Blob(chunks));
        const link = document.createElement('a'); link.href = url;
        link.download = args.name.replace(/\.[^.]+$/, '') + '.' + format;
        link.click(); setTimeout(() => URL.revokeObjectURL(url), 10000);
      }
      $('export-progress').textContent = [sync ? job.result.path : 'Download ready.', job.result.sync, ...(job.result.warnings || [])].filter(Boolean).join('\n\n');
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
  $('publish-target').onchange = () => {
    invalidate();
    $('publish-build').value = $('publish-target').value ? options.targets[$('publish-target').value]?.build || 'local' : options.build || 'local';
  };
  $('publish').onclick = async () => {
    if (demo || busy) return;
    invalidate(); $('repository-picker').hidden = true; $('publish-dialog').showModal(); lock(true);
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
    const args = {...snapshot(), target:$('publish-target').value || undefined, build:$('publish-build').value};
    try {
      const job = await run('plan', args, $('publish-progress'));
      plan = {id:job.job, args};
      const data = job.result;
      $('publish-plan').textContent = [`Repository: ${data.project_url}`, `Checkout: ${data.repo}`, `Branch: ${data.branch}`,
        `Build: ${data.build === 'ci' ? 'Source to CI' : 'Local render'}`, `Output: ${data.directory}`, `Theme: ${data.theme}`, data.site_url ? `Site: ${data.site_url}` : '', data.warning].filter(Boolean).join('\n');
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
      $('publish-progress').textContent = `${job.result.status}\n${job.result.revision}`;
      notice(job.result.status);
    } catch (error) { $('publish-progress').textContent = error.message; }
    finally { invalidate(); lock(false); }
  };
  if (demo) $('publish').disabled = true;
}
