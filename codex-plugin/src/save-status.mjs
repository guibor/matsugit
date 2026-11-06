import {createElement, Check, Pencil, LoaderCircle, TriangleAlert, FileText} from 'lucide';

export function saveStatus(state, dirty, tablePending = false) {
  if (state.loading) return {kind:'busy', label:'Loading', detail:'Reading the document'};
  if (state.saving) return {kind:'busy', label:'Saving...', detail:'Waiting for the file write to finish'};
  if (state.merging) return {kind:'busy', label:'Merging...', detail:'The source file is not being written'};
  if (state.conflict) return {kind:'review', label:'Changed elsewhere', detail:'Your draft is retained. Save opens a comparison before any file write.'};
  if (state.saveError && dirty) return {kind:'error', label:'Not saved', detail:state.saveError};
  if (tablePending) return {kind:'dirty', label:'Table edits', detail:'Table edits have not been applied to the draft or saved to the file'};
  if (!state.writable || !state.etag) return {kind:'local', label:dirty ? 'Unsaved copy' : 'Local copy', detail:'No writable file connection; download the source to keep this copy'};
  if (dirty) return {kind:'dirty', label:'Unsaved draft', detail:state.lastSavedAt ? `Changes since the last save at ${new Date(state.lastSavedAt).toLocaleTimeString()}` : 'Edits are in this workspace, not saved to the source file'};
  return {kind:'saved', label:'Saved to file', detail:state.lastSavedAt ? `Saved to the source file at ${new Date(state.lastSavedAt).toLocaleTimeString()}` : 'This draft matches the last file version read'};
}

export function changeNotice(state, dirty) {
  if (state.conflict) return {kind:'review', title:'File changed elsewhere',
    detail:'Your draft is retained. No file has been overwritten.'};
  if (state.fileReceipt === 'merged') return {kind:'info', title:dirty ? 'Changes combined in your draft' : 'Draft matches the updated file',
    detail:dirty ? 'Your edits and the independent file edits are together. Not saved to the file yet.' : 'No file was written by the merge.'};
  if (state.fileReceipt === 'reviewed') return {kind:'info', title:dirty ? 'Reviewed draft ready' : 'Draft matches the reviewed file',
    detail:dirty ? 'Your review is applied to the draft. The file is unchanged until you save.' : 'No file was written by the review.'};
  if (state.fileReceipt === 'updated') return {kind:'info', title:'Loaded the updated file',
    detail:dirty ? 'You have new unsaved edits since that update.' : 'There were no local edits to replace.'};
  return null;
}

export function paintSaveStatus(element, value) {
  const key = `${value.kind}:${value.label}`;
  if (element.dataset.statusKey !== key) {
    const icon = {busy:LoaderCircle, review:TriangleAlert, error:TriangleAlert, dirty:Pencil, saved:Check, local:FileText}[value.kind];
    const label = element.ownerDocument.createElement('span'); label.textContent = value.label;
    const svg = createElement(icon); svg.setAttribute('aria-hidden', 'true');
    element.replaceChildren(svg, label); element.dataset.statusKey = key; element.dataset.kind = value.kind;
  }
  element.title = value.detail;
}
