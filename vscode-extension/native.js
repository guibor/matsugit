// Injected only into the VS Code workspace. The outer frame owns VS Code APIs.
(() => {
  let sequence = 0, base = null, latest = null, pending = null, blocked = false, hooks;
  const requests = new Map();
  function request(method, params = {}) {
    const id = ++sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { requests.delete(id); reject(Error('VS Code connection timed out. Your draft is retained.')); }, 120000);
      requests.set(id, {resolve, reject, timer});
      parent.postMessage({matsugitNative: true, id, method, params}, '*');
    });
  }
  async function pump() {
    if (pending || blocked || base === null || latest === base) return pending;
    pending = (async () => {
      while (!blocked && latest !== base) {
        const value = latest;
        const response = await request('edit', {base, text: value});
        base = response.source;
        api.dirty = response.dirty;
        if (!response.applied) {
          blocked = true;
          // Let the workspace's existing three-way review reconcile both drafts.
          setTimeout(() => hooks?.reconcile(), 0);
          break;
        }
      }
    })();
    try { await pending; } catch (error) { blocked = true; hooks?.error(error.message); }
    finally { pending = null; hooks?.refresh(); }
  }
  const api = window.matsugitNativeDocument = {
    dirty: false,
    attach(value) { hooks = value; },
    bind(source, dirty = false) { base = latest = source; blocked = false; api.dirty = dirty; },
    edit(text) { latest = text; void pump(); },
    async read() {
      const data = await request('read');
      api.dirty = data.dirty;
      if (!pending) {
        if (base !== null && data.source !== base) blocked = true;
        base = data.source;
      }
      return {...data, text: data.source};
    },
    async flush() {
      if (blocked) throw Error('Review the changed document before saving. Your draft is retained.');
      await pump();
      if (pending) await pending;
      if (blocked || latest !== base) throw Error('VS Code has not accepted this draft yet. Review changes or retry Save.');
    },
    resume(text) { if (typeof text === 'string') latest = text; blocked = false; void pump(); },
    save: value => request('save', value),
  };
  window.addEventListener('message', event => {
    if (event.source !== parent || !event.data?.matsugitNative) return;
    const message = event.data;
    if (message.method === 'changed') {
      api.dirty = message.params.dirty;
      hooks?.refresh();
      if (message.params.external) void hooks?.reconcile();
      return;
    }
    const item = requests.get(message.id);
    if (!item) return;
    clearTimeout(item.timer); requests.delete(message.id);
    if (message.error) item.reject(Error(message.error)); else item.resolve(message.result);
  });
})();
