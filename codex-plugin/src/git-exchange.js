// Git review is separate from file Save and from publishing to another target.
export function gitExchange({call, state, text, hasUnsaved, run, lock, isBusy, reload, mergeReview, publication}) {
  const $ = id => document.getElementById(id);
  let reviewed = null, selected = [], candidate = null;
  const view = () => state.session || state.uri;
  const clean = () => !state.conflict && !hasUnsaved() && text() === state.base;
  function reset() {
    reviewed = null; candidate = null; selected = [];
    $('git-exchange-review').hidden = true; $('git-exchange-confirmation').hidden = true;
    $('git-exchange-start').textContent = 'Review and push...';
  }
  function current() {
    if (!reviewed || reviewed.view !== view() || text() !== reviewed.source || !clean())
      throw Error('The draft changed. Save/review it first, then check Git again. Nothing was pushed.');
  }
  function files(data) {
    $('git-exchange-source').textContent = data.relative + ' (document)';
    $('git-exchange-assets').replaceChildren();
    for (const name of data.assets) {
      const label = document.createElement('label'), input = document.createElement('input');
      input.type = 'checkbox'; input.checked = selected.includes(name);
      input.onchange = () => {
        selected = [...$('git-exchange-assets').querySelectorAll('input:checked')].map(item => item.value).sort();
        reviewed = null; candidate = null; $('git-exchange-confirmation').hidden = true;
        $('git-exchange-start').textContent = 'Review selected files...';
      };
      input.value = name; label.append(input, document.createTextNode(name)); $('git-exchange-assets').append(label);
    }
    $('git-exchange-warning').textContent = [...data.blocked, data.asset_warning,
      data.local_changes.some(name => !data.paths.includes(name)) ? 'Unselected local files are not committed.' : '',
      data.ahead ? `${data.ahead} existing local commit(s) will also be pushed.` : '',
      data.behind ? `${data.behind} incoming commit(s) will update this checkout, including their other files.` : '',
    ].filter(Boolean).join('\n\n');
    $('git-exchange-review').hidden = false;
  }
  $('git-exchange-start').onclick = async () => {
    if (isBusy()) return;
    if (!clean()) {
      $('git-sync-progress').textContent = 'Save/review your draft first, then return to Git sync. Your edits are retained; nothing was committed or pushed.';
      return;
    }
    const source = text(), owner = view();
    reviewed = null; candidate = null; $('git-exchange-confirmation').hidden = true;
    lock(true); $('git-sync-progress').textContent = 'Fetching versions for review...';
    try {
      const job = await run('exchange-plan', {assets:selected}, $('git-sync-progress'));
      if (owner !== view() || !clean() || text() !== source || source !== job.result.local)
        throw Error('The file or draft changed while checking Git. Save/review it, then check again.');
      const data = job.result;
      reviewed = {id:job.job, source, view:owner, data};
      $('git-sync-progress').textContent = `${data.repo}\nPush to: ${data.destination}\nBranch: ${data.merge.replace(/^refs\/heads\//, '')}`;
      files(data);
      if (data.blocked.length) return;
      const {merge} = await call('matsugit_merge', {base:data.base, local:source, incoming:data.incoming});
      current();
      mergeReview.open(merge, async result => {
        current(); candidate = result;
        $('git-exchange-confirmation').hidden = false;
        $('git-exchange-message').value = `Update ${data.relative}`;
        $('git-exchange-summary').textContent = `${data.paths.length} reviewed file(s). The reviewed document will be saved, committed and pushed. Existing CI may run; this is not deployment confirmation.`;
        $('git-exchange-preview').value = result;
        $('git-exchange-start').textContent = 'Review again...';
      }, () => { candidate = null; $('git-exchange-confirmation').hidden = true; }, {
        title:'Review Git changes', applyLabel:'Continue to commit review',
        localLabel:'Your saved file', incomingLabel:'Incoming Git version', incomingChoice:'Keep Git edit',
        context:`${data.relative} · ${data.destination}`, status:'Nothing has been saved, committed or pushed. Cancel keeps your current file.',
        progress:'Preparing the commit review...',
      });
    } catch (error) { reviewed = null; $('git-sync-progress').textContent = error.message; }
    finally { lock(false); }
  };
  $('git-exchange-confirm').onclick = async () => {
    if (isBusy() || candidate === null) return;
    const message = $('git-exchange-message').value.trim();
    if (!message) { $('git-sync-progress').textContent = 'Enter a commit message.'; return; }
    try { current(); }
    catch (error) { $('git-sync-progress').textContent = error.message; return; }
    const checked = reviewed, result = candidate;
    lock(true); $('git-sync-progress').textContent = 'Checking versions, committing and pushing...';
    try {
      const job = await run('exchange', {plan:checked.id, text:result, assets:selected, message}, $('git-sync-progress'));
      $('git-sync-progress').textContent = `Pushed ${job.result.revision.slice(0, 10)}\n${job.result.message}`;
      if (checked.view === view() && text() === checked.source && clean()) await reload(true, true, job.result.etag);
      else if (checked.view === view()) await reload();
      if (checked.view === view() && job.result.publication) publication?.pushed(job.result.publication);
    } catch (error) { $('git-sync-progress').textContent = error.message; }
    finally { reset(); lock(false); }
  };
  return {reset};
}
