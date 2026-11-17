import * as vscode from 'vscode';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {DocumentModel, checkedText, download, result, safeLink, position} from './model.mjs';

const expand = value => value.startsWith('~/') ? path.join(os.homedir(), value.slice(2)) : value;
const data = response => {
  if (response.isError) throw Error(response.content?.filter(x => x.type === 'text').map(x => x.text).join('\n'));
  return {...response.structuredContent, ...response._meta};
};

export function activate(context) {
  const identity = context.extension.packageJSON.name;
  const VIEW = identity + '.editor';
  const output = vscode.window.createOutputChannel('matsugit');
  context.subscriptions.push(output);
  const provider = {
    async resolveCustomTextEditor(document, panel) {
      if (!vscode.workspace.isTrusted) throw Error('Trust this workspace before starting local renderer processes.');
      if (document.uri.scheme !== 'file') throw Error('This first release supports local files. Open a local Markdown or Org document.');
      checkedText(document.getText());
      const settings = vscode.workspace.getConfiguration(identity);
      const env = {...process.env};
      const work = context.extension.packageJSON.matsugitProfile;
      let runtime = {};
      if (work) {
        const profile = path.join(os.homedir(), '.config', work.name);
        try { runtime = JSON.parse(await fs.readFile(path.join(profile,'runtime.json'),'utf8')); }
        catch (error) { if (error.code !== 'ENOENT') throw error; }
        env.MATSUGIT_CONFIG = path.join(profile,'config.json');
        env.MATSUGIT_DEFAULT_THEME = work.theme;
        env.MATSUGIT_THEMES_DIR = context.asAbsolutePath('themes');
        env.MATSUGIT_LEGACY_CONFIG = '0';
        if (runtime.python) env.MATSUGIT_PYTHON = runtime.python;
        if (runtime.quarto) env.QUARTO = runtime.quarto;
        env.PATH = [...['python','node','quarto'].filter(k=>runtime[k]).map(k=>path.dirname(runtime[k])),env.PATH || ''].join(path.delimiter);
      }
      if (settings.get('pythonPath')) env.MATSUGIT_PYTHON = expand(settings.get('pythonPath'));
      if (settings.get('configPath')) env.MATSUGIT_CONFIG = expand(settings.get('configPath'));
      const client = new Client({name: 'matsugit-vscode', version: '0.1.0'});
      const transport = new StdioClientTransport({command: expand(settings.get('nodePath') || runtime.node || 'node'),
        args: [context.asAbsolutePath('runtime/server.mjs')], cwd: path.dirname(document.uri.fsPath), env, stderr: 'pipe'});
      const disposables = [];
      let disposed = false, opened, initial, session, hostReady = false;
      const pendingMessages = [];
      const post = message => {
        if (disposed) return;
        if (!hostReady) pendingMessages.push(message);
        else void panel.webview.postMessage({matsugitHost: true, message});
      };
      const model = new DocumentModel(document, async change => {
        const edit = new vscode.WorkspaceEdit();
        const nativePosition = offset => {
          const at = position(document.getText(), offset);
          return new vscode.Position(at.line, at.character);
        };
        edit.replace(document.uri, new vscode.Range(nativePosition(change.start), nativePosition(change.end)), change.text);
        return vscode.workspace.applyEdit(edit);
      }, params => post({matsugitNative: true, method: 'changed', params}));
      disposables.push(vscode.workspace.onDidChangeTextDocument(event => {
        if (event.document === document && event.contentChanges.length) model.changed();
      }), vscode.workspace.onDidSaveTextDocument(saved => { if (saved === document) model.saved(); }));
      panel.onDidDispose(() => {
        disposed = true; disposables.forEach(item => item.dispose());
        void client.close().catch(error => output.appendLine(String(error)));
      });
      panel.webview.options = {enableScripts: true, localResourceRoots: []};
      const backend = async (name, args = {}) => {
        if (args.session && args.session !== session) throw Error('This action belongs to another document.');
        if (['matsugit_open', 'matsugit_reconnect'].includes(name)) {
          if (await fs.realpath(args.path) !== await fs.realpath(document.uri.fsPath)) throw Error('Open another document through VS Code.');
        }
        if (name === 'matsugit_save') return result(await model.save(args));
        if (name === 'matsugit_read') return result({...model.snapshot(), session, path: document.uri.fsPath, name: path.basename(document.uri.fsPath)});
        if (name === 'matsugit_browser') {
          if (document.isDirty || args.etag !== model.snapshot().etag)
            throw Error('Save the current VS Code document before opening it in a browser.');
          if (await fs.realpath(args.path) !== await fs.realpath(document.uri.fsPath))
            throw Error('The browser request belongs to another document.');
          const disk = data(await client.callTool({name:'matsugit_read',arguments:{session}}));
          if ((disk.source ?? disk.text)?.replace(/\r\n?/g,'\n') !== model.snapshot().source)
            throw Error('The file changed on disk. Review it in VS Code before opening the browser.');
          args = {...args,etag:disk.etag};
        }
        const response = await client.callTool({name, arguments: args});
        if (['matsugit_open', 'matsugit_reconnect'].includes(name) && !response.isError) {
          session = data(response).session;
          return result({...data(response), ...model.snapshot()});
        }
        return response;
      };
      async function handle(message) {
        if (message?.matsugitHostReady) {
          hostReady = true;
          for (const next of pendingMessages.splice(0)) post(next);
          return;
        }
        const native = message?.matsugitNative === true;
        if (!native && message?.jsonrpc !== '2.0') return;
        const reply = value => post(native ? {matsugitNative: true, id: message.id, ...value}
          : {jsonrpc: '2.0', id: message.id, ...value});
        try {
          const params = message.params || {};
          let value = {};
          if (native) {
            if (message.method === 'read') value = model.snapshot();
            else if (message.method === 'edit') value = await model.edit(params);
            else if (message.method === 'save') value = await model.save(params);
            else throw Error('Unknown native document operation.');
          } else if (message.method === 'ui/initialize') {
            value = {protocolVersion: '2026-01-26', hostInfo: {name: 'VS Code', version: vscode.version},
              hostCapabilities: {serverTools: {}, serverResources: {}, openLinks: {}, downloadFile: {}},
              hostContext: {theme: vscode.window.activeColorTheme.kind === vscode.ColorThemeKind.Dark ? 'dark' : 'light',
                displayMode: 'fullscreen', availableDisplayModes: ['fullscreen']}};
          } else if (message.method === 'ui/notifications/initialized') {
            post({jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: initial}); return;
          } else if (message.method === 'tools/call') value = await backend(params.name, params.arguments);
          else if (message.method === 'ui/open-link') {
            if (!await vscode.env.openExternal(vscode.Uri.parse(safeLink(params.url)))) throw Error('The link could not be opened.');
          } else if (message.method === 'ui/download-file') {
            const file = download(params);
            const destination = await vscode.window.showSaveDialog({defaultUri: vscode.Uri.joinPath(document.uri, '..', file.name)});
            if (!destination) value = {isError: true};
            else { await vscode.workspace.fs.writeFile(destination, file.bytes); value = {}; }
          } else if (message.method === 'ui/update-model-context' || message.method.startsWith('ui/notifications/')) {
            // Never move keyboard focus or send document text to a chat implicitly.
          } else if (message.method === 'ping') value = {};
          else throw Error('This host does not support ' + message.method);
          if (message.id !== undefined) reply({result: value});
        } catch (error) {
          output.appendLine(String(error));
          if (message.id !== undefined) reply({error: native ? error.message : {code: -32603, message: error.message}});
        }
      }
      disposables.push(panel.webview.onDidReceiveMessage(message => { void handle(message); }));
      try {
        await client.connect(transport);
        if (disposed) { await client.close(); return; }
        transport.stderr?.on('data', bytes => output.append(bytes.toString()));
        opened = await client.callTool({name: 'matsugit_open', arguments: {path: document.uri.fsPath, layout: 'split', format: 'slides', editor: 'visual', autosave: false}});
        session = data(opened).session;
        initial = result({...data(opened), ...model.snapshot()});
        const resource = await client.readResource({uri: 'ui://matsugit/workspace-v1'});
        let html = resource.contents[0].text;
        const nativeScript = await fs.readFile(context.asAbsolutePath('native.js'), 'utf8');
        html = html.replace('<head>', '<head><script>' + nativeScript + '</script><style>#open,#file{display:none!important}</style>');
        const hostScript = await fs.readFile(context.asAbsolutePath('host.js'), 'utf8');
        const source = Buffer.from(html).toString('base64');
        const start = `document.getElementById('workspace').src=URL.createObjectURL(new Blob([Uint8Array.from(atob('${source}'),c=>c.charCodeAt(0))],{type:'text/html'}));`;
        const script = hostScript + '\n' + start;
        panel.webview.html = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' data: blob:; style-src 'unsafe-inline' data: blob:; frame-src data: blob:; img-src data: blob:; font-src data: blob:; connect-src 'none'; base-uri https://matsugit.invalid;"><style>html,body,iframe{width:100%;height:100%;border:0;margin:0;display:block;overflow:hidden}</style></head><body><iframe id="workspace" title="matsugit" sandbox="allow-scripts allow-forms allow-modals allow-downloads" allow="clipboard-write"></iframe><script>${script}</script></body></html>`;
      } catch (error) {
        output.appendLine(String(error));
        await client.close().catch(() => {});
        void vscode.window.showErrorMessage('matsugit could not start: ' + error.message + '. Check Node 22+, Python 3.10+, Quarto and Pandoc, then reopen the tab.');
        throw error;
      }
    }
  };
  context.subscriptions.push(vscode.window.registerCustomEditorProvider(VIEW, provider,
    {webviewOptions: {retainContextWhenHidden: true}, supportsMultipleEditorsPerDocument: false}));
  context.subscriptions.push(vscode.commands.registerCommand(identity + '.open', async uri => {
    const selected = uri || vscode.window.activeTextEditor?.document.uri
      || (await vscode.window.showOpenDialog({canSelectMany: false, filters: {Documents: ['md', 'markdown', 'org']}}))?.[0];
    if (selected) await vscode.commands.executeCommand('vscode.openWith', selected, VIEW);
  }));
}
