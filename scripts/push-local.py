#!/usr/bin/env python3
"""Push committed public files to the local GitLab without credentials in URLs."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    spec = importlib.util.spec_from_file_location('public', ROOT/'scripts/check-public.py')
    public = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(public)
    public.check()
    listed = subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    allowed = {str(p.relative_to(ROOT)) for p in public.public_files()}
    if any(p and p not in allowed for p in listed):
        raise SystemExit('Tracked file outside the public inventory; inspect git ls-files before pushing.')
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():
        raise SystemExit('Commit the reviewed files before pushing; worktree must be clean.')
    config = json.loads(subprocess.check_output(['docker','compose','config','--format','json'],cwd=ROOT))
    state = Path(config['secrets']['root_password']['file']).parent
    project = json.loads((state/'project.json').read_text())
    branch=subprocess.check_output(['git','symbolic-ref','--short','HEAD'],cwd=ROOT,text=True).strip()
    token_path = state/'bootstrap-api-token'
    with tempfile.TemporaryDirectory(dir=state, prefix='push-') as temporary:
        helper = Path(temporary)/'askpass'
        helper.write_text('#!/bin/sh\ncase "$1" in *Username*) echo root;; *) cat "$LAB_GIT_TOKEN_FILE";; esac\n')
        helper.chmod(0o700)
        env = dict(os.environ, GIT_ASKPASS=str(helper), GIT_TERMINAL_PROMPT='0', LAB_GIT_TOKEN_FILE=str(token_path))
        subprocess.run(['git','-c','credential.helper=','push',project['url']+'.git','HEAD:refs/heads/'+branch],cwd=ROOT,env=env,check=True)
    print('Committed source pushed; GitLab starts the commit pipeline.')


if __name__ == '__main__':
    main()
