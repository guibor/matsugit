// One Share button for people who do not use Git. It always shows one state
// and one next step, and drives the existing reviewed operations underneath:
// move-and-publish the first time, two-way exchange afterwards, pull when only
// someone else changed the deck. Nothing is sent without the final click.
import {createElement, Share2, X, Copy} from 'lucide';
import {mergeResult} from './merge-result.mjs';

const $ = id => document.getElementById(id);
const BUTTON = {'Not pushed': 'Share', 'Changes not pushed': 'Share changes', Pushed: 'Sent',
  Building: 'Building site', Published: 'Shared', 'CI failed': 'Site failed'};
// Git's reasons for refusing, said for someone who has never opened a terminal.
const BLOCKED = [
  [/hooks|gpgsign|sparseCheckout|line-ending|file conversion/, 'This project has special rules for saving changes that matsugit will not bypass.'],
  [/diverged|Unpublished commits include other files|More than 100/, 'This copy of the project and the shared one have both moved on in ways that need someone who knows Git.'],
  [/Staged work/, 'Another change is half-finished in this project folder.'],
  [/deleted or renamed upstream/, 'Someone moved or deleted this deck in the shared project.'],
  [/user\.(name|email)/, 'This computer has not been told your name and email for sharing yet.'],
];
export const shareLabel = label => BUTTON[label] || 'Share';
// The places a shared deck can be opened, most useful first.
export function publishedLinks(receipt) {
  const links = receipt?.links || {}, host = receipt?.provider === 'github' ? 'GitHub' : 'GitLab';
  const siteDetail = receipt?.stage === 'published' ? 'last verified version'
    : receipt?.stage === 'failed' || receipt?.deployment_error ? 'previous version, if available'
    : 'build not verified; may show an older version';
  return [
    links.slides && {key: 'slides', label: 'Slides', detail: siteDetail, url: links.slides},
    links.document && {key: 'document', label: 'Document', detail: siteDetail, url: links.document},
    !links.slides && !links.document && links.site && {key: 'site', label: 'Site', detail: 'the project\'s website', url: links.site},
    links.source && {key: 'source', label: 'Source', detail: `on ${host}`, url: links.source},
    !links.source && links.project && {key: 'project', label: 'Project', detail: `on ${host}`, url: links.project},
  ].filter(item => item && safe(item.url));
}
const STEP_LABEL = {waiting: 'Waiting for the build to start...', starting: 'The build is starting...',
  document: 'Building the document...', slides: 'Building the slides...', publishing: 'Publishing the site...'};
export function plainBlocked(reasons) {
  return [...new Set(reasons.map(reason => BLOCKED.find(([pattern]) => pattern.test(reason))?.[1] || reason))];
}
const safe = url => { try { const parsed = new URL(url); return typeof url === 'string' && !/[\s\x00-\x1f]/.test(url) && ['https:', 'http:'].includes(parsed.protocol) && parsed.hostname && !parsed.username && !parsed.password ? url : null; } catch { return null; } };

