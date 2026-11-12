import {McpServer} from '@modelcontextprotocol/server';
import {serveStdio} from '@modelcontextprotocol/server/stdio';
import {OpenAIExtensions} from '@openai/mcp-extensions/server';
import {getResourcePath, OpenAIFileEntrypointInputSchema} from '@openai/mcp-extensions';
import {z} from 'zod';
import fs from 'node:fs';
import path from 'node:path';
// The guided sample deck: one source, shared with `matsugit template tour`.
import tourDeck from '../../matsugit/templates/tour.md';
import {WorkspaceStore, MAX_SOURCE, checkedPath, checkedText, readSource} from './store.mjs';
import {checkDeck, checkSummary} from './check.mjs';
import {PluginRuntime} from './runtime.mjs';
import {RecoveryStore} from './recovery.mjs';
import {WorkspaceActions} from './actions.mjs';
import {TableTools} from './tables.mjs';
import {MergeService} from './merge-service.mjs';

const uri = 'ui://matsugit/workspace-v1';
const runtime = new PluginRuntime(__MATSUGIT_RUNTIME__);
const store = new WorkspaceStore(() => runtime.root());
const recovery = new RecoveryStore();
const actions = new WorkspaceActions(runtime, store);
const tables = new TableTools(runtime);
const merges = new MergeService(() => path.join(runtime.root(), 'codex-plugin/merge-worker.cjs'));
const recoveryOwner = (args, context) => args.session || args.resourceUri
  ? store.recoveryOwner(args.session, getResourcePath(context.mcpReq?._meta)) : null;
