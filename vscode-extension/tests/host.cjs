const vscode = require('vscode');
const fs = require('node:fs/promises');
const path = require('node:path');

// Test-only bridge into the real extension host; never included in the VSIX.
exports.run = async () => {
  const root = process.env.MATSUGIT_VSCODE_TEST;
  if (!root) throw Error('MATSUGIT_VSCODE_TEST must name an isolated fixture directory');
  const uri = vscode.Uri.file(path.join(root, 'deck.md'));
  const doc = await vscode.workspace.openTextDocument(uri);
  await vscode.commands.executeCommand('workbench.action.closeSidebar');
  await vscode.commands.executeCommand('workbench.action.closeAuxiliaryBar');
  await vscode.commands.executeCommand('matsugit.open', uri);
  await fs.writeFile(path.join(root, 'ready'), 'ready');
  let previous = 0;
  for (;;) {
    await new Promise(resolve => setTimeout(resolve, 100));
    let command;
    try { command = JSON.parse(await fs.readFile(path.join(root, 'command.json'), 'utf8')); }
    catch { continue; }
    if (command.id === previous) continue;
    previous = command.id;
    let error;
    try {
      if (command.action === 'finish') return;
      if (command.action === 'replace') {
        const before = doc.getText(), at = before.indexOf(command.before);
        if (at < 0) throw Error('Fixture text not found');
        const edit = new vscode.WorkspaceEdit();
        edit.replace(uri, new vscode.Range(doc.positionAt(at), doc.positionAt(at + command.before.length)), command.after);
        await vscode.workspace.applyEdit(edit);
      }
      if (command.action === 'save') await doc.save();
      if (command.action === 'undo') await vscode.commands.executeCommand('undo');
    } catch (e) { error = e.message; }
    await fs.writeFile(path.join(root, 'response.json'), JSON.stringify({id: command.id, source: doc.getText(), dirty: doc.isDirty, error}));
  }
};
