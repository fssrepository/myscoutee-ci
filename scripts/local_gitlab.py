"""Local bootstrap API: never print credentials or configuration dumps."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


class LocalGitLab:
    def __init__(self, state=None, *, base=None, token=None):
        if base is not None:
            if not token: raise ValueError('GitLab API credential is required')
            self.base=base.rstrip('/')
            self.token=token
            return
        if state is None:
            config=json.loads(subprocess.check_output(['docker','compose','config','--format','json'],cwd=ROOT))
            state=Path(config['secrets']['root_password']['file']).parent
        self.state=Path(state).resolve()
        self.project=json.loads((self.state/'project.json').read_text())
        self.base=self.project['url'].split('/',3)[:3]
        self.base='/'.join(self.base)
        self.token=(self.state/'bootstrap-api-token').read_text().strip()

    def graphql(self, query, variables):
        req=urllib.request.Request(self.base+'/api/graphql',method='POST',
            headers={'PRIVATE-TOKEN':self.token,'Content-Type':'application/json'},
            data=json.dumps({'query':query,'variables':variables}).encode())
        with urllib.request.urlopen(req,timeout=60) as response: result=json.load(response)
        if result.get('errors'): raise RuntimeError('GitLab GraphQL request failed: '+json.dumps(result['errors']))
        return result['data']

    def api(self, method, path, payload=None):
        req=urllib.request.Request(self.base+'/api/v4'+path,method=method,
            headers={'PRIVATE-TOKEN':self.token,'Content-Type':'application/json'},
            data=json.dumps(payload).encode() if payload is not None else None)
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req,timeout=180) as response:
                    body=response.read()
                    return json.loads(body) if body else None
            except urllib.error.HTTPError as error:
                if method=='GET' and error.code in (502,503,504) and attempt<5:
                    time.sleep(2); continue
                raise RuntimeError(f'GitLab {method} {path}: HTTP {error.code}') from None

    def git_environment(self):
        helper=self.state/'git-askpass'
        helper.write_text('#!/bin/sh\ncase "$1" in *Username*) echo root;; *) cat "$LAB_GIT_TOKEN_FILE";; esac\n')
        helper.chmod(0o700)
        return dict(os.environ,GIT_ASKPASS=str(helper),GIT_TERMINAL_PROMPT='0',
                    LAB_GIT_TOKEN_FILE=str(self.state/'bootstrap-api-token'))
