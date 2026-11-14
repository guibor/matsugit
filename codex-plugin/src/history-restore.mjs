import {completeStoryModel} from './story-model.mjs';

export function historySlides(text, org = false) {
  try { return completeStoryModel(text,org).slides; }
  catch (error) { throw Error(error.message + ' Document restore remains available.'); }
}

export function restoreSlide(previous, current, source, destination, mode, org = false) {
  const old = historySlides(previous,org), slides = historySlides(current,org);
  if (!Number.isInteger(source) || !old[source] || !['replace','after','end'].includes(mode)) throw Error('Select an earlier slide and a destination.');
  if (mode !== 'end' && (!Number.isInteger(destination) || !slides[destination])) throw Error('Select the current slide explicitly; titles are not stable identifiers.');
  const original = old[source], target = slides[destination];
  const content = previous.slice(original.from,original.end).replace(/\s*$/, '\n\n');
  const from = mode === 'replace' ? target.from : mode === 'after' ? target.end : current.length;
  const to = mode === 'replace' ? target.end : from;
  const prefix = mode !== 'replace' && from && !current.slice(0,from).endsWith('\n\n') ? '\n\n' : '';
  const result = current.slice(0,from) + prefix + content + current.slice(to);
  if (new TextEncoder().encode(result).length > 2*1024*1024) throw Error('Restored draft exceeds 2 MiB. Nothing replaced.');
  if (historySlides(result,org).length !== slides.length + (mode === 'replace' ? 0 : 1)) throw Error('The selected slide cannot be restored without changing surrounding boundaries.');
  return result;
}