const scope = {session: z.string().optional(), resourceUri: z.string().max(4096).optional()};
const readOnly = {readOnlyHint: true, destructiveHint: false, openWorldHint: false};
const viewOptions = {layout: z.enum(['source', 'render', 'split', 'story']).optional(), format: z.enum(['document', 'slides']).optional(), editor: z.enum(['raw', 'visual']).optional(), autosave: z.boolean().optional()};
const appOnly = {_meta: {ui: {visibility: ['app']}}};
const result = (data, meta) => ({content: [{type: 'text', text: JSON.stringify(data)}], structuredContent: data, ...(meta ? {_meta: meta} : {})});
// App-only tools need ordinary MCP payloads too: not every host forwards _meta.
const appResult = (data, meta) => result({...data, ...meta});
const guard = fn => async (...args) => {
  try { return await fn(...args); }
  catch (error) { return {isError: true, content: [{type: 'text', text: error.message}]}; }
};
serveStdio(() => {
  const server = new McpServer({name: 'matsugit', version: '0.32.0'});
  server.registerTool('matsugit_merge', {description:'Compute a local three-way merge of workspace text. Never saves, publishes or executes document content.', ...appOnly,
    inputSchema:z.object({base:z.string().max(MAX_SOURCE), local:z.string().max(MAX_SOURCE), incoming:z.string().max(MAX_SOURCE)}), annotations:readOnly},
    guard(async args => appResult({computed:true}, {merge:await merges.plan(args)})));
  new OpenAIExtensions(server);
  server.registerTool('matsugit_table', {description:'Convert or validate a selected table locally. Does not save or publish.', ...appOnly,
    inputSchema:z.object({operation:z.enum(['open','check','serialize']), source:z.string().max(1024*1024),
      html:z.string().max(1024*1024).optional(), format:z.enum(['markdown','org']).optional()}), annotations:readOnly},
    guard(async args => appResult({converted:true}, await tables.run(args))));
  server.registerTool('matsugit_action', {description:'Explicit workspace export, target preview or confirmed publication. Publishing commits/pushes and may trigger existing CI.', ...appOnly,
    inputSchema:z.object({action:z.enum(['options','export','plan','publish','repositories','connect-repository','sync-plan','sync','exchange-plan','exchange','publication-status','share-status']), session:z.string().optional(), check:z.boolean().optional(),
      assets:z.array(z.string().max(4096)).max(100).optional(), message:z.string().min(1).max(500).optional(),
      provider:z.enum(['github','gitlab']).optional(), host:z.string().max(253).optional(), repository:z.string().max(512).optional(), page:z.number().int().min(1).max(1000).optional(),
      text:z.string().max(MAX_SOURCE).optional(), name:z.string().max(512).optional(), theme:z.string().max(80).optional(),
      target:z.string().max(80).optional(), build:z.enum(['ci','local']).optional(), format:z.enum(['html','zip','pptx','pdf']).optional(),
      sync_folder:z.boolean().optional(), replace:z.boolean().optional(), plan:z.string().optional(), deploy:z.boolean().optional(), move_source:z.boolean().optional()}),
    annotations:{readOnlyHint:false, destructiveHint:true, openWorldHint:true}},
    guard(async (args,context) => result(actions.start(args,getResourcePath(context.mcpReq?._meta)))));
  server.registerTool('matsugit_action_status', {description:'Read progress for this workspace operation.', ...appOnly,
    inputSchema:z.object({job:z.string(),session:z.string().optional()}),annotations:readOnly},
    guard(async ({job,session},context) => result(actions.status(job,session,getResourcePath(context.mcpReq?._meta)))));
  server.registerTool('matsugit_export_chunk', {description:'Download a bounded chunk of this workspace export.', ...appOnly,
    inputSchema:z.object({job:z.string(),session:z.string().optional(),offset:z.number().int().nonnegative()}),annotations:readOnly},
    guard(async ({job,session,offset},context) => {const {chunk,...data}=actions.chunk(job,offset,session,getResourcePath(context.mcpReq?._meta)); return appResult(data,{chunk});}));
  server.registerTool('matsugit_export_save', {description:'On explicit Save to Downloads, save this workspace\'s already-prepared export in the plugin machine\'s Downloads folder. Returns the real path and machine. Never overwrites existing files, uploads or publishes.', ...appOnly,
    inputSchema:z.object({job:z.string(),session:z.string().optional()}),
    annotations:{readOnlyHint:false,destructiveHint:false,openWorldHint:false}},
    guard(async ({job,session},context) => result(actions.saveExport(job,session,getResourcePath(context.mcpReq?._meta)))));
  server.registerResource('workspace', uri, {mimeType: 'text/html;profile=mcp-app'}, async () => ({contents: [{
    uri, mimeType: 'text/html;profile=mcp-app', text: runtime.app,
    _meta: {'openai/ui': {preferredDisplayMode: 'fullscreen', availableDisplayModes: ['fullscreen']},
      ui: {csp: {frameDomains: ['blob:'], resourceDomains: ['data:', 'blob:'], baseUriDomains: ['https://matsugit.invalid']}}},
  }]}));
  // Opened without a file (for example from the app launcher): show the guided
  // sample rather than an empty template, so the first look already does something.
  server.registerTool('matsugit_workspace', {title: 'matsugit', description: 'Open a scratch matsugit workspace showing the guided sample deck, with document and slide previews. Nothing is saved to a file. Does not publish. To give the user a sample they can keep, use matsugit_tour.',
    inputSchema: z.object(viewOptions), annotations: readOnly,
    _meta: {ui: {resourceUri: uri}, 'openai/ui': {entrypoints: [{type: 'global'}]}}},
    async options => result({layout: 'split', format: 'slides', editor: 'visual', ...options, name: 'matsugit-tour.md', text: tourDeck, writable: false}));
  server.registerTool('matsugit_tour', {title: 'Show me how matsugit works',
    description: 'First-time users: create a short guided sample deck (matsugit-tour.md) in the given folder and open it beside the chat. The slides themselves explain what to try: edit a title and watch the slide, Add a layout, ask the agent for changes, Story, Check, Present, Share. Use when someone is new to matsugit, asks how it works or wants to try it without notes. An existing matsugit-tour.md there is opened as it is, never overwritten. Writes only that one file; never publishes.',
    inputSchema: z.object({directory: z.string().describe('Absolute path of the folder to put the sample in, usually the open project'), ...viewOptions}),
    annotations: {readOnlyHint: false, destructiveHint: false, openWorldHint: false}, _meta: {ui: {resourceUri: uri}}},
    guard(async ({directory, ...options}) => {
      const data = store.open(store.tour(directory, tourDeck));
      const {text, ...summary} = data;
      return result({layout: 'split', format: 'slides', editor: 'visual', ...summary, ...options, tour: true}, {source: text});
    }));
  server.registerTool('matsugit_file', {title: 'Edit with matsugit', description: 'Open the host-selected Markdown or Org file in matsugit. Source writes are version-checked by the host.',
    inputSchema: OpenAIFileEntrypointInputSchema, annotations: readOnly,
    _meta: {ui: {resourceUri: uri, visibility: ['app']}, 'openai/ui': {entrypoints: [{type: 'file', extensions: ['.md', '.markdown', '.qmd', '.org']}]}}},
    async ({file}) => result({file}));
  server.registerTool('matsugit_open', {title: 'Open document in matsugit',
    description: 'Open a user-requested existing Markdown/Org file for editing and document/slides preview. Reads only the specified file. Never publishes.',
    inputSchema: z.object({path: z.string(), ...viewOptions}), annotations: readOnly, _meta: {ui: {resourceUri: uri}}},
    guard(async ({path: file, ...options}) => { const data = store.open(file); const {text, ...summary} = data; return result({...summary, ...options}, {source: text}); }));
  server.registerTool('matsugit_reconnect', {description:'Reconnect an existing panel to the same local document after a plugin restart. Read-only; does not open a second panel, save or publish.', ...appOnly,
    inputSchema:z.object({path:z.string()}), annotations:readOnly},
    guard(async ({path:file}) => { const {text, ...data} = store.open(file); return result(data); }));
  server.registerTool('matsugit_check', {title: 'Check slides',
    description: 'Check a Markdown/Org deck for slide-structure problems and report each in plain language with its slide and line. Use after editing a deck and whenever a user asks what is wrong or why a slide looks off. Read-only: no rendering, saving or publishing. Structure only; a visual look at the slides is still needed.',
    inputSchema: z.object({path: z.string().optional(), text: z.string().max(MAX_SOURCE).optional(), format: z.enum(['markdown', 'org']).optional()}),
    annotations: readOnly},
    guard(async ({path: file, text, format}) => {
      if ((file === undefined) === (text === undefined)) throw Error('Give either the path of a document or its text.');
      const target = file === undefined ? null : checkedPath(file);
      const source = target ? readSource(target) : checkedText(text);
      // Offsets and edit operations are for the editor; agents get the words.
      const findings = checkDeck(source, target ? target.toLowerCase().endsWith('.org') : format === 'org')
        .map(({from, fix, ...finding}) => ({...finding, ...(fix ? {suggestedFix: fix.label} : {})}));
      return result({...checkSummary(findings), findings});
    }));
  server.registerTool('matsugit_links', {title: 'Where is this deck shared',
    description: 'For a Markdown/Org deck shared from this computer with matsugit, return the links to its slides and reading document on the project site and to its source on GitLab/GitHub, plus the last known site build state. Use when the user asks where a deck is published or wants to open it. Read-only and local: no network, no login; the state is as of the last check.',
    inputSchema: z.object({path: z.string()}), annotations: readOnly},
    guard(async ({path: file}) => {
      const receipt = await store.links(file);
      const {links = {}} = receipt;
      return result({shared: receipt.stage !== 'local', links,
        state: ({published: 'live', building: 'building', failed: 'build failed', pushed: 'sent, site state unknown', local: 'not shared from this computer'})[receipt.stage] || receipt.stage,
        checked_at: receipt.checked_at || null, pushed_at: receipt.pushed_at || null});
    }));
  server.registerTool('matsugit_read', {description: 'Refresh the document already opened in this workspace.', ...appOnly,
    inputSchema: z.object({session: z.string()}), annotations: readOnly},
    guard(async ({session}) => { const {text, ...data} = store.source(session); return appResult(data, {source: text}); }));
  server.registerTool('matsugit_path', {description:'Read the real local path of the already-open document, if supplied by the host.', ...appOnly,
    inputSchema:z.object({session:z.string().optional()}),annotations:readOnly},
    guard(async ({session},context)=>result({path:store.owner(session,getResourcePath(context.mcpReq?._meta))})));
  server.registerTool('matsugit_themes', {description:'List installed theme names and the opened document\'s default. No render, file writes or publication.', ...appOnly,
    inputSchema:z.object({session:z.string().optional()}),annotations:readOnly},
    guard(async ({session},context)=>result(await store.themes(session,getResourcePath(context.mcpReq?._meta)))));
  server.registerTool('matsugit_save', {description: 'Save explicit workspace edits only if the opened file still matches the expected version. Never force overwrites.', ...appOnly,
    inputSchema: z.object({session: z.string(), text: z.string().max(MAX_SOURCE), etag: z.string().min(1), recreate: z.boolean().optional()}),
    annotations: {readOnlyHint: false, destructiveHint: true, openWorldHint: false}},
    guard(async ({session, text, etag, recreate}) => result(store.save(session, text, etag, {recreate}))));
  server.registerTool('matsugit_recovery_begin', {description: 'Prepare a private recovery copy for this viewer; does not save the document.', ...appOnly,
    inputSchema: z.object({...scope, name: z.string().max(512)}), annotations: {readOnlyHint: false, destructiveHint: false, openWorldHint: false}},
    guard(async (args, context) => {
      const data = recovery.begin({...args, owner: recoveryOwner(args, context)});
      return appResult({id: data.id}, {candidate: data.candidate});
    }));
  server.registerTool('matsugit_recovery_checkpoint', {description: 'Checkpoint workspace text and view settings in private local recovery storage. Never writes the original file or publishes.', ...appOnly,
    inputSchema: z.object({...scope, id: z.string(), generation: z.number().int().nonnegative(),
      text: z.string().max(MAX_SOURCE), base: z.string().max(MAX_SOURCE), view: z.record(z.string(), z.unknown())}),
    annotations: {readOnlyHint: false, destructiveHint: false, openWorldHint: false}},
    guard(async (args, context) => result(recovery.checkpoint(args.id, args.generation, args, recoveryOwner(args, context)))));
  server.registerTool('matsugit_recovery_list', {description: 'List local recovery copies in the workspace recovery picker.', ...appOnly,
    inputSchema: z.object(scope), annotations: readOnly},
    guard(async (args, context) => {
      const owner = recoveryOwner(args, context);
      return appResult({}, recovery.list(owner || (args.resourceUri ? 'resource:' + args.resourceUri : undefined)));
    }));
  server.registerTool('matsugit_recovery_restore', {description: 'Read the recovery copy explicitly selected in the picker. Does not save or overwrite the source.', ...appOnly,
    inputSchema: z.object({...scope, id: z.string()}), annotations: readOnly},
    guard(async (args, context) => {
      const record = recovery.read(args.id), owner = recoveryOwner(args, context);
      if ((owner && owner !== record.owner) || (!owner && args.resourceUri && record.identity !== 'resource:' + args.resourceUri)) throw Error('Recovery copy belongs to another document.');
      let data = {name: record.name, text: '', writable: false};
      if (record.owner && !args.resourceUri) {
        try {
          if (checkedPath(record.owner) !== record.owner) throw Error('Path changed');
          data = store.open(record.owner);
        } catch { data.missingSource = true; }
      }
      return appResult({}, {workspace: data, recovery: record});
    }));
  server.registerTool('matsugit_recovery_forget', {description: 'Delete only the recovery copy explicitly confirmed in the picker, never its source document.', ...appOnly,
    inputSchema: z.object({...scope, id: z.string(), token: z.string()}),
    annotations: {readOnlyHint: false, destructiveHint: true, openWorldHint: false}},
    guard(async (args, context) => {
      const record = recovery.read(args.id), owner = recoveryOwner(args, context);
      if ((owner && owner !== record.owner) || (!owner && args.resourceUri && record.identity !== 'resource:' + args.resourceUri)) throw Error('Recovery copy belongs to another document.');
      return result(recovery.forget(args.id, args.token));
    }));
  server.registerTool('matsugit_preview', {description: 'Render an unsaved snapshot locally with the existing matsugit engine. Creates temporary output only; does not save or publish.', ...appOnly,
    inputSchema: z.object({text: z.string().max(MAX_SOURCE), name: z.string().optional(), theme: z.string().optional(), session: z.string().optional(),
      format: z.enum(['document', 'slides']).optional(), base: z.string().optional()}), annotations: readOnly},
    guard(async (args, context) => result(store.start(args, getResourcePath(context.mcpReq?._meta)))));
  server.registerTool('matsugit_preview_status', {description: 'Read render progress and completed preview for the opened document.', ...appOnly,
    inputSchema: z.object({job: z.string(), session: z.string().optional()}), annotations: readOnly},
    guard(async ({job, session}, context) => result(store.status(job, session, getResourcePath(context.mcpReq?._meta)))));
  server.registerTool('matsugit_preview_cancel', {description: 'Cancel only this workspace preview job. Does not change or save the source.', ...appOnly,
    inputSchema: z.object({job: z.string(), session: z.string().optional()}),
    annotations: {readOnlyHint: false, destructiveHint: false, openWorldHint: false}},
    guard(async ({job, session}, context) => result(store.cancel(job, session, getResourcePath(context.mcpReq?._meta)))));
  server.registerTool('matsugit_preview_chunk', {description: 'Read a bounded part of a completed preview, only for this document.', ...appOnly,
    inputSchema: z.object({job: z.string(), format: z.enum(['document', 'slides']), offset: z.number().int().nonnegative(), session: z.string().optional()}), annotations: readOnly},
    guard(async ({job, format, offset, session}, context) => {
      const {chunk, ...data} = store.chunk(job, format, offset, session, getResourcePath(context.mcpReq?._meta));
      return appResult(data, {chunk});
    }));
  return server;
}, {onerror: error => console.error(error)});
process.once('SIGTERM', () => { store.close(); process.exit(0); });
process.once('SIGINT', () => { store.close(); process.exit(0); });
process.once('exit', () => { merges.close(); tables.close(); const idle = actions.close(); store.close(); if (idle) runtime.close(); });
