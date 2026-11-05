"""Local push receipts and explicit, read-only provider deployment checks."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone
from urllib.parse import quote, urlencode, urlsplit

from .core import Error
from .repositories import api, validate


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def receipt_path(source):
    root = Path(os.environ.get('MATSUGIT_PUBLICATION_STATE',
        str(Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'matsugit/publications'))).expanduser()
    return root / (hashlib.sha256(str(Path(source).resolve()).encode()).hexdigest() + '.json')


def store(source, receipt):
    path = receipt_path(source)
    if path.parent.is_symlink() or path.is_symlink():
        raise Error('Publication state is a symlink; left untouched')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.receipt-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(receipt, stream)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def record(source, plan, revision, environment=None):
    if not re.fullmatch(r'[0-9a-f]{40,64}', revision or ''):
        raise Error('Publication did not return a commit revision')
    value = {key:plan.get(key) for key in ('provider', 'project_url', 'site_url', 'branch',
             'target', 'source_sha256', 'theme', 'build')}
    value.update(version=1, revision=revision, pushed_at=now(), stage='pushed',
                 environment=environment, detail='Pushed; deployment has not been verified.')
    store(source, value)
    return value


def safe_url(value):
    parsed = urlsplit(value or '')
    return value if parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password else None


def status(source, check=False):
    path = receipt_path(source)
    if not path.is_file():
        return {'stage':'local', 'detail':'No push recorded by this workspace on this computer.'}
    if path.is_symlink() or path.stat().st_size > 65536:
        raise Error('Invalid publication state file')
    value = json.loads(path.read_text())
    if value.get('version') != 1:
        raise Error('Unknown publication state version')
    if check:
        # A cached success is not current evidence after a failed refresh.
        value.update(stage='pushed', checked_at=now(), detail='Deployment not verified.')
        for key in ('deployed_revision', 'pipeline_url', 'pipeline_status', 'check_error'):
            value.pop(key, None)
        try:
            inspect(value)
        except (Error, ValueError, KeyError, TypeError) as error:
            value['check_error'] = str(error)
            value['detail'] = 'Pushed; provider status unavailable. No login or permission change was attempted.'
        if value['stage'] != 'published':
            value['stage'] = pipeline_stage(value.get('pipeline_status'))
        # Do not replace a newer push that finished while the provider was queried.
        current = json.loads(path.read_text())
        if (current.get('revision'), current.get('pushed_at')) != (value['revision'], value['pushed_at']):
            return current
        store(source, value)
    return value


def inspect(value):
    parsed = urlsplit(value['project_url'])
    provider, host, project = value['provider'], parsed.hostname, parsed.path.strip('/')
    if not safe_url(value['project_url']) or parsed.query or parsed.fragment:
        raise Error('Invalid recorded project URL')
    validate(provider, host, project)
    revision, branch = value['revision'], value['branch']
    endpoint = 'repos/' + project if provider == 'github' else 'projects/' + quote(project, safe='')
    get = lambda suffix: api(provider, host, endpoint + suffix)
    if provider == 'github':
        runs = get('/actions/runs?' + urlencode({'head_sha':revision, 'branch':branch, 'per_page':20})).get('workflow_runs', [])
        runs = [run for run in runs if run.get('head_sha') == revision and run.get('head_branch') == branch]
        if runs:
            run = runs[0]
            value.update(pipeline_url=safe_url(run.get('html_url')), pipeline_status=run.get('conclusion') or run.get('status'))
        environment = value.get('environment') or 'github-pages'
        deployments = get('/deployments?' + urlencode({'environment':environment, 'per_page':1}))
        if deployments:
            deployment = deployments[0]
            states = get(f"/deployments/{int(deployment['id'])}/statuses?per_page=1")
            if states and states[0].get('state') == 'success' and deployment.get('environment') == environment:
                value['deployed_revision'] = deployment.get('sha')
                if deployment.get('sha') == revision:
                    value.update(stage='published', detail='Provider reports this revision deployed.',
                                 site_url=safe_url(states[0].get('environment_url')) or value.get('site_url'))
                    return
        # Branch-based Pages does not always create an Actions deployment.
        if not value.get('environment'):
            build = get('/pages/builds/latest')
            if build.get('status') == 'built':
                value['deployed_revision'] = build.get('commit')
                if build.get('commit') == revision:
                    value.update(stage='published', detail='GitHub reports this Pages revision built and deployed.')
                    return
    else:
        runs = get('/pipelines?' + urlencode({'sha':revision, 'ref':branch, 'per_page':20}))
        runs = [run for run in runs if run.get('sha') == revision and run.get('ref') == branch]
        if runs:
            run = runs[0]
            value.update(pipeline_url=safe_url(run.get('web_url')), pipeline_status=run.get('status'))
        # GitLab Pages metadata has no commit SHA. A green pipeline alone is
        # insufficient, especially when documents and slides deploy separately.
        environment = value.get('environment')
        if environment:
            deployments = get('/deployments?' + urlencode({'environment':environment, 'order_by':'id', 'sort':'desc', 'per_page':1}))
            if deployments:
                deployment = deployments[0]
                if deployment.get('status') == 'success' and deployment.get('environment', {}).get('name') == environment:
                    value['deployed_revision'] = deployment.get('sha')
                    if deployment.get('sha') == revision:
                        value.update(stage='published', detail='GitLab reports this revision deployed to the configured environment.')
                        return
    pipeline = value.get('pipeline_status')
    value['detail'] = f'Pushed; pipeline {pipeline}. Deployment not verified.' if pipeline else 'Pushed; no matching pipeline or verified deployment found.'
    value['stage'] = pipeline_stage(pipeline)


def pipeline_stage(status):
    if status in ('failed', 'failure', 'canceled', 'cancelled', 'timed_out', 'action_required'):
        return 'failed'
    if status in ('running', 'pending', 'queued', 'in_progress', 'waiting_for_resource', 'preparing'):
        return 'building'
    return 'pushed'
