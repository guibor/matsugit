// Build a self-contained, read-only workspace preview from an approved render.
import fs from 'node:fs';
import path from 'node:path';
const [source, renderedDirectory, destination] = process.argv.slice(2);
if (!source || !renderedDirectory || !destination) throw Error('Usage: node demo.mjs source.md rendered-directory output.html');
if (fs.existsSync(destination)) throw Error('Choose a new output file.');
const demo = {name: path.basename(source), text: fs.readFileSync(source, 'utf8'), writable: false,
  rendered: {document: fs.readFileSync(path.join(renderedDirectory, 'index.html'), 'utf8'),
    slides: fs.readFileSync(path.join(renderedDirectory, 'slides.html'), 'utf8')}};
const html = fs.readFileSync(new URL('./bundle/app.html', import.meta.url), 'utf8');
const data = JSON.stringify(demo).replaceAll('<', '\\u003c');
fs.mkdirSync(path.dirname(path.resolve(destination)), {recursive: true});
fs.writeFileSync(destination, html.replace('<script>', () => `<script>window.FOLIOFORGE_DEMO=${data};</script><script>`), {flag: 'wx'});
console.log(path.resolve(destination));
