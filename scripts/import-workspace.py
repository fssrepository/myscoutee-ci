#!/usr/bin/env python3
"""Create private group projects and import committed branches/tags once."""
import argparse
from pathlib import Path
import subprocess
from catalog import read_catalog
from local_gitlab import LocalGitLab, ROOT
from configure import configure_branches


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace',type=Path)
    parser.add_argument('--create-only',action='store_true')
    parser.add_argument('--update',action='store_true',help='Fast-forward selected local mirrors from committed workspace HEADs')
    parser.add_argument('--project',action='append',help='Select catalog project(s)')
    args=parser.parse_args()
    lab=LocalGitLab()
    group=lab.api('GET',f'/groups/{lab.project["group_id"]}')
    projects=lab.api('GET',f'/groups/{group["id"]}/projects?per_page=100')
    by_name={p['path']:p for p in projects}
    env=lab.git_environment()
    for name,spec in read_catalog().items():
        if name=='myscoutee-ci': continue
        if args.project and name not in args.project: continue
        project=by_name.get(name)
        if project is None:
            project=lab.api('POST','/projects',{'namespace_id':group['id'],'name':name,'path':name,
                'visibility':'private','initialize_with_readme':False,'default_branch':'master'})
        # Configure the project before its first push, so that the push creates
        # the declared pipeline rather than Auto DevOps or an empty pipeline.
        lab.api('PUT',f'/projects/{project["id"]}',{'ci_config_path':'config/ci/pipeline.yml','auto_devops_enabled':False})
        configure_branches(lab,project['id'])
        existing=lab.api('GET',f'/projects/{lab.project["id"]}/job_token_scope/allowlist?per_page=100')
        if project['id'] not in [p['id'] for p in existing]:
            lab.api('POST',f'/projects/{lab.project["id"]}/job_token_scope/allowlist',{'target_project_id':project['id']})
        allowed=lab.api('GET',f'/projects/{project["id"]}/job_token_scope/groups_allowlist')
        if group['id'] not in [item['id'] for item in allowed]:
            lab.api('POST',f'/projects/{project["id"]}/job_token_scope/groups_allowlist',{'target_group_id':group['id']})
        variables=lab.api('GET',f'/projects/{project["id"]}/variables?per_page=100')
        for key in ('LAB_APPLICATION','LAB_FRONTEND','LAB_HEAVY_BUILD','LAB_GITHUB_REPOSITORY'):
            if key in {v['key'] for v in variables}:
                lab.api('DELETE',f'/projects/{project["id"]}/variables/{key}')
        if not args.create_only:
            source=(args.workspace/spec.get('workspace_path',name)).resolve()
            if not (source/'.git').exists():
                print(name+': project created; source checkout unavailable'); continue
            branches=lab.api('GET',f'/projects/{project["id"]}/repository/branches?per_page=1')
            if not branches or args.update:
                # No working files, ignored files, credentials, reset or force.
                result=subprocess.run(['git','-C',str(source),'symbolic-ref','--short','HEAD'],capture_output=True,text=True)
                branch=result.stdout.strip() if result.returncode==0 else 'master'
                url=lab.base+'/'+group['full_path']+'/'+name+'.git'
                subprocess.run(['git','-C',str(source),'-c','credential.helper=','push',
                    url,'HEAD:refs/heads/'+branch,'--tags'],env=env,check=True,
                    stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        print(name+': private group project configured')
    print('Source pushes start the configured pipeline; expensive work remains behind manual gates.')


if __name__=='__main__': main()
