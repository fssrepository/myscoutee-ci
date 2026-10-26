#!/usr/bin/env python3
"""GitHub scheduler mapping for the shared adapter; presentation conversion only.

Candidates remain in the native runner workspace. GitHub owns workflow dispatch and
consumer events. This file is intentionally not part of runtime qualification.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from catalog import read_catalog, MANUAL_BUILD_TYPES
from project import Project, api, required, run

FILE_KEYS={'LAB_NPMRC','LAB_GRADLE_PROPERTIES','LAB_DOCKER_CONFIG','LAB_SIGNING_KEY',
           'LAB_KUBE_AGENT_TOKEN','LAB_KVM_RUNTIME_CONFIG','LAB_INSTALL_CONFIG','LAB_TRUSTED_PUBLIC_KEY',
           'LAB_SSH_PRIVATE_KEY','LAB_SSH_KNOWN_HOSTS','NODE_EXTRA_CA_CERTS'}
UPSTREAM_KEYS={'LAB_UPSTREAM_PROJECT','LAB_UPSTREAM_VERSION','LAB_UPSTREAM_REVISION',
               'LAB_UPSTREAM_PACKAGE','LAB_UPSTREAM_IMAGE'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['init','prepare','dependencies','build','test','package','deb','kvm','infra_start','cluster','release','downstream','deploy','verify','pages'])
    args=parser.parse_args()
    os.umask(0o077)
    repository=required('GITHUB_REPOSITORY')
    name=repository.split('/')[-1]
    spec=read_catalog()[name]
    for key,value in spec.get('variables',{}).items(): os.environ.setdefault(key,value)
    candidate=os.environ.get('LAB_CANDIDATE') or required('GITHUB_RUN_ID')
    if not re.fullmatch(r'[0-9]+',candidate): raise ValueError('Candidate must be a GitHub run ID')
    base=Path(required('LAB_CANDIDATE_ROOT')).expanduser().resolve()/repository/candidate
    root=base/name
    event=json.loads(Path(required('GITHUB_EVENT_PATH')).read_text())
    default=event['repository']['default_branch']
    branch=required('GITHUB_REF').removeprefix('refs/heads/')
    if branch!=default and not branch.startswith('feature/'):
        raise ValueError('Lab operations require the default branch or feature/*')
    if branch!=default:
        if args.phase in ('release','downstream','pages'):
            raise ValueError('Feature candidates cannot be published')
        if args.phase in ('deploy','verify') and os.environ.get('LAB_TARGET')!='vmware':
            raise ValueError('Feature deployment is limited to VMware')
    os.environ.update(CI_PROJECT_NAME=name,CI_PROJECT_DIR=str(root),CI_PIPELINE_ID=candidate,
        CI_DEFAULT_BRANCH=default,CI_COMMIT_BRANCH=branch,CI_COMMIT_REF_PROTECTED='true',
        LAB_CI_PROVIDER='github',LAB_GITHUB_REPOSITORY=repository,
        CI_API_V4_URL=required('LAB_GITLAB_URL').rstrip('/')+'/api/v4',
        CI_SERVER_URL=required('LAB_GITLAB_URL').rstrip('/'),
        LAB_SOURCE_BASE=required('LAB_GITLAB_URL').rstrip('/')+'/'+required('LAB_GROUP_PATH'))
    path=required('LAB_GROUP_PATH')+'/'+('ci' if name=='myscoutee-ci' else name)
    local=api('GET','/projects/'+urllib.parse.quote(path,safe=''))
    os.environ.update(CI_PROJECT_ID=str(local['id']),CI_PROJECT_PATH=path,
        CI_REGISTRY=local['container_registry_image_prefix'].split('/')[0],
        CI_REGISTRY_IMAGE=local['container_registry_image_prefix'],
        CI_REGISTRY_USER='oauth2',CI_REGISTRY_PASSWORD=required('LAB_RELEASE_TOKEN'))
    base.mkdir(parents=True,exist_ok=True)
    with (base/'operation.lock').open('w') as lock, tempfile.TemporaryDirectory(prefix='github-inputs-',dir=base) as private:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Secret contents are transient FILE variables, never repository artifacts.
        for key in FILE_KEYS:
            value=os.environ.pop(key+'_CONTENT','')
            if value:
                file=Path(private)/key; file.write_text(value); file.chmod(0o600)
                os.environ[key]=str(file)
        helper=Path(private)/'askpass'
        helper.write_text('#!/bin/sh\ncase "$1" in\n*Username*github.com*) echo x-access-token;;\n*github.com*) printf "%s\\n" "$GH_TOKEN";;\n*Username*) echo oauth2;;\n*) printf "%s\\n" "$LAB_RELEASE_TOKEN";;\nesac\n')
        helper.chmod(0o700)
        os.environ.update(GIT_ASKPASS=str(helper),GIT_TERMINAL_PROMPT='0')
        state=base/'context.json'
        library=run('git','rev-parse','HEAD',cwd=Path(__file__).resolve().parents[1],capture=True)
        if args.phase=='init':
            if state.exists() or root.exists(): raise ValueError('Candidate exists; resume it with workflow_dispatch')
            source=Path(required('GITHUB_WORKSPACE'))/'source'
            revision=run('git','rev-parse','HEAD',cwd=source,capture=True)
            run('git','clone','--no-hardlinks',source,root)
            run('git','checkout','--detach',revision,cwd=root)
            run('git','remote','set-url','origin','https://github.com/'+repository+'.git',cwd=root)
            context={'repository':repository,'candidate':candidate,'revision':revision,'library':library,
                'branch':branch,
                'title':run('git','log','-1','--format=%s',cwd=root,capture=True),
                'level':os.environ.get('LAB_RELEASE_LEVEL') or 'patch',
                'upstream':{k:v for k,v in event.get('client_payload',{}).items() if k in UPSTREAM_KEYS}}
            if any(not isinstance(v,str) for v in context['upstream'].values()): raise ValueError('Upstream values must be strings')
            state.write_text(json.dumps(context,indent=2)+'\n')
            output=os.environ.get('GITHUB_OUTPUT')
            if output:
                with open(output,'a') as stream:
                    stream.write('heavy='+str(spec['type'] in MANUAL_BUILD_TYPES).lower()+'\ncandidate='+candidate+'\n')
            summary=os.environ.get('GITHUB_STEP_SUMMARY')
            if summary:
                with open(summary,'a') as stream: stream.write('Candidate: `'+candidate+'`. DEB packaging and publication require workflow dispatch.\n')
            return
        context=json.loads(state.read_text())
        if context['repository']!=repository or context['candidate']!=candidate or context['library']!=library:
            raise ValueError('Candidate identity/library changed; use its original pinned CI library')
        if context['branch']!=branch: raise ValueError('Resume a candidate on its original branch')
        os.environ.update(CI_COMMIT_SHA=context['revision'],CI_COMMIT_TITLE=context['title'],
                          LAB_RELEASE_LEVEL=context['level'],**context['upstream'])
        receipts=base/'completed.json'
        completed=json.loads(receipts.read_text()) if receipts.exists() else []
        phase=args.phase
        prerequisites={'prepare':[], 'dependencies':['prepare'],'build':['dependencies'],'test':['build'],
            'infra_start':['dependencies'],'cluster':['deploy'],'package':['build'],'deb':['package'],'kvm':['package'],'release':['package'],
            'downstream':['release'],'deploy':['package'],'verify':['deploy'],'pages':['package']}
        if not set(prerequisites[phase])<=set(completed): raise ValueError('Run prerequisite phases first: '+','.join(prerequisites[phase]))
        if phase in completed and phase in ('prepare','dependencies','build','package','release','downstream'):
            raise ValueError('Phase already completed; retain the same candidate instead of rebuilding')
        project=Project()
        getattr(project,'release_phase' if phase=='release' else phase)()
        if phase not in completed: completed.append(phase)
        receipts.write_text(json.dumps(completed)+'\n')


if __name__=='__main__': main()
