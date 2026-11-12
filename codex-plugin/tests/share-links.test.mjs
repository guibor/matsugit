import {test} from 'node:test';
import assert from 'node:assert/strict';
import {publishedLinks} from '../src/share.mjs';

test('site links remain available without claiming that a pending or failed build is live', () => {
  for (const stage of ['local', 'pushed', 'building', 'failed', 'published']) {
    const result = publishedLinks({stage, provider: 'gitlab', links: {
      slides: 'http://pages.example.invalid/deck-slides.html',
      document: 'http://pages.example.invalid/deck.html',
      source: 'https://git.example.invalid/team/docs/-/blob/main/deck.md'}});
    assert.deepEqual(result.map(item => item.key), ['slides', 'document', 'source']);
    assert.match(result[0].detail, stage === 'published' ? /last verified/ : stage === 'failed' ? /previous version/ : /not verified/);
  }
});

test('links still reject credentials, script URLs and whitespace', () => {
  for (const url of ['javascript:alert(1)', 'http://user:secret@example.invalid', 'https://example.invalid/\n'])
    assert.deepEqual(publishedLinks({links: {slides: url}}), []);
});
