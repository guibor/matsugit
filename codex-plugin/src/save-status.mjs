import {createElement, Check, Pencil, LoaderCircle, TriangleAlert, FileText} from 'lucide';

export function saveStatus(state, dirty, tablePending = false) {
  if (state.loading) return {kind:'busy', label:'Loading', detail:'Reading the document'};
  if (state.saving) return {kind:'busy', label:'Saving...', detail:'Waiting for the file write to finish'};
  if (state.merging) return {kind:'busy', label:'Merging...', detail:'The source file is not being written'};
  if (state.conflict) return {kind:'review', label:'Review changes', detail:'The file changed elsewhere. Your draft is retained; Save is blocked.'};
  if (state.saveError && dirty) return {kind:'error', label:'Not saved', detail:state.saveError};
  if (tablePending) return {kind:'dirty', label:'Table edits', detail:'Table edits have not been applied to the draft or saved to the file'};
  if (!state.writable || !state.etag) return {kind:'local', label:dirty ? 'Unsaved copy' : 'Local copy', detail:'No writable file connection; download the source to keep this copy'};
  if (dirty) return {kind:'dirty', label:'Unsaved', detail:state.lastSavedAt ? `Changes since the last save at ${new Date(state.lastSavedAt).toLocaleTimeString()}` : 'Edits are in this workspace, not saved to the source file'};
  return {kind:'saved', label:'Saved', detail:state.lastSavedAt ? `Saved to the source file at ${new Date(state.lastSavedAt).toLocaleTimeString()}` : 'This draft matches the last file version read'};
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
