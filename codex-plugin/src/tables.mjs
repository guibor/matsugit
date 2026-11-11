import path from 'node:path';
import {spawn} from 'node:child_process';
import {pythonExecutable, pythonEnvironment} from './python.mjs';

// Pure, bounded table conversion. No paths, network or file-save operations.
export class TableTools {
  children = new Set();
  constructor(runtime) { this.runtime = runtime; }
  run({operation, source, html, format = 'markdown'}) {
    if (!['open','check','serialize'].includes(operation) || !['markdown','org'].includes(format)) throw Error('Unknown table operation');
    for (const value of [source, ...(html === undefined ? [] : [html])]) {
      if (typeof value !== 'string' || Buffer.byteLength(value) > 1024 * 1024 || value.includes('\0')) throw Error('Expected table text up to 1 MiB');
    }
    if (this.children.size >= 4) throw Error('Table conversion busy; try again shortly');
    const root = this.runtime.root();
    return new Promise((resolve, reject) => {
      const child = spawn(pythonExecutable(),
        [path.join(root, 'codex-plugin/actions.py')], {cwd:root, env:pythonEnvironment(), stdio:['pipe','pipe','pipe']});
      this.children.add(child);
      let stdout = '', stderr = '', failure;
      const stop = message => { failure = message; child.kill(); };
      const timer = setTimeout(() => stop('Table conversion timed out; source unchanged'), 60000);
      child.stdin.on('error', () => {});
      child.stdin.end(JSON.stringify({action:'table-' + operation, source, html, format}));
      child.stdout.on('data', part => { stdout += part; if (stdout.length > 4 * 1024 * 1024) stop('Table result is too large'); });
      child.stderr.on('data', part => { stderr = (stderr + part).slice(-4000); });
      child.on('error', error => { failure = error.message; });
      child.on('close', code => {
        clearTimeout(timer); this.children.delete(child);
        if (failure || code !== 0) { reject(Error(failure || stderr || 'Table conversion failed')); return; }
        try { resolve(JSON.parse(stdout)); } catch { reject(Error('Invalid table result; source unchanged')); }
      });
    });
  }
  close() { for (const child of this.children) child.kill(); }
}
