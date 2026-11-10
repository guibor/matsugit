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
export function plainBlocked(reasons) {
  return [...new Set(reasons.map(reason => BLOCKED.find(([pattern]) => pattern.test(reason))?.[1] || reason))];
}
const safe = url => { try { const parsed = new URL(url); return parsed.protocol === 'https:' && !parsed.username && !parsed.password ? url : null; } catch { return null; } };

export function share({call, state, text, dirty, save, run, lock, isBusy, snapshot, mergeReview, publication, reload, notice, demo}) {
  const dialog = $('share-dialog'), go = $('share-go'), progress = $('share-progress');
  let step = null, context = null, visit = 0;
  $('share').append(createElement(Share2), document.createElement('span'));
  $('share-close').append(createElement(X)); $('share-copy').append(createElement(Copy), 'Copy link');
  $('share-close').onclick = () => dialog.close();
  dialog.addEventListener('cancel', event => { if (isBusy()) event.preventDefault(); });
  dialog.addEventListener('close', () => { visit++; step = null; });
  for (const [id, target] of [['share-advanced-sync', 'git-sync'], ['share-advanced-publish', 'publish'], ['share-advanced-status', 'publication-state']])
    $(id).onclick = () => { if (isBusy()) return; dialog.close(); $(target).click(); };
  $('share-copy').onclick = async () => {
    try { await navigator.clipboard.writeText($('share-link').href); progress.textContent = 'Link copied.'; }
    catch { progress.textContent = 'Could not copy. Select the link above instead.'; }
  };
  const view = () => state.session || state.uri;
  function paint({title, detail = '', action = '', next = null, link = null, linkLabel = 'Open the shared deck', pick = false}) {
    $('share-title').textContent = title; $('share-detail').textContent = detail;
    go.hidden = !action; go.textContent = action; step = next;
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

  // After sending: say honestly whether the site is live, building or unknown.
  async function watch(current) {
    const where = publication.receipt() || {};
    const link = where.site_url || where.project_url || context?.project_url;
    const label = where.site_url ? 'Open the shared deck' : 'Open the project';
    if (!where.provider) {
      paint({title: 'Sent', detail: 'Your changes are in the shared project. matsugit does not know whether this project has a website.', link, linkLabel: label});
      return;
    }
    paint({title: 'Sent. Waiting for the site...', detail: 'The project is rebuilding the site. This usually takes a minute or two. You can close this; the Share button keeps the state.', link, linkLabel: label});
    for (let attempt = 0; attempt < 40 && current === visit; attempt++) {
      const receipt = await publication.check();
      if (current !== visit) return;
      const url = receipt?.site_url || link;
      if (receipt?.stage === 'published') { paint({title: 'Live', detail: 'The site shows this version.', link: url, linkLabel: 'Open the shared deck'}); return; }
      if (receipt?.stage === 'failed') {
        paint({title: 'Sent, but the site did not rebuild', detail: 'Your changes are safe in the project. The project\'s site build reported a failure; whoever looks after the project can see why.',
          link: receipt.pipeline_url || url, linkLabel: receipt.pipeline_url ? 'Open the failed build' : label}); return;
      }
      if (receipt?.check_error) {
        paint({title: 'Sent', detail: 'Your changes are in the shared project. matsugit cannot see the site build from this computer, so check the site yourself before passing the link on.', link: url, linkLabel: label}); return;
      }
      if (attempt >= 6 && receipt?.stage !== 'building') {
        paint({title: 'Sent', detail: 'Your changes are in the shared project. No site build was found for them, so the site may not update by itself.', link: url, linkLabel: label}); return;
      }
      await new Promise(resolve => setTimeout(resolve, 5000));
    }
    if (current === visit) paint({title: 'Sent. The site is still building', detail: 'It is taking longer than usual. Open Share again later to see whether it is live.', link, linkLabel: label});
  }

  async function begin() {
    const current = ++visit;
    context = null; progress.textContent = '';
    if (!view()) { paint({title: 'Save this deck as a file first', detail: 'Sharing works on a deck that is saved on this computer.'}); return; }
    paint({title: 'Checking...'});
    lock(true);
    try {
      const info = (await run('share-status', {}, progress)).result;
      if (current !== visit) return;
      context = info; progress.textContent = '';
      if (info.mode === 'new') {
        const select = $('share-destination'); select.replaceChildren();
        for (const target of info.targets) select.add(new Option(target.label, target.name, false, target.name === info.default));
        if (!info.targets.length) {
          paint({title: 'Not shared yet', detail: 'No project is connected on this computer. Connect your GitLab or GitHub project once; after that, sharing is one click.', action: 'Connect a project...', next: 'connect'});
          return;
        }
        paint({title: 'Not shared yet', detail: 'Sharing puts this deck into your project, so others can open it and the project\'s site can show it.' + (dirty() ? '\n\nYour unsaved changes are saved first.' : ''),
          action: 'Continue', next: 'plan-new', pick: true});
      } else if (dirty()) {
        paint({title: 'You have unsaved changes', detail: `Sharing saves them, then checks ${destination(info)} for changes from others.`, action: 'Save and continue', next: 'check'});
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
      await watchQuiet(current); return;
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
      paint({title: 'Ready to share', detail: `Your changes go to ${data.destination}.${files}` + (theirs ? '\nChanges someone else made are combined with yours.' : '')
        + '\n\nThe project may rebuild its site. Anyone with access to the project will see this version.', action: 'Share now', next: 'send'});
    };
    if (!merge.conflicts) { ready(mergeResult(merge)); return; }
    context.merge = merge; context.ready = ready;
    paint({title: 'You and someone else changed the same part', detail: `${merge.conflicts} place(s) need your choice between your version and theirs. Nothing is sent until you have chosen.`, action: 'Compare and choose', next: 'resolve'});
  }
  // Nothing to send: show what the last share led to.
  async function watchQuiet(current) {
    const receipt = publication.receipt() || {};
    const link = receipt.site_url || receipt.project_url || context.site_url || context.project_url;
    paint({title: 'Up to date', detail: 'Everything you saved has been shared, and nobody else has changed this deck.', link,
      linkLabel: receipt.site_url || context.site_url ? 'Open the shared deck' : 'Open the project'});
    if (receipt.provider && ['pushed', 'building'].includes(receipt.stage)) await watch(current);
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
        const job = await run('plan', args, progress);
        if (current !== visit) return;
        const data = job.result;
        context.plan = {id: job.job, args};
        progress.textContent = '';
        paint({title: 'Ready to share', detail: [`Your deck moves into ${data.project_url}, in the folder ${data.directory}.`,
          'A link stays where the file is now, so it still opens from there.',
          `${Object.keys(data.files || {}).length || 1} file(s) are sent. Anyone with access to the project will see them, including notes hidden from the slides.`,
          'The project may rebuild its site.'].join('\n'), action: 'Share now', next: 'send-new'});
      } else if (doing === 'send-new') {
        const checked = context.plan;
        if (checked.args.text !== text() || dirty()) throw Error('The deck changed after the check. Open Share again.');
        paint({title: 'Sharing...'});
        const job = await run('publish', {...checked.args, plan: checked.id, deploy: false}, progress);
        progress.textContent = '';
        if (job.result.publication) publication.pushed(job.result.publication);
        if (job.moved) notice(`Shared. This deck now lives at ${job.moved}; the old place is a link to it.`);
        context.project_url = job.result.project_url;
        await watch(current);
      } else if (doing === 'send') {
        const data = context.data, before = text();
        if (data.local !== before || dirty()) throw Error('The deck changed after the check. Open Share again.');
        paint({title: 'Sharing...'});
        // The exchange is bound to the plan that produced the reviewed versions.
        const job = await run('exchange', {plan: context.planId, text: context.result, assets: data.paths.slice(1), message: `Update ${data.relative}`}, progress);
        progress.textContent = '';
        if (text() === before && !dirty()) await reload(true, true, job.result.etag); else await reload();
        if (job.result.publication) publication.pushed(job.result.publication);
        await watch(current);
      } else if (doing === 'pull') {
        paint({title: 'Getting the latest...'});
        const planned = await run('sync-plan', {}, progress);
        if (planned.result.status !== 'updates-available') throw Error(planned.result.status === 'up-to-date' ? 'There was nothing new after all.'
          : 'The newer version cannot be added automatically here. "More options" below has the detailed view.');
        await run('sync', {text: text(), plan: planned.job}, progress);
        // The deck had no changes of its own, so the newer file simply replaces it.
        await reload(true, true);
        progress.textContent = '';
        paint({title: 'Up to date', detail: 'You now have the latest version.'});
      }
    } catch (error) { if (current === visit) fail(error); }
    finally { lock(false); }
  };
  $('share').onclick = () => { if (demo || isBusy()) return; dialog.showModal(); void begin(); };
  if (demo) $('share').disabled = true;
  return {painted(label, busy) {
    const button = $('share');
    button.lastChild.textContent = shareLabel(label);
    button.dataset.state = label === 'Published' ? 'live' : label === 'CI failed' ? 'failed' : label === 'Changes not pushed' ? 'changes' : '';
    button.title = ({'Not pushed': 'Share this deck with others', 'Changes not pushed': 'You have saved changes that are not shared yet',
      Pushed: 'Sent to the project', Building: 'The project is rebuilding its site', Published: 'The site shows this version',
      'CI failed': 'The project\'s site build failed'})[label] || 'Share';
    button.setAttribute('aria-busy', String(!!busy));
  }};
}
