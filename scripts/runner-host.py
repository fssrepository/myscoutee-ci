#!/usr/bin/env python3
"""One-time dedicated native runner setup. Default: validate and show the plan."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess

from configure import load_env
from local_gitlab import LocalGitLab, ROOT

SERVICE='myscoutee-ci-build-runner.service'
UNIT=Path('/etc/systemd/system')/SERVICE
INVENTORY=Path('/var/lib/myscoutee-ci-runner/inventory.json')
KEYS={'RUNNER_USER','RUNNER_OPERATOR','RUNNER_HOME','RUNNER_STATE_DIR',
      'RUNNER_APPLICATION_DIR','RUNNER_MICROSERVICES_DIR','RUNNER_TOOL_DIRS',
      'RUNNER_JAVA_HOME','RUNNER_KVM_STATE_DIRS'}


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args],check=True,**kwargs)


def path(value):
    result=Path(value)
    result=(ROOT/result).absolute() if not result.is_absolute() else result
    # Restrict systemd directive characters; do not interpolate shell code.
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+',str(result)):
        raise ValueError('Host paths must contain only letters, numbers, /, _, - and .')
    if result.resolve()!=Path(os.path.normpath(result)):
        raise ValueError('Use a real path, not a symlink: '+str(result))
    return result.resolve()


def configuration(file):
    if not file.is_file() or file.is_symlink(): raise ValueError('Missing regular runner host configuration')
    if file.stat().st_mode & 0o077: raise ValueError('Runner host configuration must have mode 600')
    values=load_env(file)
    if set(values)!=KEYS: raise ValueError('Runner host configuration keys differ from the example')
    for key in ('RUNNER_USER','RUNNER_OPERATOR'):
        if not re.fullmatch(r'[a-z_][a-z0-9_-]*',values[key]) or values[key]=='root':
            raise ValueError('Invalid non-root account: '+key)
    if values['RUNNER_USER']==values['RUNNER_OPERATOR']:
        raise ValueError('Use a dedicated runner account, not the operator account')
    for key in KEYS-{'RUNNER_USER','RUNNER_OPERATOR','RUNNER_TOOL_DIRS','RUNNER_KVM_STATE_DIRS'}:
        values[key]=path(values[key])
    for key in ('RUNNER_TOOL_DIRS','RUNNER_KVM_STATE_DIRS'):
        items=json.loads(values[key])
        if not isinstance(items,list) or not items or not all(isinstance(p,str) for p in items):
            raise ValueError('Expected nonempty JSON path list: '+key)
        values[key]=[path(p) for p in items]
    # No blanket ownership or ACL changes to a workspace/home/system directory.
    writable=[values['RUNNER_HOME'], values['RUNNER_STATE_DIR'], *values['RUNNER_KVM_STATE_DIRS']]
    for directory in writable:
        if '.local' not in directory.parts or len(directory.parts)<5:
            raise ValueError('Writable state must be a project-owned .local subdirectory')
    if values['RUNNER_STATE_DIR'].name!='build-runner': raise ValueError('Expected build-runner state directory')
    for directory in values['RUNNER_TOOL_DIRS']:
        if not directory.is_dir() or len(directory.parts)<3:
            raise ValueError('Tool installation is missing or too broad: '+str(directory))
    if values['RUNNER_JAVA_HOME'] not in values['RUNNER_TOOL_DIRS']:
        raise ValueError('Declare RUNNER_JAVA_HOME in RUNNER_TOOL_DIRS')
    return values


def unit(config):
    directory=config['RUNNER_STATE_DIR']
    search=[directory/'shell', *[p/'bin' for p in config['RUNNER_TOOL_DIRS']]]
    search.extend(Path(p) for p in ('/usr/local/bin','/usr/bin','/bin','/usr/sbin','/sbin'))
    return f'''# Managed by myscoutee-ci scripts/runner-host.py
[Unit]
Description=MyScoutee dedicated native build runner
After=network.target docker.service

[Service]
Type=simple
User={config['RUNNER_USER']}
Group={config['RUNNER_USER']}
WorkingDirectory={directory}
Environment=HOME={config['RUNNER_HOME']}
Environment=JAVA_HOME={config['RUNNER_JAVA_HOME']}
Environment=PATH={':'.join(str(p) for p in search)}
UMask=0077
ExecStart={directory}/gitlab-runner run --config {directory}/config.toml --working-directory {directory}
KillSignal=SIGQUIT
TimeoutStopSec=120
Restart=on-failure
RestartSec=5
'''


def check_owned(config, inventory):
    try: identity=pwd.getpwnam(config['RUNNER_USER'])
    except KeyError: identity=None
    if identity and (inventory.get('user')!=identity.pw_name or inventory.get('uid')!=identity.pw_uid
                     or identity.pw_dir!=str(config['RUNNER_HOME']) or identity.pw_shell!='/usr/sbin/nologin'):
        raise ValueError('Existing account is not owned by this helper; preserved')
    if UNIT.exists() and hashlib.sha256(UNIT.read_bytes()).hexdigest()!=inventory.get('unit_sha256'):
        raise ValueError('Existing service is not the recorded owned service; preserved')
    if UNIT.is_symlink(): raise ValueError('Refusing linked service')
    return identity


def traverse(directory, user):
    for parent in reversed(directory.parents):
        if parent!=Path('/'):
            run('setfacl','-m','u:'+user+':--x',parent)


def transfer(directory, identity):
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    traverse(directory,identity.pw_name)
    # Do not follow a candidate symlink into another project or personal state.
    for parent,dirs,files in os.walk(directory,followlinks=False):
        for item in [Path(parent),*[Path(parent)/name for name in dirs+files]]:
            os.chown(item,identity.pw_uid,identity.pw_gid,follow_symlinks=False)
    # Default ACLs override umask and would make new private keys/state group
    # accessible. KVM requires 0700 state, SSH requires owner-only private keys.
    run('setfacl','-R','-P','-b',directory)
    run('setfacl','-R','-P','-k',directory)
    for parent,dirs,files in os.walk(directory,followlinks=False):
        Path(parent).chmod(0o700)
        for name in files:
            item=Path(parent)/name
            if not item.is_symlink(): item.chmod(item.stat().st_mode & 0o700)


def apply(config):
    if os.geteuid()!=0: raise ValueError('Run --apply once with sudo in a terminal; no password is stored')
    if INVENTORY.is_symlink() or INVENTORY.parent.is_symlink(): raise ValueError('Linked host inventory')
    inventory=json.loads(INVENTORY.read_text()) if INVENTORY.exists() else {}
    if INVENTORY.exists() and (INVENTORY.stat().st_uid!=0 or INVENTORY.stat().st_mode & 0o022):
        raise ValueError('Host inventory must be root-owned and not writable by others')
    if not shutil.which('setfacl'): raise ValueError('Install the host acl package before applying')
    identity=check_owned(config,inventory)
    operator=pwd.getpwnam(config['RUNNER_OPERATOR'])
    state=config['RUNNER_STATE_DIR'].parent
    lab=LocalGitLab(state)
    runners=lab.api('GET',f'/groups/{lab.project["group_id"]}/runners?per_page=100')
    native=[r for r in runners if 'lab-build' in lab.api('GET',f'/runners/{r["id"]}')['tag_list']]
    if len(native)!=1: raise ValueError('Expected the single existing native group runner')
    runner=native[0]
    was_paused=runner['paused']
    if inventory.get('migration_runner')==runner['id']:
        was_paused=inventory['migration_was_paused']
    lab.api('PUT',f'/runners/{runner["id"]}',{'paused':True})
    success=False
    jobs=[]
    try:
        jobs=lab.api('GET',f'/runners/{runner["id"]}/jobs?status=running')
        if jobs: raise ValueError('Runner still has active jobs; let them finish before migration')
        print('Runner is idle and paused; configuring the dedicated account.',flush=True)
        if not identity:
            if config['RUNNER_HOME'].exists(): raise ValueError('Unowned runner home exists; preserved')
            run('useradd','--system','--user-group','--home-dir',config['RUNNER_HOME'],
                '--no-create-home','--shell','/usr/sbin/nologin',config['RUNNER_USER'])
            identity=pwd.getpwnam(config['RUNNER_USER'])
            INVENTORY.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            inventory.update(user=identity.pw_name,uid=identity.pw_uid)
            INVENTORY.write_text(json.dumps(inventory)+'\n'); INVENTORY.chmod(0o600)
        inventory.update(migration_runner=runner['id'],migration_was_paused=was_paused)
        INVENTORY.write_text(json.dumps(inventory)+'\n')
        # Stop the previous personal user service; never run two managers.
        old_manager=['runuser','-u',operator.pw_name,'--','env','XDG_RUNTIME_DIR=/run/user/'+str(operator.pw_uid),
            'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/'+str(operator.pw_uid)+'/bus',
            'systemctl','--user']
        previous=subprocess.run([*old_manager,'is-active','--quiet',SERVICE])
        if previous.returncode==0: run(*old_manager,'stop',SERVICE)
        run('systemctl','stop',SERVICE) if UNIT.exists() else None
        run('python3',ROOT/'scripts/build-runner.py','--prepare-only',cwd=ROOT)
        support=config['RUNNER_MICROSERVICES_DIR']/'tools/host.py'
        if not Path('/var/lib/myscoutee-msc121-host/inventory.json').exists():
            run('python3',support,'install','--user',identity.pw_name,cwd=config['RUNNER_APPLICATION_DIR'])
        run('usermod','-a','-G','docker,libvirt',identity.pw_name)
        for directory in [config['RUNNER_HOME'],config['RUNNER_STATE_DIR'],*config['RUNNER_KVM_STATE_DIRS']]:
            print('Transferring declared state:',directory,flush=True)
            transfer(directory,identity)
        for directory in config['RUNNER_TOOL_DIRS']:
            traverse(directory,identity.pw_name)
            run('setfacl','-R','-P','-m','u:'+identity.pw_name+':rX',directory)
        # Retention reads only its existing API credential and project metadata.
        for file in (state/'bootstrap-api-token',state/'project.json'):
            traverse(file,identity.pw_name)
            run('setfacl','-m','u:'+identity.pw_name+':r--',file)
        run('python3',support,'authorize-start','--user',identity.pw_name,cwd=config['RUNNER_APPLICATION_DIR'])
        print('Starting the dedicated runner service.',flush=True)
        content=unit(config)
        UNIT.write_text(content); UNIT.chmod(0o644)
        inventory['unit_sha256']=hashlib.sha256(content.encode()).hexdigest()
        INVENTORY.write_text(json.dumps(inventory,indent=2)+'\n')
        run('systemctl','daemon-reload')
        run('systemctl','start',SERVICE)
        run('systemctl','is-active','--quiet',SERVICE)
        success=True
    finally:
        # A partial migration must not send builds to an unverified identity.
        if success or jobs:
            lab.api('PUT',f'/runners/{runner["id"]}',{'paused':was_paused})
            if success:
                inventory.pop('migration_runner',None);inventory.pop('migration_was_paused',None)
                INVENTORY.write_text(json.dumps(inventory,indent=2)+'\n')
        else:
            print('Runner remains paused; correct the reported error and re-run --apply.')
    print('Dedicated runner ready. Service is not enabled at boot. No VM was started.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'.local/private/runner-host.env')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    config=configuration(args.config)
    if args.apply: apply(config)
    else:
        print('Dedicated account:',config['RUNNER_USER'])
        print('Home:',config['RUNNER_HOME'])
        print('Runner state:',config['RUNNER_STATE_DIR'])
        print('KVM state directories:',len(config['RUNNER_KVM_STATE_DIRS']))
        print('Tool installations:',len(config['RUNNER_TOOL_DIRS']))
        print('Validation passed. Use --apply with sudo for the one-time host setup.')


if __name__=='__main__': main()
