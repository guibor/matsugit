import {checkDeck, checkSummary} from './check.mjs';
import {storyModel, titleRange, moveStory, adjacentMove, insertStory, insertClaim, moveDestinations} from './story-model.mjs';

// Emacs uses Unicode characters, while browser editors use UTF-16 offsets.
export function storyRequest(request) {
  const {source, org = false, action = 'model'} = request;
  if (typeof source !== 'string' || Buffer.byteLength(source) > 2 * 1024 * 1024 || source.includes('\0')) throw Error('Invalid or oversized source');
  // The plain-language slide check, for the command line and editors without the workspace.
  if (action === 'check') {
    const findings = checkDeck(source, org).map(({from, fix, ...finding}) => ({...finding, ...(fix ? {suggestedFix: fix.label} : {})}));
    return {...checkSummary(findings), findings};
  }
  const utf = [0], chars = new Uint32Array(source.length + 1);
  let at = 0, count = 0;
  for (const char of source) { at += char.length; utf.push(at); count++; chars[at] = count; }
  const position = value => {
    if (!Number.isSafeInteger(value) || value < 0 || value >= utf.length) throw Error('Invalid source position');
    return utf[value];
  };
  const model = storyModel(source, org);
  const field = node => ({from:chars[node.from], to:chars[node.to], end:chars[node.end], kind:node.kind, label:node.label});
  const serialize = () => ({nodes:model.nodes.filter(n => n.kind !== 'claim').map(node => ({
    ...field(node), parent:node.parent ? chars[node.parent.from] : null, number:node.number || null,
    title:titleRange(source,node,org).text, empty:!!node.empty, continuations:node.continuations,
    claims:(node.claims || []).map(field), takeaways:(node.takeaways || []).map(field),
  })), sections:model.sections.length, slides:model.slides.length, unfinished:model.unfinished.length});
  if (action === 'model') return serialize();
  const from = position(request.from ?? 0);
  if (action === 'destinations') return {destinations:moveDestinations(model, from, request.query || '').map(item=>({...item,from:chars[item.from]}))};
  let change;
  const node = model.nodes.find(n=>n.from===from);
  if (action === 'move') change = moveStory(source,from,position(request.target),request.placement,org);
  else if (action === 'adjacent') {
    if (![-1,1].includes(request.direction)) throw Error('Invalid move direction');
    change = adjacentMove(source,from,request.direction,org);
  } else if (action === 'insert') change = insertStory(source,from,request.kind,org,{title:request.title,claim:request.claim});
  else if (action === 'claim') {
    if (!node || node.kind !== 'slide' || node.claims.length) throw Error('Choose a slide without a claim');
    change = insertClaim(source,node,org);
  } else if (action === 'edit') {
    const candidates = [...model.nodes, ...model.slides.flatMap(n=>[...n.claims.filter(c=>c.block),...n.takeaways])];
    const item = candidates.find(n=>n.from===from && (!request.kind || n.kind===request.kind));
    if (!item) throw Error('This story item changed; refresh before editing');
    if (typeof request.text !== 'string' || !request.text.trim() || /[\r\n\0]/.test(request.text)) throw Error('Enter one nonempty line');
    const range = titleRange(source,item,org);
    change = {changes:{from:range.from,to:range.to,insert:request.text},anchor:item.from};
  } else throw Error('Unknown Story operation');
  if (!change) return {change:null};
  return {change:{from:chars[change.changes.from],to:chars[change.changes.to ?? change.changes.from],insert:change.changes.insert},
    // The new anchor may be past the old document length after insertion.
    anchor:[...((source.slice(0,change.changes.from)+change.changes.insert+source.slice(change.changes.to ?? change.changes.from)).slice(0,change.anchor))].length};
}
