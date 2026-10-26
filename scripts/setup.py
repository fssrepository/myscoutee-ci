#!/usr/bin/env python3
"""Reproduce the local lab from committed code and ignored .env configuration."""
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from configure import load_env
from local_gitlab import ROOT


def main():
    def run(*command): subprocess.run(command,cwd=ROOT,check=True)
    run('bash','scripts/lab.sh','init')
    env=load_env(ROOT/'.env')
    run('bash','scripts/lab.sh','up')
    url='http://127.0.0.1:'+env.get('GITLAB_HTTP_PORT','8929')+'/users/sign_in'
    for attempt in range(120):
        try:
            with urllib.request.urlopen(url,timeout=5) as response:
                if response.status==200: break
        except (OSError,urllib.error.URLError): pass
        if attempt%6==0: print('Waiting for GitLab initialization...',flush=True)
        time.sleep(5)
    else: raise SystemExit('GitLab did not become ready; inspect docker compose logs gitlab')
    run('python3','scripts/provision.py')
    run('python3','scripts/push-local.py')
    workspace=Path(env.get('LAB_WORKSPACE_DIR') or ROOT.parent).expanduser().resolve()
    run('python3','scripts/import-workspace.py',str(workspace),'--create-only')
    config=env.get('LAB_VARIABLES_CONFIG') or str(ROOT/'examples/variables.json')
    run('python3','scripts/configure.py','--config',config,'--apply')
    run('python3','scripts/build-runner.py')
    run('python3','scripts/kubernetes.py','provision')
    # Variables, project access and runners must exist before source pushes.
    run('python3','scripts/import-workspace.py',str(workspace))
    print('Lab ready: '+url.removesuffix('/users/sign_in'))


if __name__=='__main__': main()
