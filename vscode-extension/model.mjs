export const MAX_TEXT = 2 * 1024 * 1024;
export const normalized = text => text.replace(/\r\n?/g, '\n');
export function position(text, offset) {
  const lines = normalized(text).slice(0, offset).split('\n');
  return {line: lines.length - 1, character: lines.at(-1).length};
}
export const result = data => ({content: [{type: 'text', text: JSON.stringify(data)}], structuredContent: data});
export function checkedText(value) {
  if (typeof value !== 'string' || value.includes('\0') || Buffer.byteLength(value) > MAX_TEXT)
    throw Error('Document must be UTF-8 text smaller than 2 MiB.');
  return value;
}
export function replacement(before, after) {
  let start = 0, end = 0;
  while (start < before.length && start < after.length && before[start] === after[start]) start++;
  while (end < before.length - start && end < after.length - start && before[before.length - end - 1] === after[after.length - end - 1]) end++;
  return {start, end: before.length - end, text: after.slice(start, after.length - end)};
}

// VS Code owns the buffer, hot-exit backups, disk conflict prompts and native Undo.
// Own draft updates do not masquerade as an external revision in the workspace.
export class DocumentModel {
  revision = 1;
  applying = null;
  queue = Promise.resolve();
  constructor(document, apply, notify = () => {}) {
    this.document = document; this.apply = apply; this.notify = notify;
  }
  snapshot() {
    return {source: normalized(this.document.getText()), etag: `vscode:${this.revision}`,
      writable: true, dirty: this.document.isDirty};
  }
  changed() {
    const external = normalized(this.document.getText()) !== this.applying;
    if (external) this.revision++;
    this.notify({dirty: this.document.isDirty, external});
  }
  saved() { this.revision++; this.notify({dirty: this.document.isDirty, external: true}); }
  edit({base, text}) {
    checkedText(base); checkedText(text);
    const next = this.queue.then(async () => {
      const current = normalized(this.document.getText());
      if (base !== current) return {applied: false, ...this.snapshot()};
      if (text !== current) {
        this.applying = text;
        try {
          if (!await this.apply(replacement(current, text))) return {applied: false, ...this.snapshot()};
        } finally { this.applying = null; }
      }
      return {applied: normalized(this.document.getText()) === text, ...this.snapshot()};
    });
    this.queue = next.catch(() => {});
    return next;
  }
  async save({text, etag}) {
    checkedText(text);
    await this.queue;
    if (this.snapshot().etag !== etag || normalized(this.document.getText()) !== text) return {outcome: 'conflict'};
    const saved = await this.document.save();
    if (!saved) throw Error('VS Code did not save. Resolve its save/conflict prompt; your draft is retained.');
    if (normalized(this.document.getText()) !== text || this.document.isDirty) return {outcome: 'conflict'};
    return {outcome: 'saved', etag: this.snapshot().etag};
  }
}

export function safeLink(value) {
  const url = new URL(value);
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password)
    throw Error('Only HTTP(S) links without credentials can be opened.');
  return url.href;
}
export function download(params) {
  const items = params?.contents;
  if (!Array.isArray(items) || items.length !== 1 || items[0].type !== 'resource') throw Error('Expected one prepared export.');
  const item = items[0].resource;
  if (typeof item?.blob !== 'string' || item.blob.length > 140 * 1024 * 1024 || !/^[A-Za-z0-9+/]*={0,2}$/.test(item.blob))
    throw Error('Invalid or oversized export.');
  const name = decodeURIComponent(new URL(item.uri).pathname.split('/').at(-1)).replace(/[\\/\x00-\x1f]/g, '_');
  if (!name || /^\.+$/.test(name)) throw Error('Invalid export filename.');
  return {name, bytes: Buffer.from(item.blob, 'base64')};
}
