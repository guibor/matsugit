// Keep native anchor navigation when there is no host bridge. A delayed
// window.open after an RPC failure no longer has the original user gesture.
export async function openWorkspaceLink(event, anchor, app, host, report) {
  const url = new URL(anchor.href);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    event.preventDefault();
    report('This is not a supported web link.');
    return;
  }
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  try {
    if (typeof host?.openExternal === 'function') {
      event.preventDefault();
      await host.openExternal({href:url.href, redirectUrl:false});
    } else if (app.getHostCapabilities()?.openLinks) {
      event.preventDefault();
      const result = await app.openLink({url:url.href});
      if (result?.isError) throw Error('Host refused the link');
    }
  } catch {
    report('The host could not open this link. Copy the link and open it in your browser.');
  }
}
