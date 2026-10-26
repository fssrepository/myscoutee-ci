#!/usr/bin/env python3
"""Remove superseded local CI candidates; preserve releases and deployments."""
import argparse
from collections import defaultdict
from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import subprocess
import urllib.parse

from catalog import ROOT, read_catalog
from local_gitlab import LocalGitLab

ACTIVE = {'running', 'pending', 'preparing', 'waiting_for_resource', 'scheduled', 'canceling'}


def pages(lab, path):
    result=[]
    separator='&' if '?' in path else '?'
    for page in range(1,1001):
        batch=lab.api('GET',path+separator+f'per_page=100&page={page}')
        result.extend(batch)
        if len(batch)<100: return result
    raise RuntimeError('Pagination limit reached; refusing partial inventory')


def retained(pipelines, count):
    if not isinstance(count,int) or count<1: raise ValueError('Keep count must be positive')
    by_ref=defaultdict(list)
    for pipeline in pipelines: by_ref[pipeline['ref']].append(pipeline['id'])
    return {number for numbers in by_ref.values() for number in sorted(numbers,reverse=True)[:count]}


def candidate(directory, project, pipeline):
    if directory.is_symlink() or directory.resolve()!=directory: return None
    roots=list(directory.iterdir()) if directory.is_dir() else []
    roots=[root for root in roots if root.is_dir() and not root.is_symlink() and (root/'.lab/plan.json').is_file()]
    if len(roots)!=1: return None
    root=roots[0]; state=root/'.lab'
    if state.is_symlink() or (state/'plan.json').is_symlink(): return None
    plan=json.loads((state/'plan.json').read_text())
    if plan.get('project')!=project or str(plan.get('pipeline'))!=str(pipeline): return None
    if (state/'published.json').exists() or any(state.glob('deployed-*.json')): return None
    return root


def protected_mounts():
    ids=subprocess.check_output(['docker','ps','-aq'],text=True).split()
    if not ids: return []
    containers=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True))
    paths=[]
    for container in containers:
        paths.extend(Path(m['Source']).resolve() for m in container.get('Mounts',[]) if m.get('Source'))
        working=container.get('Config',{}).get('Labels',{}).get('com.docker.compose.project.working_dir')
        if working: paths.append(Path(working).resolve())
    return paths


@contextmanager
def pause_native_runner(lab, apply):
    paused=[]
    try:
        if apply:
            for runner in pages(lab,f'/groups/{lab.project["group_id"]}/runners'):
                details=lab.api('GET',f'/runners/{runner["id"]}')
                if 'lab-build' in details['tag_list'] and not details['paused']:
                    lab.api('PUT',f'/runners/{runner["id"]}',{'paused':True})
                    paused.append(runner['id'])
        yield
    finally:
        for number in paused: lab.api('PUT',f'/runners/{number}',{'paused':False})


def clean(lab, policy, apply=False):
    builds=lab.state/'build-runner/builds'
    if builds.resolve()!=builds: raise ValueError('Symlinked build root')
    projects=pages(lab,f'/groups/{lab.project["group_id"]}/projects')
    allowed=set(read_catalog())-{'myscoutee-ci'}
    mounts=protected_mounts()
    before=shutil.disk_usage(lab.state).free
    removed=[]
    with pause_native_runner(lab,apply):
        for project in projects:
            name=project['path']; pid=project['id']
            if name not in allowed: continue
            pipelines=pages(lab,f'/projects/{pid}/pipelines')
            branches={b['name'] for b in pages(lab,f'/projects/{pid}/repository/branches')}
            keep=retained([p for p in pipelines if p['ref'] in branches],policy['keep_candidates_per_branch'])
            packages=None; repositories=None
            for pipeline in pipelines:
                number=pipeline['id']; directory=builds/str(pid)/str(number)
                if number in keep or pipeline['status'] in ACTIVE: continue
                root=candidate(directory,name,number)
                if root is None or any(path==directory or directory in path.parents for path in mounts): continue
                jobs=pages(lab,f'/projects/{pid}/pipelines/{number}/jobs?include_retried=true')
                if any(job['status'] in ACTIVE for job in jobs): continue
                if any(job['status']=='success' and
                       (job['name']=='release' or job['name'].startswith('deploy:')) for job in jobs): continue
                # A paused native runner cannot acquire a new manual operation
                # between this fresh check and cancellation of this old candidate.
                print(('REMOVE' if apply else 'WOULD REMOVE')+f' {name} candidate {number}',flush=True)
                if not apply: continue
                if packages is None: packages=pages(lab,f'/projects/{pid}/packages?package_type=generic')
                if repositories is None:
                    repositories=pages(lab,f'/projects/{pid}/registry/repositories')
                    for repository in repositories:
                        repository['tags']=pages(lab,f'/projects/{pid}/registry/repositories/{repository["id"]}/tags')
                lab.api('POST',f'/projects/{pid}/pipelines/{number}/cancel')
                for package in packages:
                    if package['name']==name and package['version']==f'candidate-{number}':
                        lab.api('DELETE',f'/projects/{pid}/packages/{package["id"]}')
                for repository in repositories:
                    if repository['path'].rsplit('/',1)[-1] not in ('candidate','kvm'): continue
                    for tag in repository['tags']:
                        if re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+-'+str(number)+r'-[0-9]+',tag['name']):
                            lab.api('DELETE',f'/projects/{pid}/registry/repositories/{repository["id"]}/tags/'+urllib.parse.quote(tag['name'],safe=''))
                for job in jobs:
                    if job.get('artifacts_file') or any(a.get('file_type')!='trace' for a in job.get('artifacts',[])):
                        lab.api('DELETE',f'/projects/{pid}/jobs/{job["id"]}/artifacts')
                # No global Docker prune, VM cleanup, infra package deletion or
                # release deletion. Pipeline logs and Git history remain intact.
                shutil.rmtree(directory)
                removed.append({'project':name,'pipeline':number})
    freed=shutil.disk_usage(lab.state).free-before
    print(json.dumps({'removed':removed,'free_space_change_bytes':freed},indent=2))
    return removed


def configure(lab):
    from configure import upsert
    policy=json.loads((ROOT/'ci/retention.json').read_text())
    project=f'/projects/{lab.project["id"]}'
    upsert(lab,project,{'key':'LAB_RETENTION_STATE_DIR','protected':True},str(lab.state))
    schedules=pages(lab,project+'/pipeline_schedules')
    spec=policy['schedule']
    existing=next((s for s in schedules if s['description']==spec['description']),None)
    if existing:
        schedule=lab.api('PUT',project+'/pipeline_schedules/'+str(existing['id']),spec)
    else: schedule=lab.api('POST',project+'/pipeline_schedules',spec)
    resource=project+'/pipeline_schedules/'+str(schedule['id'])
    details=lab.api('GET',resource)
    value={'key':'LAB_MAINTENANCE','value':'retention','variable_type':'env_var'}
    if any(v['key']==value['key'] for v in details['variables']):
        lab.api('PUT',resource+'/variables/LAB_MAINTENANCE',value)
    else: lab.api('POST',resource+'/variables',value)
    print('Daily retention schedule configured:',schedule['id'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir',type=Path)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--configure',action='store_true')
    args=parser.parse_args()
    lab=LocalGitLab(args.state_dir)
    if args.configure: configure(lab)
    else: clean(lab,json.loads((ROOT/'ci/retention.json').read_text()),args.apply)
