import {McpServer} from '@modelcontextprotocol/server';
import {serveStdio} from '@modelcontextprotocol/server/stdio';
import {OpenAIExtensions} from '@openai/mcp-extensions/server';
import {getResourcePath, OpenAIFileEntrypointInputSchema} from '@openai/mcp-extensions';
import {z} from 'zod';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {WorkspaceStore, MAX_SOURCE} from './store.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const uri = 'ui://folioforge/workspace-v1';
const store = new WorkspaceStore(root);
const readOnly = {readOnlyHint: true, destructiveHint: false, openWorldHint: false};
const viewOptions = {layout: z.enum(['source', 'render', 'split']).optional(), format: z.enum(['document', 'slides']).optional()};
const appOnly = {_meta: {ui: {visibility: ['app']}}};
const result = (data, meta) => ({content: [{type: 'text', text: JSON.stringify(data)}], structuredContent: data, ...(meta ? {_meta: meta} : {})});
const guard = fn => async (...args) => {
  try { return await fn(...args); }
  catch (error) { return {isError: true, content: [{type: 'text', text: error.message}]}; }
};
serveStdio(() => {
  const server = new McpServer({name: 'folioforge', version: '0.2.0'});
  new OpenAIExtensions(server);
  server.registerResource('workspace', uri, {mimeType: 'text/html;profile=mcp-app'}, async () => ({contents: [{
    uri, mimeType: 'text/html;profile=mcp-app', text: fs.readFileSync(path.join(root, 'codex-plugin/bundle/app.html'), 'utf8'),
    _meta: {'openai/ui': {preferredDisplayMode: 'fullscreen', availableDisplayModes: ['fullscreen']},
      ui: {csp: {frameDomains: ['blob:'], resourceDomains: ['data:', 'blob:'], baseUriDomains: ['https://folioforge.invalid']}}},
  }]}));
  server.registerTool('folioforge_workspace', {title: 'Folioforge', description: 'Open an empty local Markdown workspace with document and slide previews. Does not publish.',
    inputSchema: z.object(viewOptions), annotations: readOnly,
    _meta: {ui: {resourceUri: uri}, 'openai/ui': {entrypoints: [{type: 'global'}]}}},
    async options => result({...options, name: 'Untitled.md', text: '---\ntitle: Untitled\nslide-layout: structured\n---\n\n# Section\n\n## Slide title\n### Main claim\n\n- Supporting evidence\n', writable: false}));
  server.registerTool('folioforge_file', {title: 'Edit with Folioforge', description: 'Open the host-selected Markdown or Org file in Folioforge. Source writes are version-checked by the host.',
    inputSchema: OpenAIFileEntrypointInputSchema, annotations: readOnly,
    _meta: {ui: {resourceUri: uri, visibility: ['app']}, 'openai/ui': {entrypoints: [{type: 'file', extensions: ['.md', '.markdown', '.qmd', '.org']}]}}},
    async ({file}) => result({file}));
  server.registerTool('folioforge_open', {title: 'Open document in Folioforge',
    description: 'Open a user-requested existing Markdown/Org file for editing and document/slides preview. Reads only the specified file. Never publishes.',
    inputSchema: z.object({path: z.string(), ...viewOptions}), annotations: readOnly, _meta: {ui: {resourceUri: uri}}},
    guard(async ({path: file, ...options}) => { const data = store.open(file); const {text, ...summary} = data; return result({...summary, ...options}, {source: text}); }));
  server.registerTool('folioforge_read', {description: 'Refresh the document already opened in this workspace.', ...appOnly,
    inputSchema: z.object({session: z.string()}), annotations: readOnly},
    guard(async ({session}) => { const {text, ...data} = store.source(session); return result(data, {source: text}); }));
  server.registerTool('folioforge_save', {description: 'Save explicit workspace edits only if the opened file still matches the expected version. Never force overwrites.', ...appOnly,
    inputSchema: z.object({session: z.string(), text: z.string().max(MAX_SOURCE), etag: z.string().min(1)}),
    annotations: {readOnlyHint: false, destructiveHint: true, openWorldHint: false}},
    guard(async ({session, text, etag}) => result(store.save(session, text, etag))));
  server.registerTool('folioforge_preview', {description: 'Render an unsaved snapshot locally with the existing Folioforge engine. Creates temporary output only; does not save or publish.', ...appOnly,
    inputSchema: z.object({text: z.string().max(MAX_SOURCE), name: z.string().optional(), theme: z.string().optional(), session: z.string().optional()}), annotations: readOnly},
    guard(async (args, context) => result(store.start(args, getResourcePath(context.mcpReq?._meta)))));
  server.registerTool('folioforge_preview_status', {description: 'Read render progress and completed preview for the opened document.', ...appOnly,
    inputSchema: z.object({job: z.string(), session: z.string().optional()}), annotations: readOnly},
    guard(async ({job, session}, context) => result(store.status(job, session, getResourcePath(context.mcpReq?._meta)))));
  server.registerTool('folioforge_preview_cancel', {description: 'Cancel only this workspace preview job. Does not change or save the source.', ...appOnly,
    inputSchema: z.object({job: z.string(), session: z.string().optional()}),
    annotations: {readOnlyHint: false, destructiveHint: false, openWorldHint: false}},
    guard(async ({job, session}, context) => result(store.cancel(job, session, getResourcePath(context.mcpReq?._meta)))));
  server.registerTool('folioforge_preview_chunk', {description: 'Read a bounded part of a completed preview, only for this document.', ...appOnly,
    inputSchema: z.object({job: z.string(), format: z.enum(['document', 'slides']), offset: z.number().int().nonnegative(), session: z.string().optional()}), annotations: readOnly},
    guard(async ({job, format, offset, session}, context) => {
      const {chunk, ...data} = store.chunk(job, format, offset, session, getResourcePath(context.mcpReq?._meta));
      return result(data, {chunk});
    }));
  return server;
}, {onerror: error => console.error(error)});
process.once('SIGTERM', () => { store.close(); process.exit(0); });
process.once('SIGINT', () => { store.close(); process.exit(0); });
process.once('exit', () => store.close());
