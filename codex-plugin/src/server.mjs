import {McpServer} from '@modelcontextprotocol/server';
import {serveStdio} from '@modelcontextprotocol/server/stdio';
import {OpenAIExtensions} from '@openai/mcp-extensions/server';
import {getResourcePath, OpenAIFileEntrypointInputSchema} from '@openai/mcp-extensions';
import {z} from 'zod';
import {WorkspaceStore, MAX_SOURCE, checkedPath} from './store.mjs';
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
const merges = new MergeService();
const recoveryOwner = (args, context) => args.session || args.resourceUri
  ? store.recoveryOwner(args.session, getResourcePath(context.mcpReq?._meta)) : null;
const scope = {session: z.string().optional(), resourceUri: z.string().max(4096).optional()};
const readOnly = {readOnlyHint: true, destructiveHint: false, openWorldHint: false};
const viewOptions = {layout: z.enum(['source', 'render', 'split', 'story']).optional(), format: z.enum(['document', 'slides']).optional()};
const appOnly = {_meta: {ui: {visibility: ['app']}}};
const result = (data, meta) => ({content: [{type: 'text', text: JSON.stringify(data)}], structuredContent: data, ...(meta ? {_meta: meta} : {})});
const guard = fn => async (...args) => {
  try { return await fn(...args); }
  catch (error) { return {isError: true, content: [{type: 'text', text: error.message}]}; }
};
serveStdio(() => {
  const server = new McpServer({name: 'matsugit', version: '0.24.0'});
  server.registerTool('matsugit_merge', {description:'Compute a local three-way merge of workspace text. Never saves, publishes or executes document content.', ...appOnly,
    inputSchema:z.object({base:z.string().max(MAX_SOURCE), local:z.string().max(MAX_SOURCE), incoming:z.string().max(MAX_SOURCE)}), annotations:readOnly},
    guard(async args => result({computed:true}, {merge:await merges.plan(args)})));
  new OpenAIExtensions(server);
  server.registerTool('matsugit_table', {description:'Convert or validate a selected table locally. Does not save or publish.', ...appOnly,
    inputSchema:z.object({operation:z.enum(['open','check','serialize']), source:z.string().max(1024*1024),
      html:z.string().max(1024*1024).optional(), format:z.enum(['markdown','org']).optional()}), annotations:readOnly},
    guard(async args => result({converted:true}, await tables.run(args))));
  server.registerTool('matsugit_action', {description:'Explicit workspace export, target preview or confirmed publication. Publishing commits/pushes and may trigger existing CI.', ...appOnly,
    inputSchema:z.object({action:z.enum(['options','export','plan','publish','repositories','connect-repository','sync-plan','sync','exchange-plan','exchange','publication-status']), session:z.string().optional(), check:z.boolean().optional(),
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
    guard(async ({job,session,offset},context) => {const {chunk,...data}=actions.chunk(job,offset,session,getResourcePath(context.mcpReq?._meta)); return result(data,{chunk});}));
  server.registerResource('workspace', uri, {mimeType: 'text/html;profile=mcp-app'}, async () => ({contents: [{
    uri, mimeType: 'text/html;profile=mcp-app', text: runtime.app,
    _meta: {'openai/ui': {preferredDisplayMode: 'fullscreen', availableDisplayModes: ['fullscreen']},
      ui: {csp: {frameDomains: ['blob:'], resourceDomains: ['data:', 'blob:'], baseUriDomains: ['https://matsugit.invalid']}}},
  }]}));
  server.registerTool('matsugit_workspace', {title: 'matsugit', description: 'Open an empty local Markdown workspace with document and slide previews. Does not publish.',
    inputSchema: z.object(viewOptions), annotations: readOnly,
    _meta: {ui: {resourceUri: uri}, 'openai/ui': {entrypoints: [{type: 'global'}]}}},
    async options => result({...options, name: 'Untitled.md', text: '---\ntitle: Untitled\nslide-layout: structured\n---\n\n# Section\n\n## Slide title\n### Main claim\n\n- Supporting evidence\n', writable: false}));
  server.registerTool('matsugit_file', {title: 'Edit with matsugit', description: 'Open the host-selected Markdown or Org file in matsugit. Source writes are version-checked by the host.',
    inputSchema: OpenAIFileEntrypointInputSchema, annotations: readOnly,
    _meta: {ui: {resourceUri: uri, visibility: ['app']}, 'openai/ui': {entrypoints: [{type: 'file', extensions: ['.md', '.markdown', '.qmd', '.org']}]}}},
    async ({file}) => result({file}));
  server.registerTool('matsugit_open', {title: 'Open document in matsugit',
    description: 'Open a user-requested existing Markdown/Org file for editing and document/slides preview. Reads only the specified file. Never publishes.',
    inputSchema: z.object({path: z.string(), ...viewOptions}), annotations: readOnly, _meta: {ui: {resourceUri: uri}}},
    guard(async ({path: file, ...options}) => { const data = store.open(file); const {text, ...summary} = data; return result({...summary, ...options}, {source: text}); }));
  server.registerTool('matsugit_read', {description: 'Refresh the document already opened in this workspace.', ...appOnly,
    inputSchema: z.object({session: z.string()}), annotations: readOnly},
    guard(async ({session}) => { const {text, ...data} = store.source(session); return result(data, {source: text}); }));
  server.registerTool('matsugit_path', {description:'Read the real local path of the already-open document, if supplied by the host.', ...appOnly,
    inputSchema:z.object({session:z.string().optional()}),annotations:readOnly},
    guard(async ({session},context)=>result({path:store.owner(session,getResourcePath(context.mcpReq?._meta))})));
  server.registerTool('matsugit_themes', {description:'List installed theme names and the opened document\'s default. No render, file writes or publication.', ...appOnly,
    inputSchema:z.object({session:z.string().optional()}),annotations:readOnly},
    guard(async ({session},context)=>result(await store.themes(session,getResourcePath(context.mcpReq?._meta)))));
  server.registerTool('matsugit_save', {description: 'Save explicit workspace edits only if the opened file still matches the expected version. Never force overwrites.', ...appOnly,
    inputSchema: z.object({session: z.string(), text: z.string().max(MAX_SOURCE), etag: z.string().min(1)}),
    annotations: {readOnlyHint: false, destructiveHint: true, openWorldHint: false}},
    guard(async ({session, text, etag}) => result(store.save(session, text, etag))));
  server.registerTool('matsugit_recovery_begin', {description: 'Prepare a private recovery copy for this viewer; does not save the document.', ...appOnly,
    inputSchema: z.object({...scope, name: z.string().max(512)}), annotations: {readOnlyHint: false, destructiveHint: false, openWorldHint: false}},
    guard(async (args, context) => {
      const data = recovery.begin({...args, owner: recoveryOwner(args, context)});
      return result({id: data.id}, {candidate: data.candidate});
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
      return result({}, recovery.list(owner || (args.resourceUri ? 'resource:' + args.resourceUri : undefined)));
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
      return result({}, {workspace: data, recovery: record});
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
      return result(data, {chunk});
    }));
  return server;
}, {onerror: error => console.error(error)});
process.once('SIGTERM', () => { store.close(); process.exit(0); });
process.once('SIGINT', () => { store.close(); process.exit(0); });
process.once('exit', () => { merges.close(); tables.close(); const idle = actions.close(); store.close(); if (idle) runtime.close(); });
