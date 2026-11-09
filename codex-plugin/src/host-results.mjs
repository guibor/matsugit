// Some hosts forward structuredContent; others retain only the JSON text block.
export function hostResultData(response) {
  if (response?.isError) throw Error(response.content?.filter(item => item.type === 'text')
    .map(item => item.text).join('\n') || 'Operation failed.');
  let data = response?.structuredContent;
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    data = {};
    for (const item of response?.content || []) {
      if (item.type !== 'text') continue;
      try {
        const parsed = JSON.parse(item.text);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) { data = parsed; break; }
      } catch { /* Human-readable status is not a document payload. */ }
    }
  }
  return {...data, ...response?._meta};
}

export function sourceText(data) {
  const source = data.source ?? data.text;
  if (typeof source !== 'string') throw Error('The host did not return the document text. Your file was not changed; reload the plugin connection and reopen the document.');
  return source;
}
