#!/usr/bin/env python3
"""Declare GitLab agents; install only by an explicit cluster operation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from local_gitlab import LocalGitLab, ROOT
from configure import upsert


def configure_environment(lab, project, agent, spec):
    """Bind the declared environment to its dashboard without UI setup."""
    resource=project+'/environments'
    name=spec['environment']
    existing=next((item for item in lab.api('GET',resource+'?per_page=100')
                   if item['name']==name),None)
    if not existing: existing=lab.api('POST',resource,{'name':name})
    current=lab.api('GET',resource+'/'+str(existing['id']))
    if (current.get('cluster_agent') or {}).get('id')!=agent['id'] or current.get('kubernetes_namespace')!=spec['namespace']:
        # REST only accepts agents owned by this project. Use the same mutation
        # as the UI for a shared agent, preserving its user_access authorization.
        result=lab.graphql('''mutation($input: EnvironmentUpdateInput!) {
          environmentUpdate(input: $input) { errors }
        }''',{'input':{'id':'gid://gitlab/Environment/'+str(existing['id']),
                      'clusterAgentId':'gid://gitlab/Clusters::Agent/'+str(agent['id']),
                      'kubernetesNamespace':spec['namespace']}})
        if result['environmentUpdate']['errors']:
            raise RuntimeError('Dashboard configuration failed: '+str(result['environmentUpdate']['errors']))
    return existing['id']


def dashboard(lab, project_name, config_project):
    config=json.loads((ROOT/'ci/kubernetes.json').read_text())
    name,spec=next((n,s) for n,s in config['agents'].items() if s['project']==project_name.rsplit('/',1)[-1])
    agents=lab.api('GET','/projects/'+urllib.parse.quote(str(config_project),safe='')+'/cluster_agents?per_page=100')
    agent=next(a for a in agents if a['name']==name)
    # Pod readiness is not proof of the tunnel. Wait for GitLab's connection
    # record before configuring the dashboard or reporting cluster success.
    for attempt in range(37):
        result=lab.graphql('''query($path: ID!, $name: String!) {
          project(fullPath: $path) { clusterAgent(name: $name) { connections { nodes { connectedAt } } } }
        }''',{'path':agent['config_project']['path_with_namespace'],'name':name})
        connected=(result.get('project') or {}).get('clusterAgent')
        if connected and connected['connections']['nodes']: break
        if attempt==36: raise RuntimeError('Agent is installed but not connected to GitLab; check LAB_KAS_ADDRESS and the KVM bridge listener.')
        print('Waiting for the agent connection to GitLab...',flush=True)
        time.sleep(5)
    project='/projects/'+urllib.parse.quote(project_name,safe='')
    environment_id=configure_environment(lab,project,agent,spec)
    print('Connected Kubernetes dashboard: '+lab.base+'/'+project_name+'/-/environments/'+str(environment_id))


def provision():
    os.umask(0o077)
    lab=LocalGitLab()
    group=lab.api('GET',f'/groups/{lab.project["group_id"]}')
    config=json.loads((ROOT/'ci/kubernetes.json').read_text())
    resource=f'/projects/{lab.project["id"]}/cluster_agents'
    existing={a['name']:a for a in lab.api('GET',resource+'?per_page=100')}
    directory=lab.state/'kubernetes'; directory.mkdir(mode=0o700,exist_ok=True)
    for name,spec in config['agents'].items():
        agent=existing.get(name) or lab.api('POST',resource,{'name':name})
        token_file=directory/(name+'-token')
        if not token_file.exists():
            token=lab.api('POST',resource+'/'+str(agent['id'])+'/tokens',{'name':'msc129-lab'})
            token_file.write_text(token['token']); token_file.chmod(0o600)
        project='/projects/'+urllib.parse.quote(group['full_path']+'/'+spec['project'],safe='')
        upsert(lab,project,{'key':'LAB_KUBE_AGENT_TOKEN','variable_type':'file','environment':'kvm'},token_file.read_text())
        (directory/(name+'.json')).write_text(json.dumps({'id':agent['id'],'project':spec['project']})+'\n')
        print(name+': registered; connection requires the manual cluster install')


def install(project):
    from project import required
    config=json.loads((ROOT/'ci/kubernetes.json').read_text())
    name,spec=next((n,s) for n,s in config['agents'].items() if s['project']==project.name)
    address=required('LAB_KAS_ADDRESS')
    if urllib.parse.urlsplit(address).hostname in ('localhost','127.0.0.1','::1'):
        raise ValueError('KAS address must be reachable from the guest, not guest loopback')
    support=Path(required('LAB_MICROSERVICES_SOURCE'))
    # Reuse the existing trusted transport and kubeconfig owner. No VM start here.
    project.cmd('python3',support/'tools/vm.py','kubeconfig')
    sys.path.insert(0,str(support/'tools'))
    import vm
    namespace=vm.CONFIG['namespace'] if hasattr(vm,'CONFIG') else json.loads((project.root/'config/microservices/deploy/runtime.json').read_text())['namespace']
    if namespace!=required('LAB_KUBE_NAMESPACE'): raise ValueError('Dashboard namespace differs from native runtime')
    agent_namespace='gitlab-agent-'+name
    service_account='gitlab-agent'
    items=[{'apiVersion':'v1','kind':'Namespace','metadata':{'name':agent_namespace}},
           {'apiVersion':'v1','kind':'Secret','metadata':{'name':'agent-token','namespace':agent_namespace},
            'type':'Opaque','stringData':{'token':Path(required('LAB_KUBE_AGENT_TOKEN')).read_text().strip()}},
           {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding',
            'metadata':{'name':'gitlab-agent-view','namespace':namespace},
            'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'ClusterRole','name':'view'},
            'subjects':[{'kind':'ServiceAccount','name':service_account,'namespace':agent_namespace}]}]
    # Agent self-registration/leader election is confined to its own namespace.
    items.extend([
        {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'Role',
         'metadata':{'name':'agent-runtime','namespace':agent_namespace},
         'rules':[{'apiGroups':[''],'resources':['pods'],'verbs':['get','list','watch','patch']},
                  {'apiGroups':['coordination.k8s.io'],'resources':['leases'],'verbs':['get','create','update']}]},
        {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding',
         'metadata':{'name':'agent-runtime','namespace':agent_namespace},
         'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'Role','name':'agent-runtime'},
         'subjects':[{'kind':'ServiceAccount','name':service_account,'namespace':agent_namespace}]}])
    command=vm.ssh_command('sudo k3s kubectl apply -f -')
    result=subprocess.run(command,input=json.dumps({'apiVersion':'v1','kind':'List','items':items}),text=True,capture_output=True)
    if result.returncode: raise RuntimeError('Agent resources failed to apply; secret-bearing output withheld')
    chart=config['chart']; archive=project.state/'gitlab-agent.tgz'
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest()!=chart['sha256']:
        with urllib.request.urlopen(chart['url'],timeout=60) as response: content=response.read()
        if hashlib.sha256(content).hexdigest()!=chart['sha256']: raise ValueError('Agent chart checksum mismatch')
        archive.write_bytes(content)
    values={'image':{'tag':chart['agentVersion']},'replicas':1,
            'config':{'kasAddress':address,'secretName':'agent-token'},
            'rbac':{'create':False},'serviceAccount':{'create':True,'name':service_account}}
    file=project.state/'agent-values.json'; file.write_text(json.dumps(values))
    project.cmd('bash',support/'tools/helm.sh','upgrade','--install',name,archive,
        '--namespace',agent_namespace,'-f',file,'--wait','--timeout','180s')
    dashboard(LocalGitLab(base=required('CI_SERVER_URL'),token=required('LAB_RELEASE_TOKEN')),
              required('CI_PROJECT_PATH'),required('LAB_KUBE_CONTEXT').rsplit(':',1)[0])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['provision','dashboard'])
    parser.add_argument('--project',help='Full GitLab project path for an already installed agent')
    args=parser.parse_args()
    if args.action=='provision': provision()
    else:
        if not args.project: parser.error('dashboard requires --project')
        lab=LocalGitLab()
        dashboard(lab,args.project,lab.project['id'])
