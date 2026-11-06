import {test} from 'node:test';
import assert from 'node:assert/strict';
import {fileDownloads, exportMime} from '../src/download.mjs';

const failure = code => Object.assign(Error('Host response'),{code});
const noBrowser = () => { throw Error('Must not bypass the host'); };

test('host download preserves filename, MIME and complete binary payload across base64 chunks', async () => {
  const bytes = Uint8Array.from({length:150001},(_,i)=>i%256);
  let request;
  const send = fileDownloads({downloadFile:async params => { request=params; return {}; }},noBrowser);
  assert.match(await send({name:'/private/draft \u05e9\u05dc\u05d5\u05dd.pptx',blob:new Blob([bytes],{type:exportMime.pptx})}),/Sent to host downloads/);
  const item = request.contents[0].resource;
  assert.equal(item.uri,'file:///draft%20%D7%A9%D7%9C%D7%95%D7%9D.pptx');
  assert.equal(item.mimeType,exportMime.pptx);
  assert.deepEqual(new Uint8Array(Buffer.from(item.blob,'base64')),bytes);
});

test('older Codex Blob payload is used only after parameter rejection, then remembered', async () => {
  const calls=[], blob=new Blob(['a\n\u05e9\u05dc\u05d5\u05dd'],{type:'text/plain;charset=utf-8'});
  const send=fileDownloads({downloadFile:async params => {
    calls.push(params); if (params.contents) throw failure(-32602); return {};
  }},noBrowser);
  await send({name:'draft.md',blob});
  assert.equal(calls.length,2); assert.deepEqual(calls[1],{name:'draft.md',blob});
  await send({name:'again.md',blob});
  assert.equal(calls.length,3); assert.equal(calls[2].blob,blob);
});

test('host cancellation, errors and ambiguous timeouts never retry or fall back', async () => {
  for (const reply of [{isError:true},failure(-32000),failure(-32001),Error('Transport closed')]) {
    let calls=0;
    const send=fileDownloads({downloadFile:async()=>{calls++; if(reply instanceof Error)throw reply; return reply;}},noBrowser);
    await assert.rejects(send({name:'x.pdf',blob:new Blob(['data'])}));
    assert.equal(calls,1);
  }
});

test('legacy host refusal is retained and cannot become a browser download', async () => {
  let calls=0;
  const send=fileDownloads({downloadFile:async params=>{calls++; if(params.contents)throw failure(-32602);return {isError:true};}},noBrowser);
  await assert.rejects(send({name:'x.pdf',blob:new Blob(['data'])}),/cancelled or declined/);
  assert.equal(calls,2);
});

test('missing host method falls back without claiming receipt; subsequent retry is a direct browser gesture', async () => {
  let calls=0; const files=[];
  const send=fileDownloads({downloadFile:async()=>{calls++;throw failure(-32601);}},file=>files.push(file));
  const file={name:'../source.md',blob:new Blob(['draft'])};
  const message=await send(file);
  assert.match(message,/Receipt cannot be confirmed/);
  assert.equal(files[0].name,'source.md');
  const second=send(file);
  assert.equal(files.length,2); // synchronous, before the click's activation expires
  await second; assert.equal(calls,1);
  await fileDownloads(null,file=>files.push(file))({name:'..',blob:file.blob});
  assert.equal(files[2].name,'download');
});
