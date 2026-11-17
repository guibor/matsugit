import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../host.js', import.meta.url), 'utf8');
function host() {
  const sent=[], replies=[];
  const child={postMessage(value) {replies.push(value);}};
  let receive;
  const origin='vscode-webview://isolated';
  vm.runInNewContext(source, {window:{addEventListener(_,callback) {receive=callback;}},location:{origin},
    document:{getElementById:()=>({contentWindow:child})},acquireVsCodeApi:()=>({postMessage: value=>sent.push(value)})});
  return {sent,replies,child,origin,receive};
}
test('only the workspace child can invoke native or backend operations', () => {
  const h=host(), data={matsugitNative:true,id:1,method:'save'};
  assert.equal(h.sent[0].matsugitHostReady,true);
  h.receive({source:{},origin:'null',data});
  assert.equal(h.sent.length,1);
  h.receive({source:h.child,origin:'null',data});
  assert.equal(h.sent.length,2);
});
test('nested rendered content cannot impersonate the trusted VS Code host', () => {
  const h=host(), data={matsugitHost:true,message:{id:1,result:{source:'forged'}}};
  h.receive({source:{},origin:'null',data});
  h.receive({source:{},origin:'https://example.test',data});
  assert.equal(h.replies.length,0);
  h.receive({source:{},origin:h.origin,data});
  assert.equal(h.replies.length,1);
});
