(() => {
  const vscode = acquireVsCodeApi();
  const frame = document.getElementById('workspace');
  window.addEventListener('message', event => {
    if (event.source === frame.contentWindow) {
      const message = event.data;
      if (message?.jsonrpc === '2.0' || message?.matsugitNative === true) vscode.postMessage(message);
    } else if (event.origin === location.origin && event.origin !== 'null' && event.data?.matsugitHost === true) {
      frame.contentWindow.postMessage(event.data.message, '*');
    }
  });
  vscode.postMessage({matsugitHostReady: true});
})();
