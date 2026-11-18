const closed = error => /\btransport closed\b/i.test(error?.message);
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

function unconfirmed(action, cause) {
  const message = ['publish', 'exchange'].includes(action)
    ? 'Check the latest commit for this document in the target repository before sharing again.'
    : action === 'export' ? 'Check the output folder or Downloads before exporting again.'
    : action === 'sync' ? 'Check the local file and repository status before syncing again.'
    : action === 'connect-repository' ? 'Check your configured targets before connecting again.'
    : 'Reconnect Matsugit and reopen this dialog to check the status again.';
  return Object.assign(new Error(message, {cause}), {unconfirmed: true});
}

export async function deliveryJob(call, owner, action, args, progress, sleep = wait) {
  let job;
  try { job = await call('matsugit_action', {...owner, action, ...args}); }
  catch (error) {
    if (!closed(error)) throw error;
    throw unconfirmed(action, error);
  }
  let retried = false;
  while (job.state === 'running') {
    await sleep(500);
    const poll = () => call('matsugit_action_status', {...owner, job:job.job});
    try { job = await poll(); }
    catch (error) {
      if (!closed(error) || retried) throw unconfirmed(action, error);
      // The action may already have finished. Retry its receipt, never its start.
      retried = true;
      progress.textContent = 'Connection interrupted. Checking the same operation...';
      await sleep(1000);
      try { job = await poll(); } catch (cause) { throw unconfirmed(action, cause); }
    }
    progress.textContent = job.log || (job.state === 'running' ? 'Working...' : '');
  }
  return job;
}
