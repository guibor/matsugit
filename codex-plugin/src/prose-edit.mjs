import {syntaxTree} from '@codemirror/language';
import {isolateHistory} from '@codemirror/commands';

export function headingText(line) {
  const prefix = /^ {0,3}#{1,6}[ \t]/.exec(line.text);
  if (!prefix) return null;
  const suffix = /[ \t](?:\{[#.][^{}\n]*\}(?:[ \t]+#+)?|#+)[ \t]*$/.exec(line.text);
  const from = line.from + prefix[0].length;
  return {from, to:suffix ? Math.max(from,line.from + suffix.index) : line.to};
}

export function editableHeading(state, line) {
  const title=headingText(line);
  if (!title) return null;
  const mark=syntaxTree(state).resolveInner(line.from+line.text.indexOf('#'),1);
  return mark.name==='HeaderMark' && /^ATXHeading/.test(mark.parent?.name) ? title : null;
}

export function formatProse(view, mark) {
  const {state} = view, range = state.selection.main;
  if (state.readOnly || state.selection.ranges.length !== 1) return false;
  let {from,to} = range;
  const line = state.doc.lineAt(from);
  if (to > line.to || /^\s*(?:[:|]|---|\+\+\+)/.test(line.text)) return false;
  if (state.doc.line(1).text.trim() === '---') {
    for (let i=2;i<=state.doc.lines;i++) {
      if (i > line.number) return false;
      if (/^(---|\.\.\.)\s*$/.test(state.doc.line(i).text)) {
        if (i === line.number) return false;
        break;
      }
    }
  }
  if (from === to) {
    const word = state.wordAt(from);
    if (word) {from=word.from; to=word.to;}
  }
  let value = state.sliceDoc(from,to);
  if (value) {
    if (!value.trim()) return false;
    from += value.length-value.trimStart().length; to -= value.length-value.trimEnd().length;
    value = state.sliceDoc(from,to);
  }
  const tree = syntaxTree(state), node = tree.resolveInner(from,1);
  if (!value && line.text.trim() && !/^(Paragraph|ATXHeading[1-6]|SetextHeading[12]|Emphasis|StrongEmphasis)$/.test(node.name)) return false;
  for (let p=node;p;p=p.parent) {
    if (/Code|HTML|Table|Link|Image|Autolink/.test(p.name)) return false;
    if (/Heading/.test(p.name)) {
      const title = headingText(line);
      if (title && (from<title.from || to>title.to)) return false;
    }
  }
  if (value && (!/^(Paragraph|ATXHeading[1-6]|SetextHeading[12]|Emphasis|StrongEmphasis)$/.test(node.name) ||
      tree.resolveInner(to,-1).from !== node.from || /[[\]*_{}<>\\|\x60]/.test(value))) return false;
  const wanted = mark==='**'?'StrongEmphasis':'Emphasis';
  let innerFrom=from, innerTo=to;
  for (let p=node;p && /^(StrongEmphasis|Emphasis)$/.test(p.name);p=p.parent) {
    const first=p.firstChild,last=p.lastChild;
    if (p.name===wanted) {
      if (first.to!==innerFrom || last.from!==innerTo) return false;
      const shift=first.to-first.from;
      view.dispatch({changes:[{from:first.from,to:first.to},{from:last.from,to:last.to}],
        selection:{anchor:from-shift,head:to-shift},userEvent:'input.format',annotations:isolateHistory.of('full')});
      return true;
    }
    if (first.to===innerFrom && last.from===innerTo) {innerFrom=p.from;innerTo=p.to;}
  }
  const label = value || (mark==='**'?'bold text':'italic text');
  const anchor = from + mark.length;
  view.dispatch({changes:{from,to,insert:mark+label+mark},
    selection:{anchor,head:anchor+label.length},userEvent:'input.format',annotations:isolateHistory.of('full')});
  return true;
}
