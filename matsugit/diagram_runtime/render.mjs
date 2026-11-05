// D2's own parser/layout engine; only the supplied virtual file is accessible.
import {pathToFileURL} from 'node:url';
const {D2} = await import(pathToFileURL(process.argv[2] + '/node_modules/@d2lang/d2/dist/node-esm/index.js'));
let input = '';
for await (const chunk of process.stdin) {
  input += chunk;
  if (input.length > 200000) throw Error('Diagram input exceeds limit');
}
const payload = JSON.parse(input);
const engine = new D2();
try {
  const result = await engine.compile({fs: {'diagram.d2': payload.code}, inputPath: 'diagram.d2',
    options: {layout: payload.layout, themeID: 0, pad: 24, sketch: false}});
  const diagram = result.diagram;
  if (['layers', 'scenarios', 'steps'].some(key => diagram[key]?.length)) {
    throw Error('Use one D2 board per block; layers, scenarios and steps are not supported');
  }
  // Never fetch icons or make authored links active in exported diagrams.
  function check(value) {
    if (!value || typeof value !== 'object') return;
    for (const [key, child] of Object.entries(value)) {
      if (/^(icon|link)$/i.test(key) && child) throw Error('D2 icons and links are not supported; use self-contained text and shapes');
      check(child);
    }
  }
  check(diagram);
  const svg = await engine.render(diagram, {...result.renderOptions, target: '',
    animateInterval: 0, salt: payload.salt, pad: 24, center: false, sketch: false});
  process.stdout.write(svg);
} catch (error) {
  console.error(error?.message || String(error));
  process.exitCode = 1;
} finally {
  await engine.dispose();
}
