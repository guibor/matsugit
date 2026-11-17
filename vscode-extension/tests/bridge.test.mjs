import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../native.js', import.meta.url), 'utf8');

function bridge() {
  let receiver, value = 'original', external = false;
  const calls = [], errors = [];
  const parent = {postMessage(message) {
    calls.push(message);
    queueMicrotask(() => {
      let result;
      if (message.method === 'edit') {
        const applied = !external && message.params.base === value;
        if (applied) value = message.params.text;
        result = {source:value, dirty:true, applied};
      } else result = {source:value,dirty:true,etag:'vscode:1'};
      receiver({source:parent,data:{matsugitNative:true,id:message.id,result}});
    });
  }};
  const window = {addEventListener(name, callback) {receiver = callback;}};
  vm.runInNewContext(source, {window,parent,setTimeout,clearTimeout,Map,Promise,Error});
  const api = window.matsugitNativeDocument;
  api.attach({error: error => errors.push(error),refresh() {},reconcile() {}});
  api.bind(value);
  return {api,calls,errors,current:()=>value,external(text) {value=text;external=true;},accept() {external=false;}};
}
test('native bridge drains rapid typing into the accepted native buffer', async () => {
  const {api,current,errors} = bridge();
  api.edit('a'); api.edit('ab'); api.edit('abc');
  await api.flush();
  assert.equal(current(),'abc'); assert.deepEqual(errors,[]);
});
test('native bridge retains a rejected draft until explicit reconciliation', async () => {
  const {api,current,external,accept,calls} = bridge();
  external('agent'); api.edit('author');
  await assert.rejects(api.flush(),/Review|review/);
  assert.equal(current(),'agent');
  const count=calls.length;
  api.edit('author typing');
  assert.equal(calls.length,count);
  await api.read(); accept(); api.resume('combined'); await api.flush();
  assert.equal(current(),'combined');
});
test('reviewed incoming text, not the stale UI snapshot, is resumed', async () => {
  const {api,current,external,accept} = bridge();
  external('incoming'); await api.read(); accept(); api.resume('incoming');
  await api.flush(); assert.equal(current(),'incoming');
  api.edit('incoming plus author'); await api.flush();
  assert.equal(current(),'incoming plus author');
});
test('polling cannot authorize overwriting an unreviewed native change', async () => {
  const {api,current,external,accept} = bridge();
  external('agent'); await api.read(); accept();
  api.edit('stale author draft');
  await assert.rejects(api.flush(),/Review/);
  assert.equal(current(),'agent');
  api.resume('reviewed merge'); await api.flush();
  assert.equal(current(),'reviewed merge');
});
