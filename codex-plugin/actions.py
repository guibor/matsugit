"""Explicit export/publication worker. No document-supplied executables."""
import contextlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matsugit.core import config, Error
from matsugit.targets import plan, settings as preferences
from matsugit.exports import export_file
from matsugit.publish import publish


def main(request):
    # A GUI worker cannot answer credential prompts; fail instead of hanging.
    os.environ['GIT_TERMINAL_PROMPT'] = '0'
    os.environ['GCM_INTERACTIVE'] = 'never'
    os.environ.setdefault('GIT_SSH_COMMAND', 'ssh -o BatchMode=yes -o ConnectTimeout=15')
    os.environ['GH_PROMPT_DISABLED'] = '1'
    action = request['action']
    if action == 'themes':
        from matsugit.core import theme_options
        return theme_options(config(Path(request['path'])))
    if action.startswith('table-'):
        from matsugit.table_editor import TableDocument
        document = TableDocument(request['source'], fmt=request.get('format', 'markdown'))
        if action == 'table-open':
            source = request['source']
            if request.get('html'):
                source = document.serialize(request['html'])['markdown']
                document = TableDocument(source, document.command, document.format)
            return {'html': document.html, 'source': source}
        if action == 'table-check':
            return document.check_import(request['html'])
        if action == 'table-serialize':
            return document.serialize(request['html'])
        raise Error('Unknown table operation')
    if action in ('repositories', 'connect-repository'):
        from matsugit.repositories import discover, connect
        if action == 'repositories':
            return discover(request['provider'], request['host'], request.get('page', 1))
        return connect(request['provider'], request['host'], request['repository'])
    if action in ('sync-plan', 'sync'):
        from matsugit.git_sync import sync
        source = Path(request['path'])
        if action == 'sync' and source.read_bytes().decode('utf-8') != request['text']:
            raise Error('Unsaved or external edits exist. Reconcile the draft before syncing; text retained')
        return sync(source, check=action == 'sync-plan', confirmed=action == 'sync',
                    expected=request.get('fingerprint'))
    if action == 'options':
        data = preferences()
        selected = config(Path(request['path']), {'command':'publish'})
        return {'targets': data.get('publish_targets', {}),
                'default': selected.get('target'), 'build':selected.get('build', 'local'),
                'export_directory': data.get('export_directory')}
    source = Path(request['path'])
    settings = config(source, {'command': 'publish' if action in ('plan', 'publish') else 'export',
                              'target': request.get('target'), 'theme': request.get('theme'), 'build':request.get('build'),
                              'move_source': request.get('move_source'),
                              'quarto': os.environ.get('QUARTO', 'quarto')})
    if action == 'export':
        return export_file(settings, request['format'], request.get('output'),
                           sync_folder=request.get('sync_folder', False), source_text=request['text'],
                           replace=bool(request.get('sync_folder') and request.get('replace')))
    if action not in ('plan', 'publish'):
        raise Error('Unknown workspace action')
    if source.read_bytes().decode('utf-8') != request['text']:
        raise Error('Save the current draft before publishing. The original file was not changed')
    current = plan(settings)
    if settings.get('deployment') not in (None, 'ci', 'push'):
        raise Error('This target requires its private publishing wrapper. Use its existing CLI/Emacs command')
    if action == 'plan':
        return current
    if request.get('fingerprint') != current['fingerprint']:
        raise Error('Source or target changed since confirmation. Review a new publishing plan')
    sha = publish(settings, confirmed=True, deploy=bool(request.get('deploy')))
    return {'revision': sha, 'project_url': current['project_url'], 'site_url': current['site_url'],
            'status': 'Pushed. Verify CI and site access before sharing; deployment is not yet verified.'}


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        with contextlib.redirect_stdout(sys.stderr):
            result = main(request)
        print(json.dumps(result))
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
