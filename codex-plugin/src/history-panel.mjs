import {createElement, History, X} from 'lucide';
import {historySlides, restoreSlide} from './history-restore.mjs';
import {documentState} from './document-state.mjs';
import {slideDiff, wordChanges} from './slide-diff.mjs';

const reasons = {opened:'Opened file', 'before-save':'Before save', saved:'Saved file', external:'Changed outside matsugit',
  'before-restore':'Before restore', 'agent-edit':'Scoped agent-edit tool', draft:'Workspace draft'};

export function historyPanel({call, scope, snapshot, apply, recover, review, publication}) {
  const $ = id => document.getElementById(id), dialog = $('history-dialog');
  let generation = 0, selected, current, owner, openedSequence, busy = false;
  const sameDocument = () => {
    if (snapshot().sequence !== openedSequence) throw Error('The document changed. Close Changes and reopen it for the current file.');
  };
  $('history-open').append(createElement(History), document.createTextNode('Changes'));
  $('history-close').append(createElement(X));
  const controls = () => {
    for (const id of ['history-restore-document','history-restore-slide']) $(id).disabled = busy || !selected;
    $('history-restore-slide').disabled ||= !$('history-slide').options.length;
    $('history-close').disabled = busy;
  };
  $('history-close').onclick = () => dialog.close();
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('close', () => { if (!dialog.open) { generation++; selected = null; } });
  $('history-recover').onclick = () => { dialog.close(); recover(); };
  $('history-review').onclick = () => { dialog.close(); review(); };
  const options = (id, slides) => {
    $(id).replaceChildren(...slides.map((slide,index) => new Option(`${index+1}. ${slide.label}`,String(index))));
  };
  async function select(item, request) {
    if (busy) return;
    selected = null; controls(); $('history-status').textContent = 'Reading checkpoint...';
    try {
      sameDocument();
      const value = await call('matsugit_history_read',{...owner,id:item.id});
      if (request !== generation) return;
      sameDocument();
      current = snapshot(); selected = value;
      $('history-before').value = value.text; $('history-after').value = current.text;
      $('history-preview').hidden = false;
      const differences = slideDiff(value.text,current.text,current.org);
      $('history-slide-changes').replaceChildren(...differences.map(change => {
        const row = document.createElement('li'), details = document.createElement('details'), summary = document.createElement('summary');
        summary.textContent = `${change.kind}: ${change.title}`; details.append(summary);
        details.addEventListener('toggle',() => {
          if (!details.open || details.children.length > 1) return;
          const pre = document.createElement('pre');
          for (const part of wordChanges(change.before,change.after,current.org)) {
            if ('text' in part) pre.append(document.createTextNode(part.text));
            else for (const [tag,text] of [['del',part.before],['ins',part.after]]) {
              const mark = document.createElement(tag); mark.textContent = text; pre.append(mark);
            }
          }
          details.append(pre);
        });
        row.append(details); return row;
      }));
      $('history-status').textContent = reasons[value.reason] || value.reason;
      try { options('history-slide',historySlides(value.text,current.org)); options('history-destination',historySlides(current.text,current.org)); }
      catch (error) { options('history-slide',[]); $('history-status').textContent = error.message; }
      controls();
    } catch (error) { if (request === generation) $('history-status').textContent = error.message; }
  }
  async function restore(slide) {
    if (!selected || busy) return;
    busy = true; controls(); $('history-status').textContent = 'Preserving the current draft...';
    try {
      const value = slide ? restoreSlide(selected.text,current.text,Number($('history-slide').value),
        Number($('history-destination').value),$('history-placement').value,current.org) : selected.text;
      await apply(value,current);
      dialog.close();
    } catch (error) { $('history-status').textContent = error.message; }
    finally { busy = false; controls(); }
  }
  $('history-restore-document').onclick = () => restore(false);
  $('history-restore-slide').onclick = () => restore(true);
  $('history-placement').onchange = () => { $('history-destination').disabled = $('history-placement').value === 'end'; };
  return {async open() {
    if (dialog.open) return;
    const request = ++generation;
    selected = null; current = snapshot(); owner = scope(); openedSequence = current.sequence;
    $('history-preview').hidden = true; $('history-items').replaceChildren();
    $('history-status').textContent = 'Reading local history...';
    $('history-review').hidden = !current.external;
    controls(); dialog.showModal();
    const paint = git => {
      const facts = documentState({...current,receipt:publication()?.receipt(),fileDigest:publication()?.digest(),git});
      $('history-now').replaceChildren(...Object.values(facts).map(fact => {
      const row = document.createElement('p'), label = document.createElement('strong'); label.textContent = fact.label;
      row.append(label, ' ', fact.detail, fact.at ? ` (${fact.at})` : '',
        fact.matchesFile === false ? ' The saved file has newer or different text.' : '');
      return row;
      }));
    };
    paint();
    try {
      const data = await call('matsugit_history_list',owner);
      if (request !== generation) return;
      sameDocument();
      paint(data.git);
      for (const item of data.items) {
        const button = document.createElement('button'); button.type = 'button';
        button.textContent = `${new Date(item.created*1000).toLocaleString()} - ${reasons[item.reason] || item.reason}${item.author ? ' by '+item.author+' (commit author)' : ''}`;
        button.onclick = () => select(item,++generation);
        $('history-items').append(button);
      }
      $('history-status').textContent = (data.items.length ? `${data.items.length} local versions` : 'No checkpoints yet for this file.') + (data.gitUnavailable ? ' Git history unavailable.' : '');
    } catch (error) { if (request === generation) $('history-status').textContent = error.message; }
  }};
}
