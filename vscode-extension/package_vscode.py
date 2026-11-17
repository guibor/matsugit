#!/usr/bin/env python3
"""Build a local VSIX from reviewed files. No npm or dependency downloads."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def code_command(executable=None):
    executable = executable or shutil.which('code')
    if not executable:
        candidates = [Path('/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code')]
        if os.name == 'nt':
            candidates = [Path(base) / suffix for base, suffix in (
                (os.environ.get('LOCALAPPDATA'), 'Programs/Microsoft VS Code/bin/code.cmd'),
                (os.environ.get('ProgramFiles'), 'Microsoft VS Code/bin/code.cmd')) if base]
        executable = next((str(p) for p in candidates if p.is_file()), None)
    if not executable or not Path(executable).is_file():
        raise ValueError('VS Code CLI not found. Install approved VS Code and enable its code command on PATH, then retry --editor vscode.')
    path = Path(executable).absolute()
    if path.suffix.lower() in ('.cmd', '.bat'):
        # Use Electron as Node, not cmd.exe: user paths never become shell code.
        app = path.parent.parent
        binary, cli = app / 'Code.exe', app / 'resources/app/out/cli.js'
        if not binary.is_file() or not cli.is_file():
            raise ValueError('Unrecognized VS Code Windows launcher; use the approved VS Code installation.')
        return [str(binary), str(cli)], dict(os.environ, ELECTRON_RUN_AS_NODE='1')
    return [str(path)], dict(os.environ)


def package(root, output, *, name='matsugit', version=None, profile=None, theme_files=None):
    root, output = Path(root), Path(output)
    if not re.fullmatch(r'[a-z][a-z0-9-]*', name):
        raise ValueError('Invalid extension identity')
    source = root / 'vscode-extension'
    manifest = json.loads((source / 'package.json').read_text())
    version = version or json.loads((root / 'codex-plugin/package.json').read_text())['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Expected a release version')
    manifest['name'], manifest['version'] = name, version
    manifest['displayName'] = 'Matsugit' if name == 'matsugit' else 'Matsugit / ' + name.removeprefix('matsugit-').title()
    contributes = manifest['contributes']
    contributes['commands'][0].update(command=name + '.open', title=manifest['displayName'] + ': Open Document')
    contributes['menus']['editor/title'][0]['command'] = name + '.open'
    contributes['customEditors'][0].update(viewType=name + '.editor', displayName=manifest['displayName'])
    properties = contributes['configuration']['properties']
    contributes['configuration']['properties'] = {key.replace('matsugit.', name + '.', 1): value for key, value in properties.items()}
    manifest.pop('scripts', None)
    if profile:
        manifest['matsugitProfile'] = profile
    files = {'extension/package.json': (json.dumps(manifest, indent=2) + '\n').encode()}
    for name_ in ('host.js', 'native.js', 'dist/extension.cjs', 'README.md'):
        files['extension/' + name_] = (source / name_).read_bytes()
    for name_ in ('server.mjs', 'THIRD-PARTY-NOTICES.txt'):
        files['extension/runtime/' + name_] = (root / 'codex-plugin/bundle' / name_).read_bytes()
    files['extension/LICENSE'] = (root / 'LICENSE').read_bytes()
    for name_, data in (theme_files or {}).items():
        if Path(name_).is_absolute() or '..' in Path(name_).parts or '\\' in name_:
            raise ValueError('Invalid theme asset path')
        files['extension/themes/' + name_] = data
    ns = 'http://schemas.microsoft.com/developer/vsx-schema/2011'
    ET.register_namespace('', ns)
    xml = ET.Element('PackageManifest', {'xmlns':ns, 'Version':'2.0.0'})
    meta = ET.SubElement(xml, 'Metadata')
    ET.SubElement(meta, 'Identity', {'Language':'en-US','Id':name,'Version':version,'Publisher':manifest['publisher']})
    ET.SubElement(meta, 'DisplayName').text = manifest['displayName']
    ET.SubElement(meta, 'Description', {'xml:space':'preserve'}).text = manifest['description']
    ET.SubElement(meta, 'License').text = 'extension/LICENSE'
    props = ET.SubElement(meta, 'Properties')
    for key, value in {'Microsoft.VisualStudio.Code.Engine':manifest['engines']['vscode'],
                       'Microsoft.VisualStudio.Code.ExtensionKind':'workspace'}.items():
        ET.SubElement(props, 'Property', {'Id':key,'Value':value})
    ET.SubElement(ET.SubElement(xml, 'Installation'), 'InstallationTarget', {'Id':'Microsoft.VisualStudio.Code'})
    ET.SubElement(xml, 'Dependencies')
    ET.SubElement(ET.SubElement(xml, 'Assets'), 'Asset', {'Type':'Microsoft.VisualStudio.Code.Manifest',
                  'Path':'extension/package.json','Addressable':'true'})
    files['extension.vsixmanifest'] = ET.tostring(xml, encoding='utf-8', xml_declaration=True)
    types = ET.Element('Types', {'xmlns':'http://schemas.openxmlformats.org/package/2006/content-types'})
    for suffix in sorted({Path(p).suffix.lstrip('.') for p in files if Path(p).suffix}):
        ET.SubElement(types, 'Default', {'Extension':suffix,'ContentType':'application/octet-stream'})
    files['[Content_Types].xml'] = ET.tostring(types, encoding='utf-8', xml_declaration=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix='.vsix', delete=False) as temp:
        staged = Path(temp.name)
    try:
        with zipfile.ZipFile(staged, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name_, data in sorted(files.items()):
                info = zipfile.ZipInfo(name_, date_time=(2026, 1, 1, 0, 0, 0))
                archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
        os.replace(staged, output)
    finally:
        staged.unlink(missing_ok=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--code', help='Path to the approved VS Code CLI')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/matsugit.vsix')
    args = parser.parse_args()
    command, env = code_command(args.code) if args.install else (None, None)
    output = package(ROOT, args.output)
    print('VS Code extension:', output, flush=True)
    if args.install:
        subprocess.run([*command, '--install-extension', str(output), '--force'], env=env, check=True, timeout=120)
        print('Reload VS Code, open your Markdown file, then run Matsugit: Open Document.')


if __name__ == '__main__':
    main()
