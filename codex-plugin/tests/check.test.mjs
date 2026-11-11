import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync, spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {checkDeck, applyFix, checkSummary, rendererFinding} from '../src/check.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const python = process.env.MATSUGIT_PYTHON || 'python3';
const H = '---\ntitle: T\nslide-layout: structured\n---\n\n';
const columns = parts => ':::: columns\n' + parts.map(part => `#### ${part}\ntext\n`).join('\n') + '::::\n';
const indentedClaims = [0, 1, 2, 3].flatMap(spaces => ['\n', '\r\n'].map(newline =>
  (H + '## A\n\n' + ' '.repeat(spaces) + '### Claim\n\nBody.\n').replaceAll('\n', newline)));

// `renderer` records what the real renderer does with the same text: 'fails'
// (the preview stops) or 'accepts' (it renders, but not as the author meant).
const cases = [
  {code: 'block-open', renderer: 'fails', fixed: true,
    source: H + '## A\n\n:::: columns\n#### L\nx\n\n#### R\ny\n\n## B\n\ntext\n'},
  {code: 'block-stray', renderer: 'accepts', fixed: true, source: H + '## A\n\ntext\n\n:::\n'},
  {code: 'block-glued', renderer: 'accepts', fixed: true, source: H + '## A\n\nSome text\n::: takeaway\nDone.\n:::\n'},
  {code: 'block-glued', renderer: 'accepts', fixed: true, source: H + '## A\n\nSome text\n> [!TAKEAWAY]\n> Done.\n'},
  {code: 'heading-space', renderer: 'accepts', fixed: true, source: H + '##Title\n\ntext\n'},
  {code: 'break-glued', renderer: 'accepts', fixed: true, source: H + '## A\n\nFirst group.\n---\n\nSecond.\n'},
  {code: 'parts-count', renderer: 'fails', source: H + '## A\n\n' + columns(['A', 'B', 'C', 'D'])},
  {code: 'parts-count', renderer: 'fails', source: H + '## A\n\n' + columns(['A'])},
  {code: 'parts-count', renderer: 'fails',
    source: H + '## A\n\n:::: metrics\n' + [1, 2, 3, 4, 5].map(n => `#### M${n}\n**${n}**\n`).join('\n') + '::::\n'},
  {code: 'parts-count', renderer: 'fails',
    source: H + '## A\n\n::::: columns\n:::: column\na\n::::\n:::: column\nb\n::::\n:::: column\nc\n::::\n:::: column\nd\n::::\n:::::\n'},
  {code: 'parts-empty', renderer: 'fails', source: H + '## A\n\n:::: columns\n#### L\n\n#### R\ny\n::::\n'},
  {code: 'parts-start', renderer: 'fails', fixed: true, source: H + '## A\n\n:::: columns\nintro\n\n#### L\nx\n::::\n'},
  {code: 'parts-mixed', renderer: 'fails', source: H + '## A\n\n::::: columns\n#### L\nx\n\n:::: column\ny\n::::\n:::::\n'},
  {code: 'layout-off', renderer: 'accepts', fixed: true, source: '## A\n\n' + columns(['L', 'R'])},
  {code: 'layout-off', renderer: 'accepts', fixed: true, source: '---\ntitle: T\n---\n\n## A\n\n:::: rows\n#### L\nx\n\n#### R\ny\n::::\n'},
  {code: 'chart-unit', renderer: 'fails', source: H + '## A\n\n::: {.chart type="bar"}\n| a | b |\n|---|---|\n| x | 1 |\n:::\n'},
  {code: 'chart-type', renderer: 'fails', source: H + '## A\n\n::: {.chart type="pie" unit="x"}\n| a | b |\n|---|---|\n| x | 1 |\n:::\n'},
  {code: 'chart-table', renderer: 'fails', source: H + '## A\n\n::: {.chart type="bar" unit="x"}\nNo table here.\n:::\n'},
  {code: 'claim-extra', renderer: 'fails', fixed: true, source: H + '## A\n### one\n### two\n\ntext\n'},
  {code: 'claim-extra', renderer: 'fails', fixed: true, source: H + '## A\n\ntext\n\n### late\n\nmore\n'},
  {code: 'claim-extra', renderer: 'fails', source: H + '## A\n### one\n\n::: claim\ntwo\n:::\n\ntext\n'},
  {code: 'claim-untitled', renderer: 'fails', source: H + '# S\n### c\n\ntext\n'},
  {code: 'heading-inside', renderer: 'fails', fixed: true, source: H + '## A\n\n:::: columns\n#### L\nx\n\n### R\ny\n::::\n'},
  {code: 'takeaway-extra', renderer: 'fails', source: H + '## A\n\ntext\n\n::: takeaway\na\n:::\n\n> [!TAKEAWAY]\n> b\n'},
  {code: 'setting-quoted', renderer: 'fails', fixed: true,
    source: '---\ntitle: T\nslide-layout: structured\nslide-section-dividers: "false"\n---\n\n## A\n\ntext\n'},
  {code: 'setting-layout', renderer: 'fails', fixed: true, source: '---\ntitle: T\nslide-layout: structurd\n---\n\n## A\n\ntext\n'},
  {code: 'settings-open', renderer: 'accepts', source: '---\ntitle: T\nslide-layout: structured\n\n## A\n\ntext\n'},
  {code: 'block-name', tip: true, renderer: 'accepts', fixed: true, source: H + '## A\n\ntext\n\n::: takaway\nDone.\n:::\n'},
  {code: 'slide-empty', tip: true, renderer: 'accepts', source: H + '## A\n\n## B\n\ntext\n'},
  {code: 'title-long', tip: true, renderer: 'accepts', source: H + '## ' + 'Long title '.repeat(10) + '\n\ntext\n'},
  {code: 'slide-dense', tip: true, renderer: 'accepts', source: H + '## A\n\n' + 'word '.repeat(160) + '\n'},
  {code: 'table-dense', tip: true, renderer: 'accepts',
    source: H + '## A\n\n| a | b |\n|---|---|\n' + '| x | 1 |\n'.repeat(11)},
];

