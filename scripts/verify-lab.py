#!/usr/bin/env python3
"""Check the actual local GitLab configuration; optionally prove registry I/O."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.parse
from local_gitlab import LocalGitLab, ROOT
from catalog import read_catalog


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry-smoke',action='store_true')
    parser.add_argument('--pipeline-smoke',action='store_true',help='Run the small roadmap source pipeline, stopping at its publish gate')
    parser.add_argument('--ref',help='Also validate a feature branch after it has been pushed')
    args=parser.parse_args()
    lab=LocalGitLab()
    for file in ('.gitlab-ci.yml','ci/project.gitlab-ci.yml'):
        result=lab.api('POST',f'/projects/{lab.project["id"]}/ci/lint',{'content':(ROOT/file).read_text(),'include_jobs':True})
        if not result['valid']: raise ValueError(file+': '+json.dumps(result['errors']))
        print(file+': GitLab CI lint passed')
    projects=lab.api('GET',f'/groups/{lab.project["group_id"]}/projects?per_page=100')
    by_name={p['path']:p for p in projects}
    for name,spec in read_catalog().items():
        project=by_name['ci' if name=='myscoutee-ci' else name]
        source=ROOT.parent/spec.get('workspace_path',name)
        result=lab.api('POST',f'/projects/{project["id"]}/ci/lint',{
            'content':(source/'config/ci/pipeline.yml').read_text(),'dry_run':True,
            'ref':project['default_branch'],'include_jobs':True})
        if not result['valid']: raise ValueError(name+': '+json.dumps(result['errors']))
        print(name+': versioned config/ci entry passed GitLab lint')
        if spec['type'] not in ('application','frontend'): continue
        jobs={job['name']:job for job in result['jobs']}
        # CI lint's job summaries omit needs. Parse its merged YAML with the
        # Ruby/YAML already bundled in the pinned GitLab image.
        merged=json.loads(subprocess.check_output(['docker','compose','exec','-T','gitlab',
            '/opt/gitlab/embedded/bin/ruby','-ryaml','-rjson','-e',
            'puts JSON.generate(YAML.safe_load(STDIN.read, aliases: true))'],
            input=result['merged_yaml'],text=True,cwd=ROOT))
        manual=['test','release']
        if jobs['build']['when']!='on_success': raise ValueError(name+': normal build must be automatic')
        if merged['workflow'].get('auto_cancel',{}).get('on_new_commit')!='interruptible':
            raise ValueError(name+': superseded automatic work must be interruptible')
        if merged['build'].get('resource_group')!='project-build':
            raise ValueError(name+': builds must be serialized per project')
        for phase in ('prepare','dependencies','build'):
            if merged[phase].get('interruptible') is not True:
                raise ValueError(name+': automatic work is not interruptible: '+phase)
        if merged['default'].get('interruptible') is not False:
            raise ValueError(name+': manual publication/deployment must not be auto-canceled')
        manual+=['deploy:github'] if spec['type']=='frontend' else ['package:deb','package:kvm','deploy:kvm','deploy:vmware','deploy:monolith','deploy:netcup','infra:start','deploy:agent']
        for job in manual:
            if job not in jobs or jobs[job]['when']!='manual': raise ValueError(name+': missing manual gate '+job)
        for job in jobs.values():
            if job['name'].startswith('deploy:'):
                definition=merged[job['name']]
                inherited=merged.get(definition.get('extends',''),{})
                needs={n if isinstance(n,str) else n.get('job',n.get('name')) for n in definition.get('needs',inherited.get('needs',[]))}
                if 'release' in needs or ('deploy:kvm' if job['name']=='deploy:agent' else 'build') not in needs: raise ValueError('Deploy must depend on build, independently of release')
        print(name+': manual gates and independent deployment verified')
        if args.ref:
            feature=lab.api('POST',f'/projects/{project["id"]}/ci/lint',{
                'content':(source/'config/ci/pipeline.yml').read_text(),'dry_run':True,
                'ref':args.ref,'include_jobs':True})
            if not feature['valid']: raise ValueError(name+': '+json.dumps(feature['errors']))
            feature_jobs={job['name']:job for job in feature['jobs']}
            for forbidden in ('release','downstream','deploy:github','deploy:netcup','deploy:monolith','deploy:kvm'):
                if forbidden in feature_jobs: raise ValueError(name+': feature branch can publish/deploy production via '+forbidden)
            if feature_jobs['build']['when']!='on_success': raise ValueError('Feature normal build must be automatic')
            if spec['type']=='application' and feature_jobs.get('deploy:vmware',{}).get('when')!='manual':
                raise ValueError(name+': feature VMware manual gate absent')
            print(name+': feature build/VMware allowed; publication absent')
    runners=lab.api('GET',f'/groups/{lab.project["group_id"]}/runners')
    print('Group projects:',len(projects),'runners:',len(runners))
    if args.pipeline_smoke:
        project=by_name['myscoutee-roadmap']
        pipeline=lab.api('POST',f'/projects/{project["id"]}/pipeline',{'ref':project['default_branch']})
        print('Source pipeline:',pipeline['web_url'],flush=True)
        for _ in range(120):
            jobs=lab.api('GET',f'/projects/{project["id"]}/pipelines/{pipeline["id"]}/jobs?per_page=100')
            phases={j['name']:j['status'] for j in jobs}
            if any(phases.get(name)=='failed' for name in ('prepare','dependencies','build')):
                raise ValueError('Source pipeline failed: '+pipeline['web_url'])
            if all(phases.get(name)=='success' for name in ('prepare','dependencies','build')):
                if phases.get('release')!='manual': raise ValueError('Publication did not stop at manual gate')
                print('Source prepare/dependencies/build passed; publish waits for a click.')
                break
            time.sleep(2)
        else: raise ValueError('Source pipeline still pending: '+pipeline['web_url'])
    if args.registry_smoke:
        project=lab.api('GET',f'/projects/{lab.project["id"]}')
        image=project['container_registry_image_prefix']+'/verification:local'
        registry=image.split('/')[0]
        with tempfile.TemporaryDirectory(dir=lab.state,prefix='registry-check-') as temporary:
            folder=Path(temporary); auth=folder/'auth'; auth.mkdir(mode=0o700)
            env=dict(os.environ,DOCKER_CONFIG=str(auth))
            (folder/'Dockerfile').write_text('FROM scratch\nCOPY probe.txt /probe.txt\n')
            (folder/'probe.txt').write_text('MyScoutee local registry verification\n')
            def run(*command,**kwargs): return subprocess.run(command,env=env,cwd=folder,check=True,**kwargs)
            run('docker','login',registry,'--username','root','--password-stdin',input=lab.token+'\n',text=True,capture_output=True)
            run('docker','build','--network=none','-t',image,'.',capture_output=True)
            before=run('docker','image','inspect','--format','{{.Id}}',image,capture_output=True,text=True).stdout.strip()
            run('docker','push',image,capture_output=True)
            run('docker','pull',image,capture_output=True)
            after=run('docker','image','inspect','--format','{{.Id}}',image,capture_output=True,text=True).stdout.strip()
            if before!=after: raise ValueError('Registry changed image identity')
            print('Local Container Registry push/pull verified:',image)


if __name__=='__main__': main()
