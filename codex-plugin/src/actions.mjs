import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {checkedText} from './store.mjs';

export class WorkspaceActions {
  jobs = new Map();
  plans = new Map();
  constructor(runtime, store) { this.runtime = runtime; this.store = store; }
  start(args, hostPath) {
    const owner = this.store.owner(args.session, hostPath);
    if (['export','plan','publish','sync','exchange'].includes(args.action)) checkedText(args.text);
    if (['plan', 'publish', 'sync-plan', 'sync', 'exchange-plan', 'exchange', 'publication-status', 'share-status'].includes(args.action) && !owner) throw Error('Open and save a local source file first');
    const passive = ['publication-status', 'share-status'];
    if (!passive.includes(args.action) && [...this.jobs.values()].some(j => j.state === 'running' && j.owner === owner && !passive.includes(j.action))) throw Error('An export or publication is already running for this document');
    // A new review replaces this document's previous review, not its downloads
    // or another document's confirmation. Otherwise repeated checks exhaust jobs.
    if (['plan', 'sync-plan', 'exchange-plan'].includes(args.action)) {
      for (const [id, plan] of this.plans) {
        if (plan.owner === owner && plan.action === args.action) {
          this.plans.delete(id);
          const job = this.jobs.get(id);
          if (job && job.state !== 'running' && !job.file) {
            fs.rmSync(job.directory, {recursive:true, force:true}); this.jobs.delete(id);
          }
        }
      }
    }
    if (this.jobs.size >= 24) {
      for (const [id, job] of this.jobs) {
        if (job.state !== 'running' && !job.file && !this.plans.has(id)) {
          fs.rmSync(job.directory, {recursive:true,force:true}); this.jobs.delete(id);
        }
      }
    }
    if (this.jobs.size >= 24) throw Error('Reopen this workspace to start more exports; existing downloads are retained until then');
    let fingerprint, relocation;
    if (['publish','sync','exchange'].includes(args.action)) {
      const plan = this.plans.get(args.plan);
      const kind = args.action === 'exchange' ? 'exchange-plan' : args.action === 'sync' ? 'sync-plan' : 'plan';
      if (!plan || plan.action !== kind || plan.owner !== owner || plan.target !== args.target || plan.theme !== args.theme || plan.build !== args.build || plan.move_source !== args.move_source || JSON.stringify(plan.assets || []) !== JSON.stringify(args.assets || [])) throw Error('Review this operation first');
      fingerprint = plan.fingerprint;
      relocation = plan.relocation;
      this.plans.delete(args.plan);
    }
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-action-'));
    fs.chmodSync(directory, 0o700);
    const id = randomUUID();
    const extension = ['.md','.markdown','.qmd','.org'].includes(path.extname(args.name || '').toLowerCase()) ? path.extname(args.name) : '.md';
    const output = args.action === 'export' && !args.sync_folder ? path.join(directory, 'export.' + args.format) : undefined;
    const job = {owner, directory, state:'running', action:args.action, log:'', destination:relocation?.destination};
    if (relocation) this.store.expectRelocation(owner, relocation.destination);
    this.jobs.set(id, job);
    const child = spawn(process.env.MATSUGIT_PYTHON || process.env.FOLIOFORGE_PYTHON || 'python3',
      [path.join(this.runtime.root(), 'codex-plugin/actions.py')], {cwd:directory, stdio:['pipe','pipe','pipe']});
    job.child = child;
    let stdout = '';
    child.stdin.on('error', () => {});
    child.stdin.end(JSON.stringify({...args, path: owner || path.join(directory,'Untitled'+extension), output, fingerprint}));
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', data => {
      stdout += data;
      if (stdout.length > 48 * 1024 * 1024) { job.state='error'; job.error='Git review is too large; use Git for this repository'; child.kill(); }
    });
    child.stderr.on('data', data => { job.log = (job.log + data).slice(-8000); });
    child.on('error', error => { job.state='error'; job.error=error.message; if (relocation) this.store.settleRelocation(owner); });
    child.on('close', code => {
      if (relocation) this.store.settleRelocation(owner);
      if (job.state === 'error') return;
      if (relocation && fs.existsSync(owner) && fs.lstatSync(owner).isSymbolicLink()
          && fs.realpathSync(owner) === relocation.destination) {
        try {
          job.workspace = this.store.relocated(owner, relocation.destination);
          for (const item of this.jobs.values()) if (item.owner === owner) item.owner = relocation.destination;
        } catch (error) { job.state='error'; job.error=error.message; return; }
      }
      if (code !== 0) { job.state='error'; job.error=job.log || 'Operation failed'; return; }
      try {
        job.result = JSON.parse(stdout); job.state = 'ready';
        if (['plan','sync-plan','exchange-plan'].includes(args.action)) this.plans.set(id, {action:args.action, owner, target:args.target, theme:args.theme, build:args.build, move_source:args.move_source, assets:args.assets, relocation:job.result.relocation, fingerprint:job.result.fingerprint});
        if (output) {
          const size = fs.statSync(output).size;
          if (size > 100 * 1024 * 1024) throw Error('Export exceeds the 100 MiB download limit; use the command line');
          job.file = output; job.size = size;
        }
      } catch (error) { job.state='error'; job.error=error.message; }
    });
    return {job:id, state:job.state};
  }
  status(id, session, hostPath) {
    const job = this.jobs.get(id);
    const owner = job && this.store.owner(session, hostPath);
    // While a reviewed move is in flight the document answers at its new path.
    if (!job || (job.owner !== owner && job.destination !== owner)) throw Error('Unknown operation for this document');
    return {job:id, state:job.state, error:job.error, log:job.log, result:job.result, workspace:job.workspace, size:job.size};
  }
  chunk(id, offset, session, hostPath) {
    this.status(id, session, hostPath);
    const job = this.jobs.get(id);
    if (job.state !== 'ready' || !job.file || !Number.isSafeInteger(offset) || offset < 0 || offset > job.size) throw Error('Invalid export download');
    const buffer = Buffer.alloc(Math.min(192 * 1024, job.size - offset));
    const fd = fs.openSync(job.file, 'r');
    try { fs.readSync(fd, buffer, 0, buffer.length, offset); }
    finally { fs.closeSync(fd); }
    return {chunk:buffer.toString('base64'), next:offset+buffer.length, done:offset+buffer.length === job.size};
  }
  close() {
    for (const job of this.jobs.values()) {
      // Never delete files from beneath an in-flight git push.
      if (job.state !== 'running') fs.rmSync(job.directory, {recursive:true,force:true});
    }
    return ![...this.jobs.values()].some(job => job.state === 'running');
  }
}
