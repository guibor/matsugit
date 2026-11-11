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


def deployment_problem(error):
    """Why the site build could not be started, in words a person can act on."""
    text = str(error)
    if 'Executable not found' in text:
        tool = 'glab' if 'glab' in text else 'gh'
        return (f'The site build could not be started from this computer: the {"GitLab" if tool == "glab" else "GitHub"} '
                f'command-line tool ({tool}) is not installed. Start the build in the project\'s pipelines page, '
                f'or install {tool} and log in once.')
    if any(word in text.lower() for word in ('auth', 'login', '401', '403', 'token')):
        return 'The site build could not be started: this computer is not logged in to the project. Start the build in the project\'s pipelines page, or log in once.'
    return 'The site build could not be started: ' + text[-300:]


def main(request):
    # A GUI worker cannot answer credential prompts; fail instead of hanging.
    os.environ['GIT_TERMINAL_PROMPT'] = '0'
    os.environ['GCM_INTERACTIVE'] = 'never'
    os.environ.setdefault('GIT_SSH_COMMAND', 'ssh -o BatchMode=yes -o ConnectTimeout=15')
    os.environ['GH_PROMPT_DISABLED'] = '1'
    action = request['action']
    if action == 'publication-status':
        from matsugit.publication import status
        return status(Path(request['path']), check=bool(request.get('check')))
    if action == 'share-status':
        from matsugit.share import status as share_status
        return share_status(Path(request['path']))
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
    if action in ('exchange-plan', 'exchange'):
        from matsugit.git_exchange import plan as exchange_plan, exchange
        source = Path(request['path'])
        if action == 'exchange-plan':
            return exchange_plan(source, request.get('assets', []))
        result = exchange(source, request['text'], assets=request.get('assets', []),
                          expected=request.get('fingerprint'), message=request.get('message'), confirmed=True)
        from matsugit.publication import record
        try:
            # A push into a configured project carries what a later site check needs.
            from matsugit.share import receipt_plan
            described, environment = receipt_plan(result)
        except (Error, OSError, ValueError) as error:
            result['message'] += ' Could not save local push receipt: ' + str(error)
            described = {}
        # A project whose site build runs only on request gets that request, so
        # "the site updates" holds. The push itself has already succeeded.
        if request.get('deploy') and described.get('deployment') == 'ci' and described.get('project_url'):
            try:
                from matsugit.publish import request_deployment
                target = config(source, {'command': 'publish', 'target': described['target']})
                request_deployment(target, described['provider'], described['project_url'])
                result['deployment_requested'] = True
            except (Error, OSError, KeyError) as error:
                result['deployment_error'] = deployment_problem(error)
        if described:
            try:
                described['deployment_error'] = result.get('deployment_error')
                result['publication'] = record(source, described, result['revision'], environment)
            except (Error, OSError, ValueError) as error:
                result['message'] += ' Could not save local push receipt: ' + str(error)
        return result
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
    # The push and the request to build the site are separate: a failed request
    # must not report a push that already happened as a failure.
    sha = publish(settings, confirmed=True, deploy=False)
    deployment_error = None
    if request.get('deploy'):
        try:
            from matsugit.publish import request_deployment
            request_deployment(settings, current['provider'], current['project_url'])
        except (Error, OSError) as error:
            deployment_error = deployment_problem(error)
    # Remember where the deck now lives, so its slides, document and source can be opened later.
    from matsugit.links import describe
    destination = current.get('destination') or str(Path(current['repo']) / current['directory'] / ('source.org' if source.suffix.lower() == '.org' else 'source.md'))
    try:
        current = dict(current, **describe(current['repo'], destination, {'ci_layout': current.get('ci_layout', 'native'),
            'site_dir': settings.get('site_dir'), 'document_url': settings.get('document_url'), 'slides_url': settings.get('slides_url')}))
    except (ValueError, OSError):
        pass
    from matsugit.publication import record
    current['deployment_error'] = deployment_error
    result = {'revision': sha, 'project_url': current['project_url'], 'site_url': current['site_url'], 'deployment_error': deployment_error,
            'status': 'Pushed. Verify CI and site access before sharing; deployment is not yet verified.'}
    if not current.get('source_sha256'):
        # In-place and moved sources: the receipt must still say which text was sent,
        # or the workspace reports unsent changes straight after publishing.
        import hashlib
        current = dict(current, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    try:
        result['publication'] = record(source, current, sha, settings.get('deployment_environment'))
    except (Error, OSError) as error:
        result['status'] += ' Could not save local publication receipt: ' + str(error)
    return result


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        with contextlib.redirect_stdout(sys.stderr):
            result = main(request)
        print(json.dumps(result))
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
