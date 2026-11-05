import {Worker} from 'node:worker_threads';
import os from 'node:os';
import fs from 'node:fs';

export class MergeService {
  active = new Set();
  async plan(input, timeout = 5000) {
    if (this.active.size >= 2) throw Error('Merge busy; try again shortly.');
    for (const key of ['base', 'local', 'incoming'])
      if (typeof input[key] !== 'string' || Buffer.byteLength(input[key]) > 2 * 1024 * 1024)
        throw Error('Merge input exceeds the 2 MiB editor limit.');
    // Codex can remove its launch directory after starting the plugin. Node's
    // worker bootstrap needs a valid cwd even though this merge never uses it.
    try { if (!fs.existsSync(process.cwd())) process.chdir(os.tmpdir()); }
    catch { process.chdir(os.tmpdir()); }
    const bundled = typeof __MATSUGIT_MERGE_WORKER__ === 'string';
    const worker = new Worker(bundled ? __MATSUGIT_MERGE_WORKER__ : new URL('./merge-worker.mjs', import.meta.url),
      {eval: bundled, workerData: input, resourceLimits: {maxOldGenerationSizeMb: 128}});
    this.active.add(worker);
    try {
      return await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(Error('Merge took too long. Both versions are retained; review or merge externally.')), timeout);
        const finish = fn => value => { clearTimeout(timer); fn(value); };
        worker.once('message', finish(resolve));
        worker.once('error', finish(reject));
        worker.once('exit', finish(() => reject(Error('Merge interrupted; both versions are retained.'))));
      });
    } finally { this.active.delete(worker); await worker.terminate(); }
  }
  close() { for (const worker of this.active) worker.terminate(); }
}