test('every finding names the slide and line, and safe fixes clear what they describe', () => {
  for (const item of cases) {
    const findings = checkDeck(item.source);
    const finding = findings.find(found => found.code === item.code);
    assert.ok(finding, `${item.code}: not reported for ${JSON.stringify(item.source)}`);
    assert.equal(finding.severity, item.tip ? 'tip' : 'problem', item.code);
    assert.ok(finding.message && Number.isInteger(finding.line) && finding.line > 0, item.code);
    assert.equal(item.source.split('\n')[finding.line - 1], item.source.slice(finding.from).split('\n')[0], item.code);
    assert.equal(!!finding.fix, !!item.fixed, `${item.code}: fix presence`);
    if (finding.fix) {
      const repaired = applyFix(item.source, finding.fix);
      assert.deepEqual(checkDeck(repaired).filter(found => found.severity === 'problem'), [], `${item.code}: ${JSON.stringify(repaired)}`);
      assert.ok(!checkDeck(repaired).some(found => found.code === item.code), item.code);
    }
  }
  const located = checkDeck(H + '# S\n\n## One\n\ntext\n\n## Two\n\n' + columns(['A', 'B', 'C', 'D']))[0];
  assert.deepEqual([located.slide, located.title, located.line], [2, 'Two', 14]);
});

test('problems sort before tips and summarize in plain words', () => {
  const findings = checkDeck(H + '## A\n\n## B\n\n' + columns(['A']));
  assert.deepEqual(findings.map(found => found.severity), ['problem', 'tip']);
  assert.equal(checkSummary(findings).label, '1 to fix');
  assert.equal(checkSummary(findings.slice(1)).label, '1 tip');
  assert.equal(checkSummary([]).label, 'No problems');
});

test('claim indentation does not count as body content or change fix boundaries', () => {
  for (const source of indentedClaims) {
    assert.deepEqual(checkDeck(source), [], JSON.stringify(source));
    const newline = source.includes('\r\n') ? '\r\n' : '\n';
    const heading = source.split(newline).find(line => line.trimStart().startsWith('### '));
    for (const invalid of [source.replace(heading, 'Earlier body.' + newline + newline + heading),
      source + newline + heading + newline + 'More evidence.' + newline]) {
      const findings = checkDeck(invalid).filter(item => item.code === 'claim-extra');
      assert.equal(findings.length, 1, JSON.stringify(invalid));
      const fix = findings[0].fix;
      assert.equal(invalid.slice(fix.changes[0].from, fix.changes[0].to), '###');
      const repaired = applyFix(invalid, fix);
      assert.ok(repaired.includes(heading.replace('###', '####')));
      assert.deepEqual(checkDeck(repaired), [], JSON.stringify(repaired));
    }
  }
  assert.deepEqual(checkDeck(H + '## A\n\n  ::: claim\nClaim.\n  :::\n\nBody.\n'), []);
});

test('valid syntax, examples and hidden or literal content raise no findings', () => {
  const clean = [
    H + '## A\n### claim\n\n:::: columns 2:1\n#### L\nx\n\n#### R\ny\n:::\n\n::: takeaway\nDone.\n:::\n',
    H + '## A\n\n```markdown\n::: takaway\n:::\n:::\n### x\n### y\n```\n\ntext\n',
    H + '## A\n\ntext\n\n:::: {.agent-comment #review-1 status="open"}\nRequest:\n### a heading\n::: takaway\n:::\n\nResponse:\nPending.\n::::\n',
    H + '## A\n### one\n\nfirst\n\n---\n\n### two\n\nsecond\n\n::: takeaway\na\n:::\n',
    '## Plain Quarto deck\n\n::: {.columns}\n::: {.column width="50%"}\na\n:::\n::: {.column width="50%"}\nb\n:::\n:::\n',
    '---\ntitle: T\nslide-layout: structured\nslide-empty-slides: true\n---\n\n## Only a title {.statement}\n',
    H.replace(/\n/g, '\r\n') + '## A\r\n\r\n' + columns(['L', 'R']).replace(/\n/g, '\r\n'),
  ];
  for (const source of clean) assert.deepEqual(checkDeck(source), [], JSON.stringify(source));
  for (const file of ['examples/charts-takeaways.md', 'examples/decision-demo.md', 'examples/diagrams.md', 'examples/quotes.md',
    'skills/matsugit/assets/slide-types.md', 'skills/matsugit/assets/relationships.md', 'codex-plugin/tests/product-review.md',
    'codex-plugin/tests/authoring-sugar.md', 'tests/fixtures/rows.md', 'tests/fixtures/render-parity.md'])
    assert.deepEqual(checkDeck(fs.readFileSync(path.join(root, file), 'utf8')), [], file);
});

