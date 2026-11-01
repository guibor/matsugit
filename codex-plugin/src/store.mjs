import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID, createHash} from 'node:crypto';
import {spawn} from 'node:child_process';

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
function read(file) {
  if (checkedPath(file) !== file) throw Error('The document path changed; reopen it before continuing.');
  const bytes = fs.readFileSync(file);
  return new TextDecoder('utf-8', {fatal: true}).decode(bytes);
}
export class WorkspaceStore {
  sessions = new Map();
  jobs = new Map();
  constructor(root) { this.root = root; }
  open(file) {
    const target = checkedPath(file), text = read(target), id = randomUUID();
    if (this.sessions.size >= 64) throw Error('Too many open workspaces; restart the Folioforge plugin.');
    this.sessions.set(id, target);
    return {session: id, name: path.basename(target), text, etag: hash(text), writable: true};
  }
  source(session) {
    const file = this.sessions.get(session);
    if (!file) throw Error('Workspace expired; reopen the document.');
    const text = read(file);
    return {text, etag: hash(text), writable: true};
  }
  save(session, text, etag) {
    checkedText(text);
    const file = this.sessions.get(session);
    if (!file) throw Error('Workspace expired; reopen the document.');
    const current = this.source(session);
    if (!etag || current.etag !== etag) return {outcome: 'conflict', etag: current.etag};
    const temporary = path.join(path.dirname(file), `.folioforge-${randomUUID()}.tmp`);
    try {
      fs.writeFileSync(temporary, text, {flag: 'wx', mode: fs.statSync(file).mode & 0o777});
      // Check again immediately before atomic replacement. Never force overwrite.
      if (hash(read(file)) !== etag) return {outcome: 'conflict'};
      fs.renameSync(temporary, file);
      return {outcome: 'saved', etag: hash(text)};
    } finally { fs.rmSync(temporary, {force: true}); }
  }
  owner(session, hostPath) {
    if (session) {
      const file = this.sessions.get(session);
      if (!file) throw Error('Workspace expired; reopen the document.');
      if (checkedPath(file) !== file) throw Error('The document path changed; reopen it before continuing.');
      if (hostPath && checkedPath(hostPath) !== file) throw Error('Host file and workspace do not match; reopen the document.');
      return file;
    }
    if (hostPath) return checkedPath(hostPath);
    return null;
  }
  start({text, theme, session, name = 'Untitled.md'}, hostPath) {
    checkedText(text);
    if (theme && !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/.test(theme)) throw Error('Invalid theme name.');
    const owner = this.owner(session, hostPath);
    if ([...this.jobs.values()].filter(j => j.state === 'rendering').length >= 2) throw Error('Two previews are already rendering; wait for one to finish.');
    const worker = path.join(this.root, 'codex-plugin/worker.py');
    if (!fs.existsSync(worker)) throw Error('Folioforge plugin files are no longer available. Save or download your draft, then reload the plugin in Codex and reopen the document.');
    for (const [id, job] of this.jobs) {
      if (job.state !== 'rendering' && (Date.now() - job.created > 300_000 || this.jobs.size >= 4)) {
        this.jobs.delete(id); fs.rmSync(job.directory, {recursive: true, force: true});
      }
    }
    const id = randomUUID(), directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'folioforge-workspace-')));
    const extension = formats.has(path.extname(name).toLowerCase()) ? path.extname(name).toLowerCase() : '.md';
    const source = owner || path.join(directory, 'Untitled' + extension);
    const output = path.join(directory, 'render');
    const job = {id, owner, directory, output, state: 'rendering', phase: 'Preparing', created: Date.now()};
    this.jobs.set(id, job);
    // A long-lived host can retain a deleted cwd. Python/pyenv need a real one
    // before the worker starts; absolute source paths still resolve project assets.
    const child = spawn(process.env.FOLIOFORGE_PYTHON || 'python3', [worker],
      {cwd: directory, stdio: ['pipe', 'pipe', 'pipe'], detached: process.platform !== 'win32',
        env: {...process.env, PWD: directory}});
    job.child = child;
    let stderr = '', stdout = '';
    child.stdin.on('error', () => {});
    child.stdin.end(JSON.stringify({path: source, output, text, theme: theme || null}));
    child.stdout.on('data', chunk => { stdout = (stdout + chunk).slice(-10000); });
    child.stderr.on('data', chunk => {
      stderr = (stderr + chunk).slice(-16000);
      if (String(chunk).includes('Rendering html:')) job.phase = 'Rendering document';
      if (String(chunk).includes('Rendering revealjs:')) job.phase = 'Rendering slides';
    });
    const timeout = setTimeout(() => {
      job.state = 'error'; job.error = 'Rendering exceeded four minutes. The source was not changed.';
      this.stopChild(child);
    }, 240_000);
    child.on('error', error => { job.state = 'error'; job.error = `Cannot start renderer: ${error.message}`; clearTimeout(timeout); });
    child.on('close', code => {
      clearTimeout(timeout);
      if (job.state === 'error') return;
      if (code !== 0) {
        job.state = 'error'; job.error = stderr.replaceAll(this.root, '<folioforge>').replaceAll(directory, '<preview>').slice(-4000) || 'Rendering failed.';
      } else {
        try {
          const files = ['index.html', 'slides.html'].map(file => path.join(output, file));
          if (files.some(file => fs.statSync(file).size > 20 * 1024 * 1024)) throw Error('Preview exceeds 20 MiB per view; reduce embedded media.');
          job.rendered = {document: fs.readFileSync(files[0], 'utf8'), slides: fs.readFileSync(files[1], 'utf8')};
          job.theme = JSON.parse(stdout).theme; job.state = 'ready';
        } catch (error) { job.state = 'error'; job.error = error.message; }
      }
    });
    return {job: id, state: job.state, phase: job.phase};
  }
  status(id, session, hostPath) {
    const job = this.jobs.get(id);
    if (!job || job.owner !== this.owner(session, hostPath)) throw Error('Unknown preview for this document.');
    return {job: id, state: job.state, phase: job.phase, error: job.error, theme: job.theme};
  }
  chunk(id, format, offset, session, hostPath) {
    if (this.status(id, session, hostPath).state !== 'ready') throw Error('Preview is not ready.');
    if (!['document', 'slides'].includes(format)) throw Error('Unknown preview format.');
    const html = this.jobs.get(id).rendered[format];
    if (!Number.isInteger(offset) || offset < 0 || offset > html.length) throw Error('Invalid preview offset.');
    const chunk = html.slice(offset, offset + 256 * 1024), next = offset + chunk.length;
    return {chunk, next, done: next === html.length};
  }
  stopChild(child) {
    if (!child?.pid) return;
    try { process.platform === 'win32' ? child.kill() : process.kill(-child.pid, 'SIGTERM'); } catch {}
  }
  close() {
    for (const job of this.jobs.values()) {
      if (job.state === 'rendering') this.stopChild(job.child);
      fs.rmSync(job.directory, {recursive: true, force: true});
    }
    this.jobs.clear(); this.sessions.clear();
  }
}
