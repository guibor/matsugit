import {test} from 'node:test';
import assert from 'node:assert/strict';
import {openWorkspaceLink} from '../src/open-link.mjs';

const href = 'http://pages.example.invalid/docs/slides.html';
function click() { return {defaultPrevented:false, preventDefault(){this.defaultPrevented = true;}}; }
test('native navigation keeps the original click and the exact URL', async () => {
  const e = click();
  await openWorkspaceLink(e, {href}, {getHostCapabilities:()=>({})}, null, assert.fail);
  assert.equal(e.defaultPrevented, false);
});
test('ChatGPT opener is called once during the click, without URL rewriting', async () => {
  const e = click(), calls = [];
  const pending = openWorkspaceLink(e, {href}, {}, {openExternal:args=>calls.push(args)}, assert.fail);
  assert.deepEqual(calls, [{href, redirectUrl:false}]);
  assert.ok(e.defaultPrevented);
  await pending;
});
test('MCP rejection and explicit failure both give feedback without retrying a popup', async () => {
  for (const refuse of [()=>Promise.reject(Error('denied')), ()=>({isError:true})]) {
    const e = click(), errors = [];
    await openWorkspaceLink(e, {href}, {getHostCapabilities:()=>({openLinks:{}}),
      openLink:({url})=>{assert.equal(url, href);return refuse();}}, null, msg=>errors.push(msg));
    assert.ok(e.defaultPrevented);
    assert.match(errors[0], /Copy the link/);
  }
});