export function share({call, state, text, dirty, save, run, lock, isBusy, snapshot, mergeReview, publication, reload, notice, demo, openLink = url => window.open(url, '_blank', 'noopener')}) {
  const dialog = $('share-dialog'), go = $('share-go'), progress = $('share-progress');
  let step = null, context = null, contextOwner = null, visit = 0, showingOutcome = false, monitoring = false, linkSignature;
  $('share').append(createElement(Share2), document.createElement('span'));
  $('share-close').append(createElement(X)); $('share-copy').append(createElement(Copy), 'Copy link');
  $('share-close').onclick = () => dialog.close();
  $('share-later').onclick = () => dialog.close();
  dialog.addEventListener('cancel', event => { if (isBusy()) event.preventDefault(); });
  dialog.addEventListener('close', () => { visit++; step = null; });
  for (const [id, target] of [['share-advanced-sync', 'git-sync'], ['share-advanced-publish', 'publish'], ['share-advanced-status', 'publication-state']])
    $(id).onclick = () => { if (isBusy()) return; dialog.close(); $(target).click(); };
  $('share-copy').onclick = async () => {
    try { await navigator.clipboard.writeText($('share-link').href); progress.textContent = 'Link copied.'; }
    catch { progress.textContent = 'Could not copy. Select the link above instead.'; }
  };
  const view = () => state.session || state.uri;
  const knownLinks = () => {
    const receipt = publication.receipt(), local = contextOwner === view() ? context : null;
    return publishedLinks({...local, ...receipt, links: {...local?.links, ...receipt?.links}});
  };
  // The three things sharing does, always in the same order, so the reader can
  // see what has happened and what the button will do next.
  const STEP = {save: ['Saved on this computer', 'Save your changes'], send: ['Sent to the project', 'Send to the project'],
    site: ['The site shows it', 'The site updates']};
  function paintSteps(steps) {
    const list = $('share-steps');
    list.hidden = !steps;
    if (!steps) return;
    list.replaceChildren(...Object.entries(STEP).map(([name, [done, todo]]) => {
      const value = steps[name] || 'todo', item = document.createElement('li'), mark = document.createElement('span');
      item.dataset.state = value; mark.className = 'share-mark'; mark.setAttribute('aria-hidden', 'true');
      mark.textContent = {done: '\u2713', failed: '!', unknown: '?'}[value] || '';
      const label = {done, busy: name === 'site' ? STEP_LABEL[steps.build] || 'The site is rebuilding...' : name === 'send' ? 'Sending...' : 'Saving...',
        failed: 'The site did not rebuild', unknown: 'Cannot see the site from here', next: todo, todo}[value];
      item.append(mark, label + (name === 'send' && steps.project ? ` (${steps.project})` : ''));
      item.setAttribute('aria-current', String(value === 'next' || value === 'busy'));
      return item;
    }));
  }
  // Each link opens in the browser through the host, with its own copy button.
  function paintLinks(list) {
    const signature = JSON.stringify(list);
    if (signature === linkSignature) return;
    linkSignature = signature;
    const root = $('share-links');
    root.hidden = !list.length;
    root.replaceChildren(...list.map(item => {
      const row = document.createElement('li'), open = document.createElement('button'), copy = document.createElement('button');
      open.type = 'button'; open.className = 'share-open'; open.dataset.link = item.key;
      const label = document.createElement('strong'); label.textContent = item.label;
      const detail = document.createElement('span'); detail.textContent = item.detail;
      open.append(label, detail); open.title = item.url; open.onclick = () => openLink(item.url);
      copy.type = 'button'; copy.className = 'share-copy-link'; copy.textContent = 'Copy link'; copy.title = 'Copy ' + item.url;
      copy.onclick = async () => {
        try { await navigator.clipboard.writeText(item.url); progress.textContent = `${item.label} link copied.`; }
        catch { progress.textContent = `Could not copy. The link is ${item.url}`; }
      };
      row.append(open, copy); return row;
    }));
  }
  function paint({title, detail = '', action = '', next = null, link = null, linkLabel = 'Open the shared deck', pick = false, steps = null, outcome = false, links = knownLinks()}) {
    paintLinks(links);
    $('share-title').textContent = title; $('share-detail').textContent = detail;
    go.hidden = !action; go.textContent = action; step = next;
    $('share-later').hidden = !action; showingOutcome = outcome;
    paintSteps(steps);
    $('share-destination-row').hidden = !pick;
    const url = safe(link);
    $('share-link-row').hidden = !url;
    if (url) { $('share-link').href = url; $('share-link').textContent = linkLabel; }
  }
  const fail = error => paint({title: 'That did not work', detail: error.message + '\n\nNothing was lost. Your deck is still on this computer.'});
  async function saved() {
    if (!dirty()) return true;
    progress.textContent = 'Saving your deck...';
    await save();
    if (dirty() || state.conflict) throw Error('The deck could not be saved, so nothing was shared. Close this and check the message at the top.');
    return true;
  }
  const destination = info => info.label || info.target || 'your project';

  const project = () => context?.label || (publication.receipt()?.project_url || '').split('/').slice(-2).join('/') || '';
  const pending = receipt => !!receipt?.provider && ['pushed', 'building'].includes(receipt.stage) && !receipt.check_error && !receipt.gaveUp;
  // What the last share led to, from the stored receipt. Honest about unknowns.
  function outcome() {
    const receipt = publication.receipt() || {};
    const link = receipt.site_url || receipt.project_url || context?.site_url || context?.project_url;
    const label = receipt.site_url || context?.site_url ? 'Open the shared deck' : 'Open the project';
    const steps = {save: 'done', send: 'done', project: project(), build: receipt.build_step}, links = knownLinks();
    // The push worked but the build that updates the site could not be started.
    const deployError = receipt.deployment_error || context?.deployError;
    if (deployError && receipt.stage === 'pushed' && !receipt.pipeline_status) {
      paint({title: 'Sent, but the site was not asked to update', outcome: true, links,
        steps: {...steps, site: 'failed'}, detail: deployError + '\n\nYour changes are safe in the project.'});
      return;
    }
    if (!receipt.provider) paint({title: 'Sent', outcome: true, links, link: links.length ? null : link, linkLabel: label, steps: {...steps, site: 'unknown'},
      detail: 'Your changes are in the shared project. matsugit does not know whether this project has a website.'});
    else if (receipt.stage === 'published') paint({title: 'Live', outcome: true, links, link: links.length ? null : link, linkLabel: 'Open the shared deck', steps: {...steps, site: 'done'},
      detail: 'The site shows this version. You can pass the link on.'});
    else if (receipt.stage === 'failed') paint({title: 'Sent, but the site did not rebuild', outcome: true, links, steps: {...steps, site: 'failed'},
      link: receipt.pipeline_url || link, linkLabel: receipt.pipeline_url ? 'Open the failed build' : label,
      detail: 'Your changes are safe in the project. Its site build reported a failure; whoever looks after the project can see why.'});
    else if (receipt.check_error) paint({title: 'Sent', outcome: true, links, link: links.length ? null : link, linkLabel: label, steps: {...steps, site: 'unknown'},
      detail: 'Your changes are in the shared project. matsugit cannot see the site build from this computer, so check the site yourself before passing the link on.'});
    else if (receipt.gaveUp) paint({title: 'Sent', outcome: true, links, link: links.length ? null : link, linkLabel: label, steps: {...steps, site: 'unknown'},
      detail: receipt.gaveUp});
    else paint({title: 'Sent. The site is rebuilding...', outcome: true, links, link: links.length ? null : link, linkLabel: label, steps: {...steps, site: 'busy'},
      detail: 'The source link already shows your new version. The project\'s CI controls when the document and slides are published. You can close this and keep working: the Share button changes to "Shared" when this version is verified live, and a message tells you.'});
  }
  // Keep asking the project until the site is live or failed, whether or not
  // the dialog is open. Read-only; never holds the Save or Share lock.
  async function monitor() {
    if (monitoring || demo) return;
    monitoring = true;
    const owner = view(), started = publication.receipt()?.revision;
    try {
      for (let attempt = 0; attempt < 150; attempt++) {
        const receipt = await publication.check();
        if (owner !== view() || receipt?.revision !== started) return;
        if (attempt >= 8 && receipt?.stage === 'pushed' && !receipt.check_error)
          receipt.gaveUp = 'Your changes are in the shared project. No site build was found for them, so the site may not update by itself.';
        if (attempt === 149 && pending(receipt)) receipt.gaveUp = 'Your changes are in the shared project. The site is taking unusually long; open Share later to look again.';
        if (dialog.open && showingOutcome) outcome();
        publication.update(); paintMenu();
        if (!pending(receipt)) {
          if (!dialog.open && receipt?.stage === 'published') notice('Your deck is live. Open Share for the link.');
          if (!dialog.open && receipt?.stage === 'failed') notice('Your changes were sent, but the project\'s site did not rebuild. Open Share for details.');
          return;
        }
        await new Promise(resolve => setTimeout(resolve, attempt < 30 ? 4000 : 10000));
      }
    } finally { monitoring = false; }
  }
  function startWatch() { outcome(); void monitor(); }

  async function begin() {
    const current = ++visit;
    context = null; progress.textContent = '';
    if (!view()) { paint({title: 'Save this deck as a file first', detail: 'Sharing works on a deck that is saved on this computer.'}); return; }
    paint({title: 'Checking...'});
    lock(true);
    try {
      const info = (await run('share-status', {}, progress)).result;
      if (current !== visit) return;
      context = info; contextOwner = view(); progress.textContent = '';
      if (info.mode === 'new') {
        const select = $('share-destination'); select.replaceChildren();
        for (const target of info.targets) {
          // The name alone means little to a newcomer; say where the project lives.
          let host = ''; try { host = new URL(target.project_url).hostname; } catch {}
          const option = new Option(host ? `${target.label} (${host})` : target.label, target.name, false, target.name === info.default);
          option.dataset.label = target.label; select.add(option);
        }
        if (!info.targets.length) {
          paint({title: 'Not shared yet', detail: 'No project is connected on this computer. Connect your GitLab or GitHub project once; after that, sharing is one click.', action: 'Connect a project...', next: 'connect'});
          return;
        }
        paint({title: 'Not shared yet', detail: 'Sharing puts this deck into your project, so others can open it and the project\'s site can show it. You will see exactly what is sent before anything leaves this computer.' + (dirty() ? '\n\nYour unsaved changes are saved first.' : ''),
          action: 'See what will be shared', next: 'plan-new', pick: true, steps: {save: dirty() ? 'next' : 'done', send: dirty() ? 'todo' : 'next'}});
      } else if (dirty()) {
        paint({title: 'You have unsaved changes', detail: `The next step saves them and looks in ${destination(info)} for changes from others. Nothing is sent yet.`, action: 'Save and check', next: 'check',
          steps: {save: 'next', project: destination(info)}});
      } else await check(current);
    } catch (error) { if (current === visit) fail(error); }
    finally { lock(false); }
  }

  async function check(current) {
    await saved();
    paint({title: 'Checking for changes from others...'});
    let job = await run('exchange-plan', {assets: []}, progress), data = job.result;
    // Pictures and files this deck uses travel with it.
    if (data.assets.length && !data.blocked.length) { job = await run('exchange-plan', {assets: data.assets}, progress); data = job.result; }
    if (current !== visit) return;
    progress.textContent = '';
    if (data.local !== text() || dirty()) throw Error('The deck changed while checking. Open Share again.');
    if (data.blocked.length) {
      paint({title: 'This needs a hand', detail: plainBlocked(data.blocked).join('\n') + '\n\nNothing was sent. Someone who knows Git can sort this out; "More options" below has the detailed view.'});
      return;
    }
    const mine = data.local !== data.base, theirs = data.incoming !== data.base;
    const files = data.paths.length > 1 ? ` ${data.paths.length - 1} attached file(s) go with it.` : '';
    if (data.local === data.incoming && !data.ahead && data.paths.length === 1) {
      if (data.behind) { context.pull = true; paint({title: 'Others changed the project', detail: 'Your deck is unchanged, but there are newer files in the project.', action: 'Get the latest', next: 'pull'}); return; }
      await watchQuiet(); return;
    }
    if (!mine && theirs && !data.ahead && data.paths.length === 1) {
      paint({title: 'Someone else changed this deck', detail: 'You have no changes of your own. Getting theirs replaces what you see with the newer version.', action: 'Get their changes', next: 'pull'});
      return;
    }
    const {merge} = await call('matsugit_merge', {base: data.base, local: data.local, incoming: data.incoming});
    if (current !== visit) return;
    context.data = data; context.planId = job.job;
    const ready = result => {
      context.result = result;
      paint({title: 'Ready to share', detail: `Your changes go to ${destination(context)}.${files}` + (theirs ? '\nChanges someone else made are combined with yours.' : '')
        + '\n\nThe project then rebuilds its site. Anyone with access to the project will see this version.', action: 'Share now', next: 'send',
        steps: {save: 'done', send: 'next', project: destination(context)}});
    };
    if (!merge.conflicts) { ready(mergeResult(merge)); return; }
    context.merge = merge; context.ready = ready;
    paint({title: 'You and someone else changed the same part', detail: `${merge.conflicts} place(s) need your choice between your version and theirs. Nothing is sent until you have chosen.`, action: 'Compare and choose', next: 'resolve'});
  }
  // Nothing to send: show what the last share led to.
  async function watchQuiet() {
    const receipt = publication.receipt() || {};
    if (receipt.revision && receipt.stage !== 'local') {
      outcome();
      // Opening Share is asking "where does it stand?": look once more, even
      // when an earlier look could not see the site.
      if (receipt.provider && receipt.stage !== 'published') void publication.check().then(latest => {
        if (dialog.open && showingOutcome) outcome();
        if (pending(latest)) void monitor();
      }).catch(() => {});
      return;
    }
    paint({title: 'Up to date', detail: 'Everything you saved is in the shared project, and nobody else has changed this deck.', outcome: false,
      link: knownLinks().length ? null : context.site_url || context.project_url, linkLabel: context.site_url ? 'Open the shared deck' : 'Open the project',
      steps: {save: 'done', send: 'done', site: 'unknown', project: destination(context)}});
  }

  go.onclick = async () => {
    if (isBusy() || !step) return;
    const current = visit, doing = step;
    if (doing === 'connect') { dialog.close(); $('publish').click(); return; }
    if (doing === 'resolve') {
      dialog.close();
      mergeReview.open(context.merge, async result => { dialog.showModal(); visit = current; context.ready(result); }, () => {}, {
        title: 'Choose between your version and theirs', applyLabel: 'Continue', localLabel: 'Your version', incomingLabel: 'Their version',
        incomingChoice: 'Keep theirs', status: 'Nothing has been saved or sent yet.', progress: 'Preparing...'});
      return;
    }
    progress.textContent = '';
    try {
      // Save before taking the lock: Save is unavailable while an operation runs.
      if (['check', 'plan-new'].includes(doing)) await saved();
    } catch (error) { fail(error); return; }
    lock(true);
    try {
      if (doing === 'check') await check(current);
      else if (doing === 'plan-new') {
        await saved();
        const args = {...snapshot(), target: $('share-destination').value, build: 'ci', move_source: true};
        context.label = $('share-destination').selectedOptions[0]?.dataset.label || context.label;
        const job = await run('plan', args, progress);
        if (current !== visit) return;
        const data = job.result;
        context.plan = {id: job.job, args, deployment: data.deployment};
        progress.textContent = '';
        paint({title: 'Ready to share', detail: [`Your deck moves into ${data.project_url}, in the folder ${data.directory}.`,
          'A link stays where the file is now, so it still opens from there.',
          `${Object.keys(data.files || {}).length || 1} file(s) are sent. Anyone with access to the project will see them, including notes hidden from the slides.`,
          'The project then rebuilds its site.'].join('\n'), action: 'Share now', next: 'send-new', steps: {save: 'done', send: 'next', project: destination(context)}});
      } else if (doing === 'send-new') {
        const checked = context.plan;
        if (checked.args.text !== text() || dirty()) throw Error('The deck changed after the check. Open Share again.');
        paint({title: 'Sharing...', steps: {save: 'done', send: 'busy', project: destination(context)}});
        // A project that builds its site only on request is asked to; that is what "Share now" promised.
        const job = await run('publish', {...checked.args, plan: checked.id, deploy: checked.deployment === 'ci'}, progress);
        progress.textContent = '';
        if (job.result.publication) publication.pushed(job.result.publication);
        context.deployError = job.result.deployment_error || null;
        if (job.moved) notice(`Shared. This deck now lives at ${job.moved}; the old place is a link to it.`);
        context.project_url = job.result.project_url;
        startWatch();
      } else if (doing === 'send') {
        const data = context.data, before = text();
        if (data.local !== before || dirty()) throw Error('The deck changed after the check. Open Share again.');
        paint({title: 'Sharing...', steps: {save: 'done', send: 'busy', project: destination(context)}});
        // The exchange is bound to the plan that produced the reviewed versions.
        const job = await run('exchange', {deploy: context.deployment === 'ci', plan: context.planId, text: context.result, assets: data.paths.slice(1), message: `Update ${data.relative}`}, progress);
        progress.textContent = '';
        if (text() === before && !dirty()) await reload(true, true, job.result.etag); else await reload();
        if (job.result.publication) publication.pushed(job.result.publication);
        context.deployError = job.result.deployment_error || null;
        startWatch();
      } else if (doing === 'pull') {
        const before = text();
        if (dirty() || state.conflict) throw Error('Your draft changed. Save or review it, then open Share again.');
        paint({title: 'Getting the latest...'});
        const planned = await run('sync-plan', {}, progress);
        if (planned.result.status !== 'updates-available') throw Error(planned.result.status === 'up-to-date' ? 'There was nothing new after all.'
          : 'The newer version cannot be added automatically here. "More options" below has the detailed view.');
        await run('sync', {text: before, plan: planned.job}, progress);
        const refreshed = text() === before && !dirty() ? await reload(true, true) : await reload();
        progress.textContent = '';
        paint(refreshed ? {title: 'Up to date', detail: 'You now have the latest version.'}
          : {title: 'Changes received', detail: 'The file was updated, but your open draft still needs review. Close Share and use Refresh; your draft is retained.'});
      }
    } catch (error) { if (current === visit) fail(error); }
    finally { lock(false); }
  };
  $('share').onclick = () => { if (demo || isBusy()) return; dialog.showModal(); void begin(); };
  if (demo) $('share').disabled = true;
  // "..." menu: the shared deck's slides, document and source, once known.
  function paintMenu() {
    const root = $('more-published'), list = knownLinks();
    root.hidden = !list.length;
    root.replaceChildren(Object.assign(document.createElement('span'), {textContent: 'Shared deck'}), ...list.map(item => {
      const button = document.createElement('button');
      button.type = 'button'; button.dataset.link = item.key; button.title = item.url;
      button.dataset.label = `Open ${item.label.toLowerCase()} ${item.detail}`;
      button.onclick = () => openLink(item.url);
      return button;
    }));
  }
  return {painted(label, busy) {
    paintMenu();
    if (dialog.open) paintLinks(knownLinks());
    const button = $('share');
    button.disabled = demo || state.loading || state.delivering || !(state.session || state.uri);
    button.lastChild.textContent = shareLabel(label);
    button.dataset.state = label === 'Published' ? 'live' : label === 'CI failed' ? 'failed' : label === 'Changes not pushed' ? 'changes' : '';
    button.title = ({'Not pushed': 'Share this deck with others', 'Changes not pushed': 'You have saved changes that are not shared yet',
      Pushed: 'Sent to the project', Building: 'The project is rebuilding its site', Published: 'The site shows this version',
      'CI failed': 'The project\'s site build failed'})[label] || 'Share';
    button.setAttribute('aria-busy', String(label === 'Building' || monitoring && label === 'Pushed'));
    // A share made earlier may still be building: pick the watch up again.
    const receipt = publication.receipt();
    if (!monitoring && pending(receipt) && Date.now() - Date.parse(receipt.pushed_at || 0) < 30 * 60 * 1000) void monitor();
  }};
}
