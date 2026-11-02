import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {gunzipSync} from 'node:zlib';

// Built into server.mjs, never sourced from a document or another installed version.
export class PluginRuntime {
  roots = new Set();
  directory = null;
  constructor(archive) {
    const {app, files} = JSON.parse(gunzipSync(Buffer.from(archive, 'base64')));
    if (typeof app !== 'string' || !files || typeof files !== 'object') throw Error('Invalid bundled matsugit runtime.');
    this.app = app;
    this.files = Object.entries(files).map(([name, content]) => {
      if (typeof content !== 'string' || name.includes('\\') ||
          name.split('/').some(part => !part || part.startsWith('.')) ||
          !(name === 'codex-plugin/worker.py' || name.startsWith('matsugit/'))) {
        throw Error('Invalid bundled matsugit runtime path.');
      }
      return [name, Buffer.from(content, 'base64')];
    });
    for (const required of ['codex-plugin/worker.py', 'matsugit/core.py', 'matsugit/preview.py']) {
      if (!files[required]) throw Error('Incomplete bundled matsugit runtime.');
    }
  }
  intact() {
    if (!this.directory) return false;
    try {
      if (!fs.lstatSync(this.directory).isDirectory()) return false;
      return this.files.every(([name, bytes]) => {
        const file = path.join(this.directory, name);
        return fs.lstatSync(file).isFile() && fs.readFileSync(file).equals(bytes);
      });
    } catch { return false; }
  }
  root() {
    if (this.intact()) return this.directory;
    // Private and process-owned. Recreate from memory if temp cleanup removes it.
    const directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'matsugit-runtime-')));
    try {
      fs.chmodSync(directory, 0o700);
      for (const [name, bytes] of this.files) {
        const file = path.join(directory, name);
        fs.mkdirSync(path.dirname(file), {recursive: true, mode: 0o700});
        fs.writeFileSync(file, bytes, {flag: 'wx', mode: 0o600});
      }
    } catch (error) {
      fs.rmSync(directory, {recursive: true, force: true});
      throw error;
    }
    // Older directories may still belong to an in-flight worker. Clean on exit.
    this.roots.add(directory);
    this.directory = directory;
    return directory;
  }
  close() {
    for (const directory of this.roots) fs.rmSync(directory, {recursive: true, force: true});
    this.roots.clear(); this.directory = null;
  }
}
