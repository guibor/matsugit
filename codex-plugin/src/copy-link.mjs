// A modal makes the rest of the document inert, so copy from inside it.
export async function copyLink(text, root) {
  const doc = root.ownerDocument, focus = doc.activeElement, selection = doc.getSelection();
  const ranges = selection ? Array.from({length: selection.rangeCount}, (_, i) => selection.getRangeAt(i).cloneRange()) : [];
  const inputSelection = typeof focus?.selectionStart === 'number' ? [focus.selectionStart, focus.selectionEnd, focus.selectionDirection] : null;
  const input = doc.createElement('textarea');
  input.value = text; input.readOnly = true;
  input.style.cssText = 'position:fixed;opacity:0;width:1px;height:1px;pointer-events:none';
  root.append(input);
  let copied = false;
  try { input.focus({preventScroll: true}); input.select(); copied = doc.execCommand('copy'); }
  catch { /* The host may block this user-gesture copy path too. */ }
  finally {
    input.remove();
    if (focus?.isConnected) focus.focus({preventScroll: true});
    if (inputSelection) focus.setSelectionRange(...inputSelection);
    if (selection) { selection.removeAllRanges(); for (const range of ranges) selection.addRange(range); }
  }
  if (copied) return true;
  let timer;
  try {
    await Promise.race([
      doc.defaultView.navigator.clipboard.writeText(text),
      new Promise((_, reject) => { timer = setTimeout(() => reject(Error('Clipboard unavailable')), 2000); }),
    ]);
    return true;
  } catch { return false; }
  finally { clearTimeout(timer); }
}
