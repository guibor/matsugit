import {search, SearchQuery, setSearchQuery, getSearchQuery, findNext, findPrevious,
  replaceNext, replaceAll, selectMatches, closeSearchPanel} from '@codemirror/search';
import {runScopeHandlers} from '@codemirror/view';
import {createElement, Search, ChevronUp, ChevronDown, SlidersHorizontal, X} from 'lucide';

function panel(view) {
  const dom = document.createElement('div'), row = document.createElement('div'), options = document.createElement('div');
  dom.className = 'ff-find'; row.className = 'ff-find-row'; options.className = 'ff-find-options';
  options.hidden = true;
  const input = label => Object.assign(document.createElement('input'), {placeholder:label, 'ariaLabel':label});
  const term = input('Find in draft'), replacement = input('Replace with');
  term.setAttribute('main-field','true');
  const count = document.createElement('output');
  function button(label, action, icon) {
    const el = document.createElement('button');
    el.type = 'button'; el.title = label; el.setAttribute('aria-label',label);
    if (icon) el.append(createElement(icon)); else el.textContent = label;
    el.onclick = action; return el;
  }
  const previous = button('Previous match',()=>findPrevious(view),ChevronUp);
  const next = button('Next match',()=>findNext(view),ChevronDown);
  const settings = button('Find options',()=>{options.hidden = !options.hidden; settings.setAttribute('aria-expanded',String(!options.hidden));},SlidersHorizontal);
  settings.setAttribute('aria-expanded','false');
  row.append(createElement(Search),term,count,previous,next,settings,button('Close Find',()=>closeSearchPanel(view),X));
  const flags = {};
  for (const [key,label] of [['caseSensitive','Match case'],['wholeWord','Whole word'],['regexp','Regex']]) {
    const wrap = document.createElement('label'), box = document.createElement('input');
    box.type = 'checkbox'; box.onchange = commit; flags[key] = box; wrap.append(box,label); options.append(wrap);
  }
  options.append(button('Select all matches',()=>selectMatches(view)));
  const replaceRow = document.createElement('div');
  replaceRow.className = 'ff-find-row';
  replaceRow.append(replacement,button('Replace',()=>replaceNext(view)),button('Replace all',()=>replaceAll(view)));
  options.append(replaceRow); dom.append(row,options);
  function commit() {
    view.dispatch({effects:setSearchQuery.of(new SearchQuery({search:term.value,replace:replacement.value,
      ...Object.fromEntries(Object.entries(flags).map(([k,box])=>[k,box.checked]))}))});
  }
  term.oninput = replacement.oninput = commit;
  dom.onkeydown = event => {
    if (runScopeHandlers(view,event,'search-panel')) event.preventDefault();
    else if (event.key === 'Enter' && [term,replacement].includes(event.target)) {
      event.preventDefault();
      (event.target === replacement ? replaceNext : event.shiftKey ? findPrevious : findNext)(view);
    }
  };
  let lastDoc, lastQuery, matches;
  function refresh() {
    const state = view.state, q = getSearchQuery(state);
    replaceRow.hidden = state.readOnly;
    if (!q.eq(lastQuery || q) || !lastQuery) {
      term.value = q.search; replacement.value = q.replace;
      for (const [key,box] of Object.entries(flags)) box.checked = q[key];
    }
    if (lastDoc !== state.doc || lastQuery !== q) {
      matches = [];
      if (q.valid) for (const hit of q.getCursor(state)) {
        matches.push(hit); if (matches.length > 1000) break;
      }
      lastDoc = state.doc; lastQuery = q;
    }
    const sel = state.selection.main, pos = matches.findIndex(m=>m.from === sel.from && m.to === sel.to);
    const total = matches.length > 1000 ? '1000+' : String(matches.length);
    count.textContent = !q.search ? '' : !q.valid ? 'Invalid query' : !matches.length ? 'No matches'
      : pos < 0 ? total + (matches.length === 1 ? ' match' : ' matches') : (pos+1)+' of '+total;
    previous.disabled = next.disabled = !matches.length;
  }
  refresh();
  return {dom,top:true,mount(){term.focus(); term.select();}, update:refresh};
}
export const draftSearch = search({top:true,createPanel:panel});
