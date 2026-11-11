import {test} from 'node:test';
import assert from 'node:assert/strict';
import {sessionConnection} from '../src/session-connection.mjs';
const expired = () => Error('Workspace expired; reopen the document.');
const deferred = () => { let resolve; const promise = new Promise(r => resolve=r); return {promise, resolve}; };

test('concurrent and late expired requests reconnect once without replacing file versions', async () => {
  const state = {sequence:1, path:'/docs/a.md', session:'old', text:'draft', etag:'old-version'};
  const gate = deferred(); let opens=0, retries=0;
  const call = sessionConnection({current:() => ({...state}), bind:data => { state.session=data.session; },
    request:async (name, args) => {
      if (name==='matsugit_reconnect') { opens++; await gate.promise; return {session:'new',path:state.path}; }
      if (args.session==='old') throw expired();
      retries++; return args;
    }});
  const calls = [call('matsugit_read', {session:'old'}), call('matsugit_save', {session:'old',etag:'old-version',text:'draft'})];
  await new Promise(r=>setImmediate(r)); gate.resolve();
  const results = await Promise.all(calls);
  assert.equal(opens,1); assert.equal(retries,2);
  assert.equal(results[1].etag,'old-version'); assert.equal(state.text,'draft');
  assert.equal((await call('matsugit_read', {session:'old'})).session,'new');
  assert.equal(opens,1);
});

test('a reconnect completing after a document switch cannot bind or retry against that file', async () => {
  let state = {sequence:1,path:'/docs/a.md',session:'old'};
  const gate=deferred(); let binds=0, writes=0;
  const call=sessionConnection({current:()=>({...state}),bind:()=>binds++,request:async(name,args)=>{
    if(name==='matsugit_reconnect') { await gate.promise; return {session:'new',path:'/docs/a.md'}; }
    if(args.session==='old') throw expired();
    writes++;
  }});
  const attempt=call('matsugit_save',{session:'old',text:'A draft'});
  const rejected=assert.rejects(attempt,/document changed/);
  await new Promise(r=>setImmediate(r)); state={sequence:2,path:'/docs/b.md',session:'B'}; gate.resolve();
  await rejected; assert.equal(binds,0); assert.equal(writes,0);
});

test('transport failures and uncertain publish outcomes are never automatically retried', async () => {
  for(const message of ['Transport closed.','Timeout after publication','Recovery workspace expired; reopen recovery before continuing.']) {
    let requests=0;
    const call=sessionConnection({current:()=>({sequence:1,path:'/docs/a.md',session:'old'}),
      bind:()=>assert.fail('must not bind'),request:async()=>{requests++;throw Error(message);}});
    await assert.rejects(call('matsugit_action',{session:'old',action:'publish'}),e=>e.message===message);
    assert.equal(requests,1);
  }
});

test('a redirected path is not accepted as the same document', async () => {
  const call=sessionConnection({current:()=>({sequence:1,path:'/docs/a.md',session:'old'}),
    bind:()=>assert.fail('must not bind'),request:async name=>{
      if(name==='matsugit_reconnect')return {session:'new',path:'/docs/b.md'};
      throw expired();
    }});
  await assert.rejects(call('matsugit_read',{session:'old'}),/path changed/);
});
