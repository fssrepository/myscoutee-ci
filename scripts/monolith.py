"""Deploy the immutable candidate with the product's existing local Compose lab."""
import json
import os
import re


def deploy(project):
    spec=json.loads((project.root/'config/ci/monolith.json').read_text())
    name=os.environ.get('LAB_MONOLITH_PROJECT',spec['project'])
    if not re.fullmatch(r'[a-z][a-z0-9-]+',name): raise ValueError('Invalid monolith project name')
    source=project.root/spec['compose']
    config=json.loads(project.cmd('docker','compose','-f',source,'config','--format','json',capture=True))
    config['name']=name
    inventory={i['service']:i for i in json.loads((project.state/'images.json').read_text())}
    for section in ('volumes','networks'):
        for key,value in config.get(section,{}).items():
            if value.get('external'): raise ValueError('Local CI lab cannot adopt external '+section)
            value['name']=name+'_'+key
    build=[]
    for service,value in config['services'].items():
        value['container_name']=name+'-'+service
        image=spec['images'].get(service)
        if image:
            value['image']=inventory[image]['imageId']
            value.pop('build',None)
        elif value.get('build'):
            # Only the owner's support/seed image is assembled here. Application
            # binaries are the exact normal-build artifacts, never rebuilt.
            value['image']=name+'-'+service+':'+project.release['version']
            build.append(service)
        value['restart']='no'
    api=config['services']['profilemanagement']
    api['environment'].update(spec.get('apiEnvironment',{}))
    mounts=[('server/docker/scripts/ensure_operator_configuration_master_key.sh','/usr/local/bin/ensure-operator-configuration-key'),
            ('server/docker/images/profilemanagement/e2e/entrypoint.sh','/usr/local/bin/myscoutee-e2e-entrypoint')]
    for relative,target in mounts:
        source=project.root/relative
        if source.is_symlink() or not source.is_file():
            raise ValueError('Expected a regular public entrypoint: '+relative)
        # The private runner checkout uses umask 077; the application's distinct
        # container UID must be able to read/execute these two public scripts.
        source.chmod(0o755)
        api.setdefault('volumes',[]).append({'type':'bind','source':str(source),'target':target,'read_only':True})
    api['entrypoint']=['/bin/sh','/usr/local/bin/myscoutee-e2e-entrypoint']
    # Production candidates do not bake the E2E writable key directory into
    # their image. Reuse the owner's directory initializer for this volume;
    # never run the application as root or change existing key contents.
    owner=project.cmd('docker','image','inspect','--format','{{.Config.User}}',api['image'],capture=True)
    if not re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*',owner):
        raise ValueError('Monolith candidate must declare a numeric non-root UID:GID')
    uid,gid=owner.split(':')
    initializer=project.root/'server/docker/scripts/prepare_dev_runtime_directories.sh'
    if initializer.is_symlink() or not initializer.is_file():
        raise ValueError('Expected the public runtime directory initializer')
    initializer.chmod(0o755)
    configuration=next(v for v in api['volumes'] if v['target']=='/etc/myscoutee/configuration')
    if configuration['type']!='volume': raise ValueError('Monolith configuration requires an owned named volume')
    config['services']['runtime-directories']={
        'image':api['image'],'user':'0:0','network_mode':'none','restart':'no',
        'read_only':True,'cap_drop':['ALL'],'cap_add':['CHOWN','FOWNER','DAC_OVERRIDE'],
        'security_opt':['no-new-privileges:true'],
        'entrypoint':['/bin/sh','/prepare-runtime-directories.sh','/etc/myscoutee'],
        'environment':{'MYSCOUTEE_RUNTIME_UID':uid,'MYSCOUTEE_RUNTIME_GID':gid,
                       'MYSCOUTEE_RUNTIME_DIRECTORIES':'configuration'},
        'volumes':[configuration,{'type':'bind','source':str(initializer),
                    'target':'/prepare-runtime-directories.sh','read_only':True}]}
    api.setdefault('depends_on',{})['runtime-directories']={'condition':'service_completed_successfully'}
    nginx=config['services']['nginx']
    nginx['entrypoint']=['/scripts/nginx-e2e-entrypoint.sh']; nginx['command']=[]
    http=int(os.environ.get('LAB_MONOLITH_HTTP_PORT',spec['httpPort']))
    https=int(os.environ.get('LAB_MONOLITH_HTTPS_PORT',spec['httpsPort']))
    stun=int(os.environ.get('LAB_MONOLITH_STUN_PORT',spec['stunPort']))
    if any(not 1024<=p<=65535 for p in (http,https,stun)): raise ValueError('Invalid local lab port')
    spring=(project.root/'config/nginx/http/spring.conf').read_text()
    redirect='return 308 https://$server_name$request_uri;'
    if spring.count(redirect)!=1: raise ValueError('Expected the canonical HTTPS redirect in the monolith configuration')
    rendered=project.state/'monolith.spring.conf'
    rendered.write_text(spring.replace(redirect,f'return 308 https://$server_name:{https}$request_uri;'))
    rendered.chmod(0o644)
    nginx.setdefault('volumes',[]).append({'type':'bind','source':str(rendered),
        'target':'/etc/nginx/conf.d/spring.conf','read_only':True})
    nginx['ports']=[{'target':80,'published':str(http),'host_ip':'127.0.0.1','protocol':'tcp'},
                    {'target':443,'published':str(https),'host_ip':'127.0.0.1','protocol':'tcp'}]
    config['services']['stun']['ports']=[{'target':3478,'published':str(stun),'host_ip':'127.0.0.1','protocol':p} for p in ('tcp','udp')]
    api['environment']['CHAT_CALL_STUN_PORT']=str(stun)
    api['environment']['WEBSOCKET_ALLOWED_ORIGIN_PATTERNS']=f'https://localhost:{https},https://127.0.0.1:{https}'
    file=project.state/'monolith.compose.json'; file.write_text(json.dumps(config,indent=2)+'\n'); file.chmod(0o600)
    compose=['docker','compose','-f',file]
    if build: project.cmd(*compose,'build',*build)
    project.cmd(*compose,'up','--no-build','--wait','--wait-timeout','300')
    # Inspect every managed service; Compose health alone does not prove that
    # the running stack uses the candidate's image identities.
    for service,image in spec['images'].items():
        actual=project.cmd('docker','inspect','--format','{{.Image}}',name+'-'+service,capture=True)
        if actual!=inventory[image]['imageId']: raise ValueError('Running image differs: '+service)
    certificate=project.state/'monolith-ca.pem'
    project.cmd('docker','cp',name+'-nginx:/etc/nginx/keys/nginx.crt',certificate)
    (project.state/'deployed-monolith.json').write_text(json.dumps({'target':'monolith','version':project.release['version'],
        'installed':True,'project':name,'url':f'https://localhost:{https}',
        'httpUrl':f'http://localhost:{http}','certificate':str(certificate)})+'\n')
