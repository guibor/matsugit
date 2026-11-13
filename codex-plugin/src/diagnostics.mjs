import {execFile} from 'node:child_process';
import os from 'node:os';
import {pythonExecutable, pythonEnvironment} from './python.mjs';

export class SetupDiagnostics {
  pending = null;
  constructor(root) { this.root = root; }
  run() {
    // Repeated clicks share a bounded read-only check, not more child processes.
    if (this.pending) return this.pending;
    this.pending = new Promise((resolve,reject) => {
      const root = typeof this.root === 'function' ? this.root() : this.root;
      execFile(pythonExecutable(),['-m','matsugit','doctor','--json'],
        {cwd:os.tmpdir(), env:{...pythonEnvironment(), PYTHONPATH:root, PYTHONDONTWRITEBYTECODE:'1', PWD:os.tmpdir()},
          timeout:65000, maxBuffer:128*1024}, (error,stdout) => {
          try {
            if (error && error.code !== 1) throw Error('Setup check could not finish. Check Python 3.10+ is available, then retry.');
            const data = JSON.parse(stdout);
            if (data.schema !== 1 || typeof data.ready !== 'boolean' || !Array.isArray(data.checks)) throw Error('Invalid setup check response. Reload the updated plugin and retry.');
            resolve(data);
          } catch (failure) { reject(failure); }
        });
    }).finally(() => { this.pending = null; });
    return this.pending;
  }
}
