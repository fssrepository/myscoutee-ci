#!/usr/bin/env python3
"""Reconcile declared variables from local dotenv/file inputs; never log values."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import urllib.parse

from local_gitlab import LocalGitLab, ROOT
from catalog import read_catalog


def load_env(path):
    """Literal KEY=value only: no shell execution or variable interpolation."""
    values={}
    if not path.exists(): return values
    for number,line in enumerate(path.read_text().splitlines(),1):
        line=line.strip()
        if not line or line.startswith('#'): continue
        key,sep,value=line.partition('=')
        key=key.strip()
        if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key):
            raise ValueError(f'Invalid dotenv assignment at line {number}')
        parts=shlex.split(value,comments=True)
        if len(parts)>1: raise ValueError(f'Quote dotenv values containing spaces, line {number}')
        values[key]=parts[0] if parts else ''
    return values


def resolve(item, env, directory):
    source=env.get(item.get('from_env',''),'') or item.get('value','')
    if not source:
        if item.get('required',False): raise ValueError('Missing configuration: '+(item.get('from_env') or item.get('key','input')))
        return None
    if item.get('from_file'):
        path=Path(source).expanduser()
        if not path.is_absolute(): path=directory/path
        value=path.read_text()
        return value.strip() if item.get('masked') and item.get('variable_type')!='file' else value
    return source


def upsert(lab, resource, item, value):
    scope=item.get('environment','*')
    key=item['key']
    existing=lab.api('GET',resource+'/variables?per_page=100')
    found=next((v for v in existing if v['key']==key and v.get('environment_scope','*')==scope),None)
    payload={'key':key,'value':value,'variable_type':item.get('variable_type','env_var'),
             'protected':item.get('protected',True),'masked':item.get('masked',False),'raw':True}
    if resource.startswith('/projects/'): payload['environment_scope']=scope
    elif scope!='*': raise ValueError('Use project scope for environment variables on CE')
    if found:
        if all(found.get(k)==v for k,v in payload.items()): return
        query=urllib.parse.urlencode({'filter[environment_scope]':scope})
        lab.api('PUT',resource+'/variables/'+urllib.parse.quote(key)+'?'+query,payload)
    else: lab.api('POST',resource+'/variables',payload)


def configure_branches(lab, project_id):
    resource=f'/projects/{project_id}/protected_branches'
    existing={p['name']:p for p in lab.api('GET',resource+'?per_page=100')}
    policy=json.loads((ROOT/'ci/branches.json').read_text())
    for rule in policy['protected']:
        found=existing.get(rule['name'])
        if not found:
            lab.api('POST',resource,rule)
        elif (found['allow_force_push']!=rule['allow_force_push'] or
              [v['access_level'] for v in found['push_access_levels']]!=[rule['push_access_level']] or
              [v['access_level'] for v in found['merge_access_levels']]!=[rule['merge_access_level']]):
            raise ValueError('Existing branch protection differs; review '+rule['name']+' on project '+str(project_id))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env')
    parser.add_argument('--config',type=Path,default=ROOT/'examples/variables.json')
    parser.add_argument('--provider',choices=['gitlab','github'],default='gitlab')
    parser.add_argument('--all-projects',action='store_true',help='Configure every catalog GitHub repository')
    parser.add_argument('--apply',action='store_true',help='Apply; otherwise print keys/scopes only')
    args=parser.parse_args()
    env={**load_env(args.env_file),**os.environ}
    if args.provider=='github' and not env.get('GH_TOKEN') and env.get('GITHUB_TOKEN_FILE'):
        env['GH_TOKEN']=resolve({'from_env':'GITHUB_TOKEN_FILE','from_file':True,'masked':True},env,args.env_file.resolve().parent)
    records=json.loads(args.config.read_text())[args.provider]
    workspace=Path(env.get('LAB_WORKSPACE_DIR') or ROOT.parent)
    for name,spec in read_catalog().items():
        declaration=workspace/spec.get('workspace_path',name)/'config/ci/variables.json'
        if declaration.exists():
            records.extend(dict(item,project=name) for item in json.loads(declaration.read_text()).get(args.provider,[]))
    if args.provider=='github':
        for item in records:
            if item['key']=='LAB_CI_REF':
                item.setdefault('value',subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
        if args.all_projects:
            records=[dict(item,repository=spec['variables']['LAB_GITHUB_REPOSITORY'])
                     for name,spec in read_catalog().items() for item in records
                     if not item.get('project') or item['project']==name]
    lab=LocalGitLab() if args.provider=='gitlab' else None
    if lab and (lab.state/'group-release-token').exists():
        env.setdefault('LAB_RELEASE_TOKEN_FILE',str(lab.state/'group-release-token'))
        if not env['LAB_RELEASE_TOKEN_FILE']: env['LAB_RELEASE_TOKEN_FILE']=str(lab.state/'group-release-token')
    if lab:
        group=lab.api('GET',f'/groups/{lab.project["group_id"]}')
        if args.apply:
            for project in lab.api('GET',f'/groups/{group["id"]}/projects?per_page=100'):
                configure_branches(lab,project['id'])
            from retention import configure as configure_retention
            configure_retention(lab)
        library=group['full_path']+'/'+lab.project['url'].rsplit('/',1)[-1]
        defaults={'LAB_CI_PATH':library,'LAB_CI_REF':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  'LAB_GROUP_PATH':group['full_path'],'LAB_SOURCE_BASE':lab.base+'/'+group['full_path']}
        for key,value in defaults.items():
            if args.apply: upsert(lab,f'/groups/{group["id"]}',{'key':key,'protected':False},value)
            print('gitlab group: '+key)
    # Resolve every input before mutations, including file contents.
    resolved=[(item,resolve(item,env,args.env_file.resolve().parent)) for item in records]
    for item,value in resolved:
        if value is None:
            print('Not configured: '+item['key']+' (no local input)'); continue
        if lab:
            project=item.get('project')
            resource=('/projects/'+urllib.parse.quote(group['full_path']+'/'+project,safe='')) if project else f'/groups/{group["id"]}'
            if args.apply: upsert(lab,resource,item,value)
            print('gitlab '+(project or 'group')+'/'+item.get('environment','*')+': '+item['key'])
        else:
            repository=item.get('repository') or env.get(item.get('repository_env','GITHUB_REPOSITORY'),'')
            if item.get('project') and repository.split('/')[-1]!=item['project']: continue
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):
                raise ValueError('Set GITHUB_REPOSITORY=owner/repository')
            kind='secret' if item.get('secret') else 'variable'
            command=['gh',kind,'set',item['key'],'--repo',repository]
            if item.get('environment'):
                scope=item['environment']
                command+=['--env',scope]
                if args.apply:
                    endpoint='repos/'+repository+'/environments/'+urllib.parse.quote(scope,safe='')
                    result=subprocess.run(['gh','api',endpoint],text=True,capture_output=True,env=env)
                    if result.returncode:
                        if 'HTTP 404' not in result.stderr: raise RuntimeError('GitHub environment lookup failed (details withheld)')
                        result=subprocess.run(['gh','api','--method','PUT',endpoint,'--input','-'],input='{}',text=True,capture_output=True,env=env)
                        if result.returncode: raise RuntimeError('GitHub environment creation failed (details withheld)')
            if args.apply:
                # gh encrypts secrets with the repository public key. No value
                # in argv, output, committed files or environment diagnostics.
                result=subprocess.run(command,input=value,text=True,capture_output=True,env=env)
                if result.returncode: raise RuntimeError('GitHub configuration failed for '+item['key']+' (details withheld)')
            print('github '+repository+': '+kind+' '+item['key'])


if __name__=='__main__': main()
