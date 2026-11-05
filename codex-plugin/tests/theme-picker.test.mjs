import {test} from 'node:test';
import assert from 'node:assert/strict';
import {themeChoices, updateThemePicker} from '../src/theme-picker.mjs';

test('theme picker distinguishes configured default from explicit choices', () => {
  assert.deepEqual(themeChoices({default: 'alpha', themes: ['beta', 'alpha', 'default', 'beta']}), [
    {value: '', label: 'alpha (default)'}, {value: 'alpha', label: 'alpha'},
    {value: 'beta', label: 'beta'}, {value: 'default', label: 'default'}]);
  assert.equal(themeChoices({}, 'old-theme').at(-1).value, 'old-theme');
});

test('refreshing installed themes preserves selection and uses text, not HTML', () => {
  const select = {value: 'restored', ownerDocument: {createElement: () => ({})},
    replaceChildren(...children) { this.children = children; this.value = ''; }};
  updateThemePicker(select, {default: 'alpha', themes: ['alpha', '<inert>']});
  assert.equal(select.value, 'restored');
  assert(select.children.some(option => option.value === 'restored'));
  assert(select.children.some(option => option.textContent === '<inert>'));
  updateThemePicker(select, {}, '');
  assert.deepEqual(select.children, [{value: '', textContent: 'Project default'}]);
});
