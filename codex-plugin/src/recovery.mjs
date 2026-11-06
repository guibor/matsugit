import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {checkedText} from './store.mjs';

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const MAX_RECORD = 12 * 1024 * 1024;
export function recoveryDirectory() {
  if (process.env.MATSUGIT_RECOVERY_DIR || process.env.FOLIOFORGE_RECOVERY_DIR) {
    return process.env.MATSUGIT_RECOVERY_DIR || process.env.FOLIOFORGE_RECOVERY_DIR;
  }
  // Keep upgrades in the same recovery store, including concurrently open old viewers.
  // Do not move, merge, rewrite or delete any recovery records during installation.
  const legacy = process.platform === 'darwin'
    ? path.join(os.homedir(), 'Library/Application Support/Folioforge/recovery')
    : path.join(process.env.XDG_STATE_HOME || path.join(os.homedir(), '.local/state'), 'folioforge/recovery');
  if (fs.existsSync(legacy)) return legacy;
  return (process.platform === 'darwin'
    ? path.join(os.homedir(), 'Library/Application Support/matsugit/recovery')
    : path.join(process.env.XDG_STATE_HOME || path.join(os.homedir(), '.local/state'), 'matsugit/recovery'));
}
const number = (value, fallback, max) => Number.isFinite(value) && value >= 0 ? Math.min(value, max) : fallback;
function tableDraft(value) {
  if (!value || !Number.isSafeInteger(value.from) || !Number.isSafeInteger(value.to) ||
      value.from < 0 || value.to < value.from || value.to > 2*1024*1024 ||
      !['markdown','org'].includes(value.format)) return null;
  for (const item of [value.source,value.html]) if (typeof item !== 'string' || Buffer.byteLength(item)>1024*1024 || item.includes('\0')) return null;
  return {from:value.from,to:value.to,source:value.source,html:value.html,format:value.format};
}
export function preferences(value = {}) {
  if (!value || typeof value !== 'object') value = {};
  const position = p => ({hash: typeof p?.hash === 'string' && /^#/.test(p.hash) ? p.hash.slice(0, 1024) : '',
    scroll: number(p?.scroll, 0, 1e9), h: Math.floor(number(p?.h, 0, 100000)), v: Math.floor(number(p?.v, 0, 100000)),
    slideId: typeof p?.slideId === 'string' ? p.slideId.slice(0, 512) : ''});
  return {layout: ['source', 'render', 'split', 'story'].includes(value.layout) ? value.layout : 'split',
    storyPreview:value.storyPreview === true,
    editorMode:value.editorMode==='visual'?'visual':'raw', tableDraft:tableDraft(value.tableDraft),
    slideSeparators: value.slideSeparators === true,
    format: value.format === 'slides' ? 'slides' : 'document',
    theme: typeof value.theme === 'string' && /^[\w-]{0,80}$/.test(value.theme) ? value.theme : '',
    auto: value.auto !== false, sync: value.sync !== false,
    anchor: Math.floor(number(value.anchor, 0, 2 * 1024 * 1024)), head: Math.floor(number(value.head, 0, 2 * 1024 * 1024)),
    editorScroll: number(value.editorScroll, 0, 1e9), width: Math.max(20, number(value.width, 50, 80)),
    height: Math.max(20, number(value.height, 50, 80)),
    positions: {document: position(value.positions?.document), slides: position(value.positions?.slides)}};
}
export class RecoveryStore {
  writers = new Map();
  constructor(directory = recoveryDirectory(), {maxRecords = 128, maxBytes = 128 * 1024 * 1024} = {}) {
    this.directory = path.resolve(directory); this.maxRecords = maxRecords; this.maxBytes = maxBytes;
  }
  prepare() {
    fs.mkdirSync(this.directory, {recursive: true, mode: 0o700});
    const stat = fs.lstatSync(this.directory);
    if (!stat.isDirectory() || (process.getuid && (stat.uid !== process.getuid() || (stat.mode & 0o077)))) {
      throw Error('Recovery directory must be a private directory owned by your user.');
    }
  }
  file(id) {
    if (!uuid.test(id)) throw Error('Invalid recovery ID.');
    return path.join(this.directory, id + '.json');
  }
  read(id) {
    this.prepare();
    const file = this.file(id), stat = fs.lstatSync(file);
    if (!stat.isFile() || stat.size > MAX_RECORD || (process.getuid && (stat.uid !== process.getuid() || (stat.mode & 0o077)))) {
      throw Error('Unsafe or oversized recovery copy; original retained.');
    }
    const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
    let record;
    try { record = JSON.parse(fs.readFileSync(fd, 'utf8')); } finally { fs.closeSync(fd); }
    if (record.version !== 1 || record.id !== id || typeof record.identity !== 'string' ||
        typeof record.name !== 'string' || !Number.isFinite(record.updated) || !uuid.test(record.token) ||
        (record.owner !== null && (typeof record.owner !== 'string' || !path.isAbsolute(record.owner)))) {
      throw Error('Unsupported recovery copy; original retained.');
    }
    checkedText(record.text); checkedText(record.base);
    return {...record, view: preferences(record.view)};
  }
  list(identity) {
    this.prepare();
    const items = []; let unreadable = 0;
    for (const name of fs.readdirSync(this.directory).filter(name => /^[a-f0-9-]{36}\.json$/.test(name))) {
      try {
        const record = this.read(name.slice(0, -5));
        if (identity !== undefined && record.identity !== identity) continue;
        items.push({id: record.id, name: record.name, owner: record.owner, updated: record.updated,
          dirty: record.text !== record.base || !!record.view.tableDraft, token: record.token});
      } catch { unreadable++; }
    }
    items.sort((a, b) => b.updated - a.updated || a.id.localeCompare(b.id));
    return {items, unreadable};
  }
  begin({owner = null, resourceUri, name = 'Untitled.md'}) {
    if (owner !== null && (typeof owner !== 'string' || !path.isAbsolute(owner))) throw Error('Invalid recovery owner.');
    if (typeof name !== 'string' || name.length > 512 || (resourceUri && (typeof resourceUri !== 'string' || resourceUri.length > 4096))) {
      throw Error('Invalid recovery document.');
    }
    const identity = owner || (resourceUri ? 'resource:' + resourceUri : 'untitled');
    const {items} = this.list(identity);
    const id = randomUUID();
    // A new viewer always gets a separate writer, including after restoration.
    // No two processes ever overwrite the same recovery file.
    this.writers.set(id, {owner, identity, name, generation: -1});
    return {id, candidate: items[0] ? this.read(items[0].id) : null};
  }
  checkpoint(id, generation, snapshot, owner = null) {
    const writer = this.writers.get(id);
    if (!writer || writer.owner !== owner) throw Error('Recovery workspace expired; reopen recovery before continuing.');
    if (!Number.isSafeInteger(generation) || generation < 0) throw Error('Invalid recovery generation.');
    if (generation <= writer.generation) return {stale: true};
    checkedText(snapshot.text); checkedText(snapshot.base);
    return this.locked(id, () => {
      if (writer.generation >= 0 && !fs.existsSync(this.file(id))) throw Error('Recovery copy was removed; reopen the workspace to resume checkpoints.');
      const record = {version: 1, id, token: randomUUID(), identity: writer.identity, owner: writer.owner, name: writer.name,
        text: snapshot.text, base: snapshot.base, view: preferences(snapshot.view), updated: Date.now()};
      const bytes = JSON.stringify(record);
      if (Buffer.byteLength(bytes) > MAX_RECORD) throw Error('Recovery copy exceeds its size limit.');
      const entries = fs.readdirSync(this.directory).filter(name => /^[a-f0-9-]{36}\.json$/.test(name));
      const file = this.file(id);
      let size = Buffer.byteLength(bytes);
      for (const entry of entries) if (entry !== id + '.json') size += fs.lstatSync(path.join(this.directory, entry)).size;
      if ((!entries.includes(id + '.json') && entries.length >= this.maxRecords) || size > this.maxBytes) {
        throw Error('Recovery storage is full. Download drafts and remove unwanted copies from Recover workspaces. Nothing was deleted.');
      }
      const temporary = path.join(this.directory, '.' + randomUUID() + '.tmp');
      try {
        const fd = fs.openSync(temporary, 'wx', 0o600);
        try { fs.writeFileSync(fd, bytes); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
        fs.renameSync(temporary, file);
        writer.generation = generation;
      } finally { fs.rmSync(temporary, {force: true}); }
      return {updated: record.updated};
    });
  }
  locked(id, action) {
    this.prepare();
    const file = this.file(id) + '.lock';
    let fd;
    try { fd = fs.openSync(file, 'wx', 0o600); }
    catch (error) { if (error.code === 'EEXIST') throw Error('Recovery copy is busy or has an interrupted write. Original retained; try again or reopen the workspace.'); throw error; }
    try { return action(); }
    finally { fs.closeSync(fd); fs.unlinkSync(file); }
  }
  forget(id, token) {
    return this.locked(id, () => {
      const record = this.read(id);
      if (record.token !== token) throw Error('This recovery copy changed. Refresh the list before deleting it.');
      // An in-use writer must not resurrect a copy deleted in this process.
      this.writers.delete(id);
      fs.unlinkSync(this.file(id));
      return {forgotten: true};
    });
  }
}
