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
    if action in ('repositories', 'connect-repository'):
        from matsugit.repositories import discover, connect
        if action == 'repositories':
            return discover(request['provider'], request['host'], request.get('page', 1))
        return connect(request['provider'], request['host'], request['repository'])
    if action == 'options':
        data = preferences()
        selected = config(Path(request['path']), {'command':'publish'})
        return {'targets': data.get('publish_targets', {}),
                'default': selected.get('target'), 'build':selected.get('build', 'local'),
                'export_directory': data.get('export_directory')}
    source = Path(request['path'])
    settings = config(source, {'command': 'publish' if action in ('plan', 'publish') else 'export',
                              'target': request.get('target'), 'theme': request.get('theme'), 'build':request.get('build'),
                              'quarto': os.environ.get('QUARTO', 'quarto')})
    if action == 'export':
        return export_file(settings, request['format'], request.get('output'),
                           sync_folder=request.get('sync_folder', False), source_text=request['text'],
                           replace=bool(request.get('sync_folder') and request.get('replace')))
    if action not in ('plan', 'publish'):
        raise Error('Unknown workspace action')
    if source.read_text(encoding='utf-8') != request['text']:
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
