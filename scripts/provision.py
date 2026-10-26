#!/usr/bin/env python3
"""Create the local project and validation runner; secrets stay in Git-ignored .local/state."""
import json
import datetime
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def compose(*args, **kwargs):
    return subprocess.run(['docker', 'compose', *args], cwd=ROOT, check=True, **kwargs)


def main():
    os.umask(0o077)
    # Config includes paths and defaults only; never print it.
    config = json.loads(compose('config', '--format', 'json', capture_output=True, text=True).stdout)
    password_path = Path(config['secrets']['root_password']['file'])
    state = password_path.parent
    port = config['services']['gitlab']['ports'][0]['published']
    base = f'http://127.0.0.1:{port}'
    try:
        with urllib.request.urlopen(base+'/users/sign_in', timeout=10) as response:
            if response.status != 200:
                raise ValueError('GitLab is not ready')
    except (OSError, ValueError):
        raise SystemExit('GitLab is still initializing; retry provision after readiness succeeds.')
    token_file = state/'bootstrap-api-token'
    if not token_file.exists():
        ruby = "u=User.find_by_username!('root'); t=u.personal_access_tokens.create!(name:'local-lab-bootstrap',scopes:['api'],expires_at:30.days.from_now); puts t.token"
        result = compose('exec', '-T', 'gitlab', 'gitlab-rails', 'runner', ruby, capture_output=True, text=True)
        # Rails may print a warning before the token. Keep everything private.
        token = result.stdout.strip().splitlines()[-1]
        if not token.startswith('glpat-'):
            raise SystemExit('Token creation failed; output withheld.')
        token_file.write_text(token+'\n')
        token_file.chmod(0o600)
    token = token_file.read_text().strip()

    def api(method, path, payload=None):
        req = urllib.request.Request(base+'/api/v4'+path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'PRIVATE-TOKEN': token, 'Content-Type': 'application/json'}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            # Do not dump token-bearing requests/responses to CI or chat logs.
            raise RuntimeError(f'GitLab API {method} {path}: HTTP {error.code}') from None

    api('PUT', '/application/settings', {'signup_enabled': False})
    labels = config['services']['gitlab']['labels']
    group_path = labels['io.myscoutee.lab.group']
    project_path = labels['io.myscoutee.lab.project']
    groups = api('GET', '/groups?search='+urllib.parse.quote(group_path))
    group = next((g for g in groups if g['full_path']==group_path), None)
    if group is None:
        group = api('POST', '/groups', {'name':group_path, 'path':group_path, 'visibility':'private'})
    release_token=state/'group-release-token'
    if not release_token.exists():
        expires=(datetime.date.today()+datetime.timedelta(days=90)).isoformat()
        bot=api('POST',f'/groups/{group["id"]}/access_tokens',{'name':'local-lab-release',
            'scopes':['api','write_repository'],'access_level':40,'expires_at':expires})
        release_token.write_text(bot['token']+'\n'); release_token.chmod(0o600)
    projects = api('GET', f'/groups/{group["id"]}/projects?per_page=100')
    project = next((p for p in projects if p['path']==project_path), None)
    if project is None:
        project = api('POST', '/projects', {'name': project_path, 'path': project_path, 'namespace_id':group['id'],
            'visibility': 'private', 'initialize_with_readme': False, 'default_branch': 'master'})
    project_id = project['id']
    api('PUT',f'/projects/{project_id}',{'ci_config_path':'config/ci/pipeline.yml'})
    project_url = base+'/'+group_path+'/'+project_path
    (state/'project.json').write_text(json.dumps({'id': project_id, 'group_id':group['id'], 'url':project_url}, indent=2)+'\n')
    runner_path = state/'runner/config.toml'
    if not runner_path.exists():
        runner = api('POST', '/user/runners', {'runner_type':'group_type', 'group_id':group['id'],
            'description':'Local isolated validation', 'tag_list':['lab-docker'],
            'run_untagged':False})
        runner_path.write_text(f'''concurrent = 1
check_interval = 3
[[runners]]
  name = "myscoutee-lab-validation"
  url = "http://gitlab:{port}"
  clone_url = "http://gitlab:{port}"
  token = {json.dumps(runner['token'])}
  executor = "docker"
  [runners.docker]
    image = "python:3.13-slim-bookworm"
    network_mode = "myscoutee-ci"
    privileged = false
    volumes = ["/cache"]
''')
        runner_path.chmod(0o600)
    compose('--profile', 'runner', 'up', '-d', 'runner')
    print(f'Local project ready: {project_url}')
    print('Validation runner configured. Root password and bootstrap token remain in Git-ignored .local/state.')
    print('Push the reviewed commit with scripts/push-local.py to run the pipeline.')


if __name__ == '__main__':
    main()
