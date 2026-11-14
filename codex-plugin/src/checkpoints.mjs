import {execFile} from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import {pythonExecutable, pythonEnvironment} from './python.mjs';
import {recoveryDirectory} from './recovery.mjs';

export class Checkpoints {
  constructor(root, directory = path.join(recoveryDirectory(), 'history')) {
    this.root = root; this.directory = directory; this.pending = 0;
  }
  async run(operation, owner, data = {}) {
    if (!owner) throw Error('History requires a connected document. Save this copy to a file first.');
    if (this.pending >= 8) throw Error('History is busy; retry shortly. Nothing was replaced.');
    this.pending++;
    try {
      return await new Promise((resolve,reject) => {
        const root = typeof this.root === 'function' ? this.root() : this.root;
        const child = execFile(pythonExecutable(), ['-m','matsugit.history'],
          {cwd:os.tmpdir(), env:{...pythonEnvironment(), PYTHONPATH:root, PYTHONDONTWRITEBYTECODE:'1'}, timeout:20000, maxBuffer:13*1024*1024},
          (error,stdout) => {
            try {
              const result = JSON.parse(stdout);
              if (error || result.error) throw Error(result.error || 'History could not finish. Your document was not replaced.');
              resolve(result);
            } catch (failure) { reject(failure); }
          });
        child.stdin.on('error', () => {});
        child.stdin.end(JSON.stringify({directory:this.directory, operation, owner, ...data}));
      });
    } finally { this.pending--; }
  }
}
