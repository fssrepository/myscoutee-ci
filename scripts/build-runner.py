#!/usr/bin/env python3
"""Start an opt-in host shell group runner using the already pinned runner binary."""
import json
import argparse
import os
import re
from pathlib import Path
import subprocess
from local_gitlab import LocalGitLab, ROOT
from configure import load_env


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only',action='store_true',help='Prepare registration/files without starting a runner')
    args=parser.parse_args()
    if not args.prepare_only and (ROOT/'.local/private/runner-host.env').exists():
        if subprocess.run(['systemctl','is-active','--quiet','myscoutee-ci-build-runner.service']).returncode:
            raise SystemExit('Dedicated runner requires the one-time host setup: sudo python3 scripts/runner-host.py --apply')
        print('Dedicated runner is active. Reconcile its host configuration with scripts/runner-host.py --apply.')
        return
    env={**load_env(ROOT/'.env.example'),**load_env(ROOT/'.env'),**os.environ}
    concurrency=env.get('LAB_BUILD_CONCURRENCY','')
    if not re.fullmatch(r'[1-9][0-9]*',concurrency):
        raise ValueError('LAB_BUILD_CONCURRENCY must be a positive integer')
    lab=LocalGitLab()
    directory=lab.state/'build-runner'
    directory.mkdir(mode=0o700,exist_ok=True)
    binary=directory/'gitlab-runner'
    if not binary.exists():
        container=subprocess.check_output(['docker','compose','ps','-q','runner'],cwd=ROOT,text=True).strip()
        if not container: raise SystemExit('Start the Docker validation runner first')
        subprocess.run(['docker','cp',container+':/usr/bin/gitlab-runner',str(binary)],check=True)
        binary.chmod(0o700)
    config=directory/'config.toml'
    if not config.exists():
        runner=lab.api('POST','/user/runners',{'runner_type':'group_type','group_id':lab.project['group_id'],
            'description':'MyScoutee trusted native builds','tag_list':['lab-build'],'run_untagged':False})
        config.write_text(f'''concurrent = {concurrency}
check_interval = 3
[[runners]]
  name = "myscoutee-native-builds"
  url = {json.dumps(lab.base)}
  token = {json.dumps(runner['token'])}
  executor = "shell"
  request_concurrency = {concurrency}
  shell = "bash"
  builds_dir = {json.dumps(str(directory/'builds'))}
  [runners.custom_build_dir]
    enabled = true
''')
        config.chmod(0o600)
    # Runner owns its shell wrapper, not the user's interactive dotfiles.
    # Native jobs get Bash semantics without profile/logout side effects.
    content=config.read_text()
    updated=content.replace('  shell = "sh"','  shell = "bash"')
    updated,count=re.subn(r'^concurrent\s*=.*$', 'concurrent = '+concurrency,updated,flags=re.M)
    if count!=1: raise ValueError('Expected one global runner concurrency setting')
    if re.search(r'^\s*request_concurrency\s*=',updated,flags=re.M):
        updated=re.sub(r'^\s*request_concurrency\s*=.*$', '  request_concurrency = '+concurrency,updated,flags=re.M)
    else:
        updated=updated.replace('  executor = "shell"','  executor = "shell"\n  request_concurrency = '+concurrency)
    if updated!=content: config.write_text(updated)
    shell_dir=directory/'shell'; shell_dir.mkdir(mode=0o700,exist_ok=True)
    wrapper=shell_dir/'bash'
    wrapper.write_text('#!/bin/bash\numask 077\nargs=()\nfor arg in "$@"; do\n  case "$arg" in --login|-l) ;; *) args+=("$arg");; esac\ndone\nexec /bin/bash --noprofile --norc "${args[@]}"\n')
    wrapper.chmod(0o700)
    if args.prepare_only:
        print('Native runner files prepared; no service started.')
        return
    generation=directory/'service-generation'
    current=generation.read_text().strip() if generation.exists() else ''
    active=subprocess.run(['systemctl','--user','is-active','--quiet','myscoutee-ci-build-runner.service']).returncode==0
    if active and current!='2':
        subprocess.run(['systemctl','--user','stop','myscoutee-ci-build-runner.service'],check=True)
        active=False
    if not active:
        subprocess.run(['systemctl','--user','reset-failed','myscoutee-ci-build-runner.service'],capture_output=True)
        subprocess.run(['systemd-run','--user','--unit=myscoutee-ci-build-runner',
            '--setenv=PATH='+str(shell_dir)+':'+os.environ['PATH'],
            '--property=WorkingDirectory='+str(directory),str(binary),'run','--config',str(config),
            '--working-directory',str(directory)],check=True)
        generation.write_text('2\n')
    print('Native group runner ready: '+concurrency+' concurrent jobs. Not enabled at host boot.')


if __name__=='__main__': main()
