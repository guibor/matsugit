export const exportMime = {
  pptx:'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  pdf:'application/pdf', html:'text/html', zip:'application/zip',
};

async function resource(file) {
  const bytes = new Uint8Array(await file.blob.arrayBuffer());
  const parts = [];
  // Multiples of three allow independent base64 chunks without interior padding.
  for (let i=0;i<bytes.length;i+=49152)
    parts.push(btoa(String.fromCharCode(...bytes.subarray(i,i+49152))));
  return {contents:[{type:'resource',resource:{uri:`file:///${encodeURIComponent(file.name)}`,
    mimeType:file.blob.type || 'application/octet-stream',blob:parts.join('')}}]};
}

export function browserDownload({name,blob}) {
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href = url; link.download = name; document.body.append(link);
  try { link.click(); }
  finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url),60000); }
}

export function fileDownloads(app, fallback = browserDownload) {
  let transport = typeof app?.downloadFile === 'function' ? 'standard' : 'browser';
  return async ({name,blob}) => {
    name = String(name || 'download').split(/[\\/]/).at(-1).replace(/[\x00-\x1f\x7f]/g,'_');
    if (!name || /^\.+$/.test(name)) name = 'download';
    const file = {name,blob};
    if (transport !== 'browser') {
      let result;
      try {
        try {
          result = await app.downloadFile(transport === 'legacy' ? file : await resource(file), {timeout:120000});
        } catch (error) {
          // Older Codex hosts accept a structured-cloned Blob, not MCP contents.
          // Only a parameter rejection is safe to retry: no download was started.
          if (transport !== 'standard' || error.code !== -32602) throw error;
          transport = 'legacy';
          result = await app.downloadFile(file, {timeout:120000});
        }
        if (result?.isError) throw Error('Download cancelled or declined by the host. The prepared file is retained; you can try again.');
        return `Sent to host downloads: ${name}`;
      } catch (error) {
        // A refusal, timeout or closed connection must never trigger another download.
        if (error.code !== -32601) throw error;
        transport = 'browser';
      }
    }
    fallback(file);
    return `Browser download requested: ${name}. Receipt cannot be confirmed. If no file appears, retry Download; this host may block browser downloads.`;
  };
}
