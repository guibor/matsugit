// A retry is safe only for a rejected, expired session, never for an uncertain
// transport failure. Context guards prevent late replies from rebinding a new file.
export function sessionConnection({current, request, bind}) {
  let context, pending;
  const aliases = new Set();
  const same = (a, b) => a.sequence === b.sequence && a.path === b.path;
  const changed = () => Error('The document changed while reconnecting. Your draft was not replaced.');
  async function resume(snapshot) {
    const live = current();
    if (!same(snapshot, live)) throw changed();
    if (live.session !== snapshot.session) {
      if (aliases.has(snapshot.session)) return live.session;
      throw changed();
    }
    if (pending) return pending;
    const attempt = (async () => {
      const opened = await request('matsugit_reconnect', {path:snapshot.path});
      if (!same(snapshot, current()) || current().session !== snapshot.session) throw changed();
      if (opened.path !== snapshot.path || typeof opened.session !== 'string' || !opened.session)
        throw Error('The file path changed; reopen the document. Your draft was not replaced.');
      bind(opened);
      aliases.add(snapshot.session);
      return opened.session;
    })();
    pending = attempt;
    try { return await attempt; } finally { if (pending === attempt) pending = null; }
  }
  return async (name, args) => {
    const snapshot = current();
    if (!context || !same(context, snapshot)) { context = snapshot; aliases.clear(); pending = null; }
    if (args?.session && aliases.has(args.session)) args = {...args, session:snapshot.session};
    try { return await request(name, args); }
    catch (error) {
      if (error.message !== 'Workspace expired; reopen the document.' || !snapshot.path
          || !args?.session || args.session !== snapshot.session) throw error;
      const session = await resume(snapshot);
      if (!same(snapshot, current()) || current().session !== session) throw changed();
      return request(name, {...args, session});
    }
  };
}
