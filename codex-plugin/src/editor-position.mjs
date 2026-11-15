import {EditorView} from '@codemirror/view';

// A document offset survives decoration changes; a pixel scroll offset does not.
export function preservePassage(view, change) {
  const box = view.scrollDOM.getBoundingClientRect();
  const caret = view.coordsAtPos(view.state.selection.main.head);
  const visibleCaret = caret && caret.top >= box.top && caret.bottom <= box.bottom;
  const pos = visibleCaret ? view.state.selection.main.head
    : view.posAtCoords({x:box.left + Math.min(100,box.width / 2),y:box.top + 8}, false);
  const before = pos === null ? null : view.coordsAtPos(pos);
  const offset = before ? before.top - box.top : 8;
  change();
  if (pos === null) return;
  view.dispatch({effects:EditorView.scrollIntoView(pos,{y:'start',yMargin:offset})});
}
