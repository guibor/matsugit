import {test} from 'node:test';
import assert from 'node:assert/strict';
import {layoutEditAllowed,slideSpacing} from '../src/layout-edit.mjs';
const source = '## Slide {#stable}\n\n:::: columns 1:1\n\n#### Left\n\nWords\n\n#### Right\n\nOther\n\n::::\n\nAfter';
const at = text => source.indexOf(text);
test('visual editing protects paired fences and region prefixes, not prose', () => {
  for (const change of [
    {from:at('::::'),to:at('::::')+1,insert:''},
    {from:at('Other'),to:source.lastIndexOf('::::')+2,insert:''},
    {from:at('#### Left'),to:at('#### Left')+1,insert:''},
    {from:at('::::')-1,to:at('::::'),insert:''},
    {from:at('::::'),to:at('::::'),insert:'x'},
    {from:at('Words'),to:at('Words'),insert:':::\n\n'},
  ]) assert.equal(layoutEditAllowed(source,[change]),false,JSON.stringify(change));
  for (const change of [
    {from:at('Words'),to:at('Words')+5,insert:'Revised words'},
    {from:at('Left'),to:at('Left')+4,insert:'New label'},
    {from:at('::::'),to:source.lastIndexOf('::::')+4,insert:''},
    {from:0,to:source.length,insert:'## Replacement\n'},
  ]) assert.equal(layoutEditAllowed(source,[change]),true,JSON.stringify(change));
});
test('new unbalanced layouts are refused, complete pasted layouts allowed', () => {
  assert.equal(layoutEditAllowed('Text',[{from:4,to:4,insert:'\n\n::: columns\n'}]),false);
  assert.equal(layoutEditAllowed('Text',[{from:4,to:4,insert:'\n\n::: columns\n\nHi\n\n:::\n'}]),true);
  assert.equal(layoutEditAllowed('```md\n::: columns\n```',[{from:9,to:10,insert:''}]),true);
});
test('spacing changes only the current slide attributes and preserves IDs and quoted values', () => {
  assert.equal(slideSpacing(source,at('Words')).active,false);
  const change=slideSpacing(source,at('Words'),true);
  assert.equal(change.insert,'## Slide {#stable .tight}');
  assert.equal(slideSpacing(change.insert,2,false).insert,'## Slide {#stable}');
  assert.equal(slideSpacing('## Title {#id data-note="keep  spaces" .dense}',8,true).insert,
    '## Title {#id data-note="keep  spaces" .dense .tight}');
  assert.equal(slideSpacing('## One\n\nText\n\n## Two\n\nBody',26,true).insert,'## Two {.tight}');
  assert.equal(slideSpacing('# Section\n',5,true),null);
});
