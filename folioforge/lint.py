"""Conservative authoring checks; layout warnings are not a substitute for review."""
import json
import os
from pathlib import Path
from .core import run
from .layout import plain, classes, slides, metadata
from .components import prepare
from .charts import dataset


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def inspect(ast):
    findings = []
    def add(code, title, message):
        findings.append(dict(code=code, slide=title, message=message))
    ast['meta'] = metadata(ast.get('meta', {}))
    # Validate components before measuring the final slide structure.
    prepared = slides(prepare(ast))
    groups, title, blocks = [], 'Opening', []
    for block in prepared['blocks']:
        if block.get('t') == 'Header' and block['c'][0] == 2:
            if blocks:
                groups.append((title, blocks))
            title, blocks = plain(block['c'][2]), []
        else:
            blocks.append(block)
    if blocks:
        groups.append((title, blocks))
    for title, blocks in groups:
        # Speaker notes should not count against slide density.
        def visible(n):
            if isinstance(n, list):
                return [visible(x) for x in n]
            if isinstance(n, dict):
                if 'notes' in classes(n):
                    return {}
                return {k:visible(v) for k,v in n.items()}
            return n
        nodes = list(walk(visible(blocks)))
        words = len(plain(visible(blocks)).split())
        if len(title) > 95:
            add('long-title', title, 'Title exceeds 95 characters; move detail into the smaller claim.')
        if words > 150:
            add('dense-slide', title, f'{words} words; consider rows, a second slide or presenter notes.')
        for node in nodes:
            if 'chart' in classes(node):
                dataset(node)
                if not any('source' in classes(n) or 'ff-source' in classes(n) for n in nodes):
                    add('chart-source', title, 'State the source and period of chart data.')
            if node.get('t') == 'Table':
                _, _, specs, _, bodies, _ = node['c']
                rows = sum(len(b[2])+len(b[3]) for b in bodies)
                if rows > 10 or len(specs) > 6:
                    add('dense-table', title, f'Table has {rows} rows and {len(specs)} columns; inspect projected readability.')
    return findings


def check(source, quarto):
    source = Path(source)
    fmt = 'org' if source.suffix == '.org' else 'markdown'
    ast = json.loads(run([quarto, 'pandoc', '-f', fmt, '-t', 'json'], text=source.read_text(encoding='utf-8')))
    return inspect(ast)


def rendered(directory):
    """Optional local browser pass. Never allow network requests from a deck."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError('Visual lint requires folioforge[lint] and playwright install chromium') from exc
    path = Path(directory).resolve()/'slides.html'
    if not path.is_file():
        raise ValueError('Visual lint needs an existing rendered slides.html')
    findings=[]
    with sync_playwright() as p:
        kwargs={'headless':True}
        if os.environ.get('FOLIOFORGE_CHROMIUM'):
            kwargs['executable_path']=os.environ['FOLIOFORGE_CHROMIUM']
        browser=p.chromium.launch(**kwargs)
        try:
            page=browser.new_page(viewport={'width':1440,'height':900})
            page.route('http://**',lambda r:r.abort())
            page.route('https://**',lambda r:r.abort())
            page.goto(path.as_uri())
            page.wait_for_function('window.Reveal?.isReady()',timeout=30000)
            count=page.evaluate('Reveal.getSlides().length')
            for i in range(count):
                page.evaluate('i=>{const s=Reveal.getSlides()[i];const n=Reveal.getIndices(s);Reveal.slide(n.h,n.v)}',i)
                page.wait_for_timeout(300)
                result=page.evaluate('''i=>{
                  const s=Reveal.getSlides()[i],r=s.getBoundingClientRect();
                  const parts=[...s.querySelectorAll(':scope>h2,:scope>.ff-claim,:scope>.ff-body,:scope>.ff-takeaway')].filter(e=>e.getBoundingClientRect().height);
                  return {title:s.querySelector('h1,h2')?.textContent||s.id,
                    overflow:s.scrollHeight>s.clientHeight+2||s.scrollWidth>s.clientWidth+2,
                    overlap:parts.some((e,j)=>j&&e.getBoundingClientRect().top<parts[j-1].getBoundingClientRect().bottom-1),
                    broken:[...s.querySelectorAll('img')].some(e=>!e.complete||!e.naturalWidth)};
                }''',i)
                for code in ('overflow','overlap','broken'):
                    if result[code]:
                        findings.append(dict(code=code,slide=result['title'],message='Rendered '+code+' detected. Inspect the slide; do not hide overflowing content.'))
        finally:
            browser.close()
    return findings
