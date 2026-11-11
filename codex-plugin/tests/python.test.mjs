import test from 'node:test';
import assert from 'node:assert/strict';
import {pythonExecutable, pythonEnvironment} from '../src/python.mjs';

test('Windows uses native Python; existing Unix defaults and overrides stay unchanged', () => {
  assert.equal(pythonExecutable({}, 'win32'), 'python');
  for (const platform of ['linux', 'darwin']) assert.equal(pythonExecutable({}, platform), 'python3');
  for (const platform of ['linux', 'darwin', 'win32']) {
    assert.equal(pythonExecutable({MATSUGIT_PYTHON:'custom path/python', FOLIOFORGE_PYTHON:'legacy'}, platform), 'custom path/python');
    assert.equal(pythonExecutable({FOLIOFORGE_PYTHON:'legacy'}, platform), 'legacy');
  }
});

test('Windows child processes get UTF-8 without changing the parent or Unix environment', () => {
  const env = {PATH: 'existing', PYTHONUTF8: '0'};
  assert.deepEqual(pythonEnvironment(env, 'win32'), {PATH:'existing', PYTHONUTF8:'1'});
  assert.equal(env.PYTHONUTF8, '0');
  for (const platform of ['linux', 'darwin']) assert.equal(pythonEnvironment(env, platform), env);
});
