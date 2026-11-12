// Keep the local dependency first so esbuild emits contiguous review excerpts.
import {pythonExecutable, pythonEnvironment} from './python.mjs';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID, createHash} from 'node:crypto';
import {spawn, execFile} from 'node:child_process';

export const MAX_SOURCE = 2 * 1024 * 1024;
const formats = new Set(['.md', '.markdown', '.qmd', '.org']);
export const hash = text => createHash('sha256').update(text).digest('hex');
export function checkedPath(file) {
  if (!path.isAbsolute(file)) throw Error('Choose an absolute document path.');
  const target = fs.realpathSync(file), stat = fs.statSync(target);
  if (!formats.has(path.extname(target).toLowerCase()) || !stat.isFile()) throw Error('Choose a Markdown, QMD or Org file.');
  if (stat.size > MAX_SOURCE) throw Error('Document exceeds the 2 MiB editor limit.');
  return target;
}
export function checkedText(text) {
  if (typeof text !== 'string' || Buffer.byteLength(text) > MAX_SOURCE || text.includes('\0')) throw Error('Invalid source or document exceeds 2 MiB.');
  return text;
}
// Said in words a person can act on; the raw system error stays in the cause.
export class MissingFile extends Error {
  constructor(file) {
    super(`The file is no longer at ${file}. It was moved, renamed or deleted. Your text is safe in this window.`);
    this.code = 'missing-file';
  }
}
const writable = file => { try { fs.accessSync(file, fs.constants.W_OK); return true; } catch { return false; } };
export function readSource(file) {
  if (!fs.existsSync(file)) throw new MissingFile(file);
  if (checkedPath(file) !== file) throw Error('The document path changed; reopen it before continuing.');
  const fd = fs.openSync(file, 'r');
  try {
    const info = fs.fstatSync(fd);
    if (!info.isFile() || info.size > MAX_SOURCE) throw Error('Document exceeds the 2 MiB editor limit.');
    const bytes = Buffer.alloc(MAX_SOURCE + 1);
    let count = 0, length;
    while (count < bytes.length && (length = fs.readSync(fd, bytes, count, bytes.length - count, null))) count += length;
    if (count > MAX_SOURCE) throw Error('Document exceeds the 2 MiB editor limit.');
    return new TextDecoder('utf-8', {fatal: true}).decode(bytes.subarray(0, count));
  } finally { fs.closeSync(fd); }
}
export class WorkspaceStore {
  sessions = new Map();
  jobs = new Map();
  themeRequests = new Set();
  relocations = new Map();
  constructor(root) { this.root = root; }
  // Write the guided sample into a folder the user chose, once. If it is already
  // there it is opened as it is: the person may have edited it.
  tour(directory, text) {
    if (typeof directory !== 'string' || !path.isAbsolute(directory)) throw Error('Give the absolute path of a folder for the sample deck.');
    const folder = fs.realpathSync(directory);
    if (!fs.statSync(folder).isDirectory()) throw Error('Choose a folder for the sample deck.');
    const file = path.join(folder, 'matsugit-tour.md');
    try { fs.writeFileSync(file, checkedText(text), {flag: 'wx', mode: 0o644}); }
    catch (error) { if (error.code !== 'EEXIST') throw error; }
    return file;
  }
  open(file) {
    const target = checkedPath(file), text = readSource(target);
    // Sessions identify a file, not a panel draft. Recovery writers remain
    // independent, even when several panels open this same file.
    const existing = [...this.sessions].find(([, owner]) => owner === target)?.[0];
    const id = existing || randomUUID();
    if (!existing && this.sessions.size >= 64) throw Error('Too many open workspaces; restart the matsugit plugin.');
    this.sessions.set(id, target);
    return {session: id, name: path.basename(target), path: target, text, etag: hash(text), writable: true, readOnly: !writable(target)};
  }
  // A reviewed publication may move the open file and leave a symlink while
  // the workspace keeps polling. Follow exactly that reviewed move, never an
  // arbitrary symlink swapped underneath an open workspace.
  expectRelocation(previous, destination) { this.relocations.set(previous, destination); }
  settleRelocation(previous) { this.relocations.delete(previous); }
  followed(file) {
    const destination = this.relocations.get(file);
    if (!destination) return file;
    let moved = false;
    try { moved = fs.lstatSync(file).isSymbolicLink() && checkedPath(file) === destination; } catch { return file; }
    if (!moved) return file;
    for (const [id, item] of this.sessions) if (item === file) this.sessions.set(id, destination);
    for (const job of this.jobs.values()) if (job.owner === file) job.owner = destination;
    return destination;
  }
  source(session) {
    const file = this.followed(this.sessions.get(session));
    if (!file) throw Error('Workspace expired; reopen the document.');
    const text = readSource(file);
    return {text, etag: hash(text), writable: true, readOnly: !writable(file)};
  }
  relocated(previous, destination) {
    // Called only for the explicit reviewed relocation, never to follow an
    // arbitrary symlink swapped underneath an already-open workspace.
    if (!fs.lstatSync(previous).isSymbolicLink() || checkedPath(previous) !== destination)
      throw Error('Relocation changed unexpectedly; reopen the source.');
    for (const [id, file] of this.sessions) if (file === previous) this.sessions.set(id, destination);
    for (const job of this.jobs.values()) if (job.owner === previous) job.owner = destination;
    return this.open(destination);
  }
  save(session, text, etag, {recreate = false} = {}) {
    checkedText(text);
    const file = this.followed(this.sessions.get(session));
    if (!file) throw Error('Workspace expired; reopen the document.');
    if (recreate) {
      // Put the document back where it was, after it was moved or deleted. Only
      // when nothing has appeared there since; never replaces an existing file.
      const parent = path.dirname(file);
      if (fs.realpathSync(parent) !== parent) throw Error('The document directory changed; reopen it before saving.');
      const temporary = path.join(parent, `.matsugit-${randomUUID()}.tmp`);
      try {
        const fd = fs.openSync(temporary, 'wx', 0o600);
        try { fs.writeFileSync(fd, text); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
        if (fs.realpathSync(parent) !== parent) throw Error('The document directory changed; reopen it before saving.');
        // Atomic create-if-absent, including dangling links and racing writers.
        fs.linkSync(temporary, file);
        return {outcome: 'saved', etag: hash(text)};
      } catch (error) {
        if (error.code === 'EEXIST') return {outcome:'conflict'};
        throw error;
      } finally { fs.rmSync(temporary, {force:true}); }
    }
    const current = this.source(session);
    // A file marked read-only on disk is left alone; the rename below would otherwise replace it.
    if (current.readOnly) return {outcome: 'read-only', etag: current.etag};
    if (!etag || current.etag !== etag) return {outcome: 'conflict', etag: current.etag};
    // Identical saves must not invalidate another editor's visited-file timestamp.
    if (current.text === text) return {outcome: 'saved', etag: current.etag};
    const temporary = path.join(path.dirname(file), `.matsugit-${randomUUID()}.tmp`);
    try {
      fs.writeFileSync(temporary, text, {flag: 'wx', mode: fs.statSync(file).mode & 0o777});
      // Check again immediately before atomic replacement. Never force overwrite.
      if (hash(readSource(file)) !== etag) return {outcome: 'conflict'};
      fs.renameSync(temporary, file);
      return {outcome: 'saved', etag: hash(text)};
    } finally { fs.rmSync(temporary, {force: true}); }
  }
  owner(session, hostPath) {
    if (session) {
      const file = this.followed(this.sessions.get(session));
      if (!file) throw Error('Workspace expired; reopen the document.');
      if (checkedPath(file) !== file) throw Error('The document path changed; reopen it before continuing.');
      if (hostPath && checkedPath(hostPath) !== file) throw Error('Host file and workspace do not match; reopen the document.');
      return file;
    }
    if (hostPath) return checkedPath(hostPath);
    return null;
  }
  // Where a deck that was shared from this computer can be opened. Reads the
  // local push receipt only; no network, no login.
  links(file) {
    const target = checkedPath(file);
    const root = typeof this.root === 'function' ? this.root() : this.root;
    return new Promise((resolve, reject) => {
      const child = execFile(pythonExecutable(),
        [path.join(root, 'codex-plugin/actions.py')],
        {cwd: os.tmpdir(), env: {...pythonEnvironment(), PWD: os.tmpdir()}, timeout: 15000, maxBuffer: 262144},
        (error, stdout, stderr) => {
          if (error) { reject(Error(stderr.trim() || 'Could not read where this deck was shared')); return; }
          try { resolve(JSON.parse(stdout)); } catch { reject(Error('Invalid sharing record')); }
        });
      child.stdin.on('error', () => {});
      child.stdin.end(JSON.stringify({action: 'publication-status', path: target, check: false}));
    });
  }
  themes(session, hostPath) {
    const owner = this.owner(session, hostPath);
    if (this.themeRequests.size >= 4) throw Error('Theme discovery busy; try again shortly');
    const root = typeof this.root === 'function' ? this.root() : this.root;
    return new Promise((resolve, reject) => {
      const child = execFile(pythonExecutable(),
        [path.join(root, 'codex-plugin/actions.py')],
        {cwd: os.tmpdir(), env: {...pythonEnvironment(), PWD: os.tmpdir()}, timeout: 15000, maxBuffer: 65536},
        (error, stdout, stderr) => {
          this.themeRequests.delete(child);
          if (error) { reject(Error(stderr.trim() || 'Could not discover installed themes')); return; }
          try { resolve(JSON.parse(stdout)); } catch { reject(Error('Invalid theme list')); }
        });
      this.themeRequests.add(child);
      child.stdin.on('error', () => {});
      child.stdin.end(JSON.stringify({action: 'themes',
        path: owner || path.join(os.tmpdir(), 'matsugit-untitled', 'Untitled.md')}));
    });
  }
  recoveryOwner(session, hostPath) {
    // Checkpoints must still work if the original was deleted or moved. This
    // identity permits recovery storage only; source reads keep strict checks.
    let host = null;
    if (hostPath) {
      if (!path.isAbsolute(hostPath)) throw Error('Choose an absolute document path.');
      try { host = fs.realpathSync(hostPath); }
      catch { host = path.resolve(hostPath); }
    }
    if (!session) return host;
    const owner = this.sessions.get(session);
    if (!owner) throw Error('Workspace expired; reopen the document.');
    if (host && host !== owner) throw Error('Host file and workspace do not match; reopen the document.');
    return owner;
  }
  start({text, theme, session, name = 'Untitled.md', format = 'document', base}, hostPath) {
    checkedText(text);
    if (!['document', 'slides'].includes(format)) throw Error('Unknown preview format.');
    if (theme && !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/.test(theme)) throw Error('Invalid theme name.');
    const owner = this.owner(session, hostPath);
    // Expired bases simply rebuild; never reuse another document's snapshot.
    const previous = this.jobs.get(base);
    if (previous && previous.owner !== owner) throw Error('Unknown preview for this document.');
    const baseline = previous?.state === 'ready' && previous.format === format ? previous : null;
    if ([...this.jobs.values()].filter(j => j.state === 'rendering').length >= 2) throw Error('Two previews are already rendering; wait for one to finish.');
    const root = typeof this.root === 'function' ? this.root() : this.root;
    const worker = path.join(root, 'codex-plugin/worker.py');
    if (!fs.existsSync(worker)) throw Error('matsugit plugin files are no longer available. Save or download your draft, then reload the plugin in Codex and reopen the document.');
    for (const [id, job] of this.jobs) {
      if (job !== baseline && !job.readers && job.state !== 'rendering' && (Date.now() - job.created > 300_000 || this.jobs.size >= 4)) {
        this.jobs.delete(id); fs.rmSync(job.directory, {recursive: true, force: true});
      }
    }
    const id = randomUUID(), directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-workspace-')));
    const extension = formats.has(path.extname(name).toLowerCase()) ? path.extname(name).toLowerCase() : '.md';
    const source = owner || baseline?.source || path.join(directory, 'Untitled' + extension);
    const output = path.join(directory, 'render');
    const job = {id, owner, source, format, directory, output, state: 'rendering', phase: 'Preparing', created: Date.now()};
    if (baseline) baseline.readers = (baseline.readers || 0) + 1;
    this.jobs.set(id, job);
    // A long-lived host can retain a deleted cwd. Python/pyenv need a real one
    // before the worker starts; absolute source paths still resolve project assets.
    const child = spawn(pythonExecutable(), [worker],
      {cwd: directory, stdio: ['pipe', 'pipe', 'pipe'], detached: process.platform !== 'win32',
        env: {...pythonEnvironment(), PWD: directory}});
    job.child = child;
    let stderr = '', stdout = '';
    child.stdin.on('error', () => {});
    child.stdin.end(JSON.stringify({path: source, output, text, format, base: baseline?.output, theme: theme || null}));
    child.stdout.on('data', chunk => { stdout = (stdout + chunk).slice(-10000); });
    child.stderr.on('data', chunk => {
      stderr = (stderr + chunk).slice(-16000);
      if (String(chunk).includes('Rendering html:')) job.phase = 'Rendering document';
      if (String(chunk).includes('Rendering revealjs:')) job.phase = 'Rendering slides';
    });
    const timeout = setTimeout(() => {
      if (job.state !== 'rendering') return;
      job.state = 'error'; job.error = 'Rendering exceeded four minutes. The source was not changed.';
      this.stopChild(child);
    }, 240_000);
    child.on('error', error => { job.state = 'error'; job.error = `Cannot start renderer: ${error.message}`; clearTimeout(timeout); });
    child.on('close', code => {
      clearTimeout(timeout);
      if (baseline) baseline.readers--;
      if (job.state !== 'rendering') return;
      if (code !== 0) {
        job.state = 'error'; job.error = stderr.replaceAll(root, '<matsugit>').replaceAll(directory, '<preview>').slice(-4000) || 'Rendering failed.';
      } else {
        try {
          const result = JSON.parse(stdout);
          const file = path.join(output, result.kind === 'patch' ? 'patch.json' : format === 'slides' ? 'slides.html' : 'index.html');
          if (fs.statSync(file).size > 20 * 1024 * 1024) throw Error('Preview exceeds 20 MiB per view; reduce embedded media.');
          job.rendered = {[format]: fs.readFileSync(file, 'utf8')};
          Object.assign(job, result, {base: result.kind === 'patch' ? baseline.id : null, state: 'ready'});
        } catch (error) { job.state = 'error'; job.error = error.message; }
      }
    });
    return {job: id, state: job.state, phase: job.phase};
  }
  cancel(id, session, hostPath) {
    this.status(id, session, hostPath);
    const job = this.jobs.get(id);
    if (job.state === 'rendering') {
      job.state = 'canceled';
      this.stopChild(job.child);
    }
    return {job: id, state: job.state};
  }
  status(id, session, hostPath) {
    const job = this.jobs.get(id);
    if (!job || job.owner !== this.owner(session, hostPath)) throw Error('Unknown preview for this document.');
    return {job: id, state: job.state, phase: job.phase, error: job.error, theme: job.theme,
      kind: job.kind, format: job.format, base: job.base, changed: job.changed};
  }
  chunk(id, format, offset, session, hostPath) {
    if (this.status(id, session, hostPath).state !== 'ready') throw Error('Preview is not ready.');
    if (!['document', 'slides'].includes(format)) throw Error('Unknown preview format.');
    const html = this.jobs.get(id).rendered[format];
    if (typeof html !== 'string') throw Error('This format has not been rendered.');
    if (!Number.isInteger(offset) || offset < 0 || offset > html.length) throw Error('Invalid preview offset.');
    const chunk = html.slice(offset, offset + 256 * 1024), next = offset + chunk.length;
    return {chunk, next, done: next === html.length};
  }
  stopChild(child) {
    if (!child?.pid) return;
    try { process.platform === 'win32' ? child.kill() : process.kill(-child.pid, 'SIGTERM'); } catch {}
  }
  close() {
    for (const child of this.themeRequests) child.kill();
    for (const job of this.jobs.values()) {
      if (job.state === 'rendering') this.stopChild(job.child);
      fs.rmSync(job.directory, {recursive: true, force: true});
    }
    this.jobs.clear(); this.sessions.clear();
  }
}