test('every insertable recipe passes the check it will be judged by', () => {
  const templates = JSON.parse(execFileSync(python, ['-c',
    'import json; from matsugit.authoring import editor_templates; print(json.dumps(editor_templates()))'], {cwd: root, encoding: 'utf8'}));
  for (const [name, recipe] of Object.entries(templates)) {
    const slide = recipe.kind === 'Slide' || ['slide', 'section'].includes(name);
    // A claim belongs directly under its title; everything else follows body text.
    const findings = checkDeck(H + (slide ? '' : name === 'claim' ? '## Slide\n' : '## Slide\n\nBody.\n\n') + recipe.markdown);
    assert.deepEqual(findings.filter(found => found.severity === 'problem'), [], name);
  }
});

test('Org sources report an unfinished block and nothing speculative', () => {
  const findings = checkDeck('* S\n** A\n#+begin_columns\ntext\n', true);
  assert.deepEqual(findings.map(found => [found.code, found.line]), [['block-open', 3]]);
  assert.deepEqual(checkDeck('* S\n** A\n#+begin_takeaway\nDone.\n#+end_takeaway\n', true), []);
});

test('renderer messages are restated in slide words without losing the original', () => {
  const known = rendererFinding('Use two or three columns');
  assert.match(known.message, /2 or 3 parts/);
  assert.match(known.how, /Use two or three columns/);
  assert.equal(rendererFinding('Something new').message, 'Something new');
});

test('the real renderer agrees with each problem: it fails or misrenders, and fixes render', {timeout: 120000}, t => {
  const script = `
import json, sys, shutil
from matsugit.source import read
from matsugit.lint import inspect
from matsugit.converter import converter
command = converter()
out = []
for text in json.load(sys.stdin):
    try:
        inspect(read(text, 'markdown', command)); out.append('accepts')
    except ValueError as exc:
        out.append('fails')
print(json.dumps(out))`;
  const repaired = cases.filter(item => item.fixed && !item.tip).map(item =>
    applyFix(item.source, checkDeck(item.source).find(found => found.code === item.code).fix));
  const accepted = [...repaired, ...indentedClaims];
  const run = spawnSync(python, ['-c', script], {cwd: root, encoding: 'utf8', input: JSON.stringify([...cases.map(item => item.source), ...accepted])});
  if (run.status !== 0) { t.skip('Renderer converter unavailable: ' + run.stderr.trim().split('\n').at(-1)); return; }
  const results = JSON.parse(run.stdout);
  cases.forEach((item, index) => assert.equal(results[index], item.renderer, `${item.code}: ${JSON.stringify(item.source)}`));
  accepted.forEach((source, index) => assert.equal(results[cases.length + index], 'accepts', JSON.stringify(source)));
});

test('a slide titled "continued" becomes a break that carries the title and claim over', () => {
  for (const suffix of [' (continued)', ' (cont.)', ' - continued', ', continued', " (cont'd)", ' Continued']) {
    const source = H + '## Rollout plan\n### Validate each stage\n\nFirst part.\n\n## Rollout plan' + suffix + '\n### Validate each stage\n\nSecond part.\n';
    const finding = checkDeck(source).find(item => item.code === 'title-continued');
    assert.ok(finding, suffix);
    assert.equal(finding.severity, 'tip');
    const fixed = applyFix(source, finding.fix);
    assert.equal(fixed, H + '## Rollout plan\n### Validate each stage\n\nFirst part.\n\n---\n\nSecond part.\n', suffix);
    assert.deepEqual(checkDeck(fixed), []);
  }
  // Without a repeated claim only the heading is replaced; unrelated titles are left alone.
  const plain = H + '## Plan\n\nA.\n\n## Plan (continued)\n\nB.\n';
  assert.equal(applyFix(plain, checkDeck(plain).find(item => item.code === 'title-continued').fix), H + '## Plan\n\nA.\n\n---\n\nB.\n');
  for (const source of [H + '## Plan\n\nA.\n\n## Continued growth\n\nB.\n', H + '## Plan\n\nA.\n\n## Other (continued)\n\nB.\n',
    H + '# One\n\n## Plan\n\nA.\n\n# Two\n\n## Plan (continued)\n\nB.\n'])
    assert.ok(!checkDeck(source).some(item => item.code === 'title-continued'), source);
});
