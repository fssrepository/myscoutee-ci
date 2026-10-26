#!/usr/bin/env python3
"""Granular CI adapter. Product build, packaging and deployment stay with owners."""
import base64
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import shutil
import tarfile
import time
import urllib.parse
import urllib.request

from catalog import read_catalog, consumers
from version import plan, VERSION, release_kind
import terraform_module


def required(name):
    value = os.environ.get(name, '')
    if not value:
        raise ValueError('Missing CI/CD variable: '+name)
    return value


def run(*args, cwd=None, capture=False, **kwargs):
    result = subprocess.run([str(a) for a in args], cwd=cwd, check=True,
                            text=True, capture_output=capture, **kwargs)
    return result.stdout.strip() if capture else ''


def digest(path):
    checksum=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): checksum.update(chunk)
    return checksum.hexdigest()


def api(method, endpoint, payload=None, token=None):
    credential = token or required('LAB_RELEASE_TOKEN')
    req = urllib.request.Request(required('CI_API_V4_URL')+endpoint, method=method,
        headers={'PRIVATE-TOKEN':credential, 'Content-Type':'application/json'},
        data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.load(response)


class Project:
    def __init__(self):
        self.root = Path(os.environ.get('CI_PROJECT_DIR', Path.cwd())).resolve()
        self.name = required('CI_PROJECT_NAME')
        self.projects = read_catalog()
        self.spec = self.projects[self.name]
        descriptor=self.root/'config/ci/project.json'
        if descriptor.exists():
            local=json.loads(descriptor.read_text())
            expected={'project':self.name,**{k:v for k,v in self.spec.items() if k!='workspace_path'}}
            if local!=expected: raise ValueError('Project CI metadata differs from the pinned catalog; update both together')
        self.kind = self.spec['type']
        self.state = self.root/'.lab'
        self.dist = self.state/'dist'
        self.state.mkdir(exist_ok=True)
        self.dist.mkdir(exist_ok=True)
        self.plan_file = self.state/'plan.json'
        self.release = json.loads(self.plan_file.read_text()) if self.plan_file.exists() else None
        self.packaging = self.root/'config/packaging/node_modules/@fssrepository/myscoutee-packaging'
        if self.release:
            os.environ['MYSCOUTEE_VERSION'] = self.release['version']
            os.environ['MYSCOUTEE_DIST_DIR'] = str(self.dist)
        if os.environ.get('LAB_NPMRC'):
            os.environ['NPM_CONFIG_USERCONFIG'] = os.environ['LAB_NPMRC']
        if os.environ.get('LAB_GRADLE_PROPERTIES'):
            os.environ['MYSCOUTEE_GITHUB_PACKAGES_PROPERTIES'] = os.environ['LAB_GRADLE_PROPERTIES']
            for line in Path(os.environ['LAB_GRADLE_PROPERTIES']).read_text().splitlines():
                key,separator,value=line.partition('=')
                if separator and key.strip() in ('gpr.user','gpr.key'):
                    os.environ['ORG_GRADLE_PROJECT_'+key.strip()]=value.strip()
                    # npm runs packaging through /bin/sh, which drops dotted
                    # environment names. All workspace Maven consumers already
                    # support these portable aliases; no personal Gradle home.
                    alias={'gpr.user':'GITHUB_ACTOR','gpr.key':'GITHUB_TOKEN'}[key.strip()]
                    os.environ[alias]=value.strip()
        docker=self.state/'docker-auth'; docker.mkdir(exist_ok=True,mode=0o700)
        if os.environ.get('LAB_DOCKER_CONFIG'):
            shutil.copyfile(os.environ['LAB_DOCKER_CONFIG'],docker/'config.json')
            (docker/'config.json').chmod(0o600)
        os.environ['DOCKER_CONFIG']=str(docker)
        if os.environ.get('CI_JOB_TOKEN'):
            helper=self.state/'source-askpass'
            helper.write_text('#!/bin/sh\ncase "$1" in *Username*) echo gitlab-ci-token;; *) printf "%s\\n" "$CI_JOB_TOKEN";; esac\n')
            helper.chmod(0o700)
            os.environ.update(GIT_ASKPASS=str(helper),GIT_TERMINAL_PROMPT='0')
        os.environ['MYSCOUTEE_BACKEND_SOURCE']=str(self.root)
        support=self.root.parent/'myscoutee-microservices'
        if support.exists():
            os.environ['LAB_MICROSERVICES_SOURCE']=str(support)
            os.environ['MYSCOUTEE_MICROSERVICES_SOURCE']=str(support)

    def cmd(self, *args, cwd=None, **kwargs):
        return run(*args, cwd=cwd or self.root, **kwargs)

    def npm(self, directory, *args):
        return self.cmd('npm', '--prefix', directory, *args)

    def packaging_command(self, *args):
        self.npm('config/packaging', 'run', *args)

    def prepare(self):
        # Pipeline trees are isolated; .lab never becomes a release source file.
        exclude = Path(self.cmd('git','rev-parse','--git-path','info/exclude',capture=True))
        if not exclude.is_absolute(): exclude = self.root/exclude
        exclude.parent.mkdir(parents=True,exist_ok=True)
        with exclude.open('a') as stream: stream.write('\n/.lab/\n')
        if self.spec.get('frontend'):
            self.cmd('git','config','submodule.frontend.url',required('LAB_SOURCE_BASE').rstrip('/')+'/'+self.spec['frontend']+'.git')
        self.cmd('git','-c','credential.helper=','submodule','update','--init','--recursive')
        baseline = os.environ.get('LAB_BASE_VERSION')
        if not baseline and (self.root/'VERSION').exists(): baseline=(self.root/'VERSION').read_text().strip()
        if not baseline and (self.root/'package.json').exists(): baseline=json.loads((self.root/'package.json').read_text()).get('version')
        tags = self.cmd('git','tag','--list','v*',capture=True).splitlines()
        stable = [t[1:] for t in tags if VERSION.fullmatch(t[1:])]
        if not baseline and stable: baseline=max(stable,key=lambda x:tuple(map(int,x.split('.'))))
        if not baseline: baseline='0.0.0'
        title = os.environ.get('CI_COMMIT_TITLE','').split('\n')[0]
        level = release_kind(title) or os.environ.get('LAB_RELEASE_LEVEL','patch')
        self.release = plan(baseline,tags,'release: '+level)
        self.release.update(project=self.name, type=self.kind,
                            source=self.cmd('git','rev-parse','HEAD',capture=True),
                            pipeline=required('CI_PIPELINE_ID'))
        if self.kind != 'application': self.release['delivery'] = self.kind
        self.plan_file.write_text(json.dumps(self.release,indent=2)+'\n')
        # Versions change only in the isolated pipeline tree. Release tags will
        # contain this exact tested source, including updated dependency locks.
        for filename in ['package.json','package-lock.json']:
            path=self.root/filename
            if path.exists() and self.kind in ('npm','angular-library','frontend'):
                data=json.loads(path.read_text()); data['version']=self.release['version']
                if '' in data.get('packages',{}): data['packages']['']['version']=self.release['version']
                path.write_text(json.dumps(data,indent=2)+'\n')
        if (self.root/'VERSION').exists(): (self.root/'VERSION').write_text(self.release['version']+'\n')
        if self.kind == 'java-base':
            path=self.root/'server/gradle.properties'
            path.write_text(re.sub(r'^version=.*$', 'version='+self.release['version'],path.read_text(),flags=re.M))
        if self.kind=='application':
            path=self.root/'server/.env'
            # The template owns a versioned example; its runtime .env is ignored.
            # Update the versioned owner too so the release tag reproduces it.
            source=path if path.exists() else path.with_name('.env.example')
            value,count=re.subn(r'^MYSCOUTEE_VERSION=.*$', 'MYSCOUTEE_VERSION='+self.release['version'],source.read_text(),flags=re.M)
            if count!=1: raise ValueError('Expected one application version owner in server/.env')
            source.write_text(value)
            path.write_text(value)
        print(json.dumps(self.release,indent=2))

    def fixtures(self):
        fixtures = json.loads(os.environ.get('LAB_FIXTURES','{}'))
        upstream=os.environ.get('LAB_UPSTREAM_PROJECT')
        if upstream in self.spec.get('fixtures',[]): fixtures[upstream]=required('LAB_UPSTREAM_REVISION')
        for name in self.spec.get('fixtures',[]):
            # These are exact integration fixtures, not publication dependencies.
            revision = fixtures.get(name)
            if not revision or not re.fullmatch(r'[a-f0-9]{40}',revision):
                raise ValueError('LAB_FIXTURES must pin a source commit for '+name)
            target=self.root.parent/name
            if not target.exists(): self.cmd('git','-c','credential.helper=','clone',required('LAB_SOURCE_BASE').rstrip('/')+'/'+name+'.git',target)
            self.cmd('git','checkout','--detach',revision,cwd=target)

    def dependencies(self):
        self.consume_upstream()
        revision=os.environ.get('LAB_MICROSERVICES_REVISION')
        if self.kind=='application' and revision:
            if not re.fullmatch(r'[a-f0-9]{40}',revision): raise ValueError('Pin LAB_MICROSERVICES_REVISION to a commit')
            target=self.root.parent/'myscoutee-microservices'
            if not target.exists(): self.cmd('git','-c','credential.helper=','clone',required('LAB_SOURCE_BASE')+'/myscoutee-microservices.git',target)
            self.cmd('git','checkout','--detach',revision,cwd=target)
        if self.kind in ('npm','angular-library','frontend'):
            self.npm('.', 'ci','--ignore-scripts','--no-audit','--no-fund')
        if self.kind == 'application':
            for directory in ('frontend','config/packaging','tests/e2e','tests/qa'):
                if (self.root/directory/'package-lock.json').exists():
                    self.npm(directory,'ci','--ignore-scripts','--no-audit','--no-fund')
        if self.kind == 'go-image':
            print('Go build dependencies are owned by the multi-stage Dockerfile; host Go is required only for optional tests.')
        inputs={'source':self.release['source'],'version':self.release['version']}
        if os.environ.get('LAB_UPSTREAM_PROJECT'):
            inputs['upstream']={key.removeprefix('LAB_UPSTREAM_').lower():os.environ[key]
                for key in ('LAB_UPSTREAM_PROJECT','LAB_UPSTREAM_VERSION','LAB_UPSTREAM_REVISION','LAB_UPSTREAM_IMAGE') if key in os.environ}
        support=self.root.parent/'myscoutee-microservices'
        if self.kind=='application' and support.exists():
            inputs['microservices']=self.cmd('git','rev-parse','HEAD',cwd=support,capture=True)
        (self.dist/(self.name+'-build-inputs.json')).write_text(json.dumps(inputs,indent=2)+'\n')

    def consume_upstream(self):
        upstream=os.environ.get('LAB_UPSTREAM_PROJECT')
        if not upstream: return
        if upstream not in self.spec['depends_on']: raise ValueError('Unexpected upstream project')
        version=required('LAB_UPSTREAM_VERSION')
        if not VERSION.fullmatch(version): raise ValueError('Invalid upstream version')
        event_type=self.projects[upstream]['type']
        if event_type in ('npm','angular-library'):
            package=required('LAB_UPSTREAM_PACKAGE')
            changed=False
            for directory in ('.','frontend','config/packaging','tests/e2e','tests/qa'):
                path=self.root/directory/'package.json'
                if not path.exists(): continue
                data=json.loads(path.read_text())
                for section in ('dependencies','devDependencies'):
                    if package in data.get(section,{}):
                        data[section][package]=version; changed=True
                        path.write_text(json.dumps(data,indent=2)+'\n')
                        self.npm(directory,'install','--package-lock-only','--ignore-scripts','--no-audit','--no-fund')
            if not changed: raise ValueError('Upstream npm package is not declared by consumer')
        elif event_type=='java-base':
            path=self.root/'server/gradle/libs.versions.toml'
            text,count=re.subn(r'^base\s*=\s*"[^"]+"',f'base = "{version}"',path.read_text(),flags=re.M)
            if count!=1: raise ValueError('Expected exactly one base version owner')
            path.write_text(text)
        elif event_type=='frontend':
            revision=required('LAB_UPSTREAM_REVISION')
            if not re.fullmatch(r'[a-f0-9]{40}',revision): raise ValueError('Invalid frontend commit')
            url=required('LAB_SOURCE_BASE').rstrip('/')+'/'+upstream+'.git'
            self.cmd('git','fetch',url,revision,cwd=self.root/'frontend')
            self.cmd('git','checkout','--detach',revision,cwd=self.root/'frontend')
        elif event_type in ('go-image','nginx-image'):
            image=required('LAB_UPSTREAM_IMAGE')
            if not re.fullmatch(r'[a-z0-9./:_-]+@sha256:[a-f0-9]{64}',image): raise ValueError('Dependency image must be digest-pinned')
            runtime=self.root/'config/microservices/deploy/runtime.json'
            data=json.loads(runtime.read_text())
            if upstream=='myscoutee-nginx':
                settings=self.root/'config/packaging/release/settings.json'
                config=json.loads(settings.read_text()); config['build']['nginxNativeImage']=image
                settings.write_text(json.dumps(config,indent=2)+'\n')
                data['images']['nginxBase']=image
            elif upstream=='myscoutee-mcp':
                path=self.root/'server/docker/images/mcp/Dockerfile'
                value,count=re.subn(r'^ARG MCP_BASE_IMAGE=.+$', 'ARG MCP_BASE_IMAGE='+image,path.read_text(),flags=re.M)
                if count!=1: raise ValueError('Missing MCP base image owner')
                path.write_text(value)
            else:
                service={'myscoutee-registry':'registry','myscoutee-payment-simulator':'payment-simulator'}[upstream]
                variable={'registry':'REGISTRY_DEMO_IMAGE','payment-simulator':'PAYMENT_SIMULATOR_IMAGE'}[service]
                data['dependencies'][service]=image
                for filename in ('server/docker-compose-prod.yml','config/packaging/compose/docker-compose.production.yml'):
                    path=self.root/filename
                    text,count=re.subn(r'\$\{'+variable+r':-[^}]+\}',lambda _: '${'+variable+':-'+image+'}',path.read_text())
                    if count!=1: raise ValueError('Missing image default in '+filename)
                    path.write_text(text)
            runtime.write_text(json.dumps(data,indent=2)+'\n')
        elif upstream=='myscoutee-microservices':
            os.environ['LAB_MICROSERVICES_REVISION']=required('LAB_UPSTREAM_REVISION')
        elif upstream=='myscoutee-skills':
            fixtures=json.loads(os.environ.get('LAB_FIXTURES','{}'))
            fixtures[upstream]=required('LAB_UPSTREAM_REVISION')
            os.environ['LAB_FIXTURES']=json.dumps(fixtures)
        else:
            raise ValueError('No dependency binding for '+upstream)

    def test(self):
        (self.state/'tests.json').unlink(missing_ok=True)
        self.fixtures()
        if self.kind in ('npm','angular-library'):
            data=json.loads((self.root/'package.json').read_text())
            if 'check' in data.get('scripts',{}): self.npm('.','run','check')
            self.npm('.','test')
            if 'test:package' in data.get('scripts',{}): self.npm('.','run','test:package')
        elif self.kind=='frontend': self.npm('.','test','--','--watch=false')
        elif self.kind=='go-image':
            self.cmd('go','test','-race',*(['-p','1'] if self.name=='myscoutee-registry' else []),'./...')
        elif self.kind=='java-base': self.cmd('./gradlew','--no-daemon','--parallel','check',cwd=self.root/'server')
        elif self.kind=='java-client': self.cmd('./gradlew','--no-daemon','check')
        elif self.kind=='python-deb': self.cmd('python3','-m','unittest','discover','-s','tests','-v')
        elif self.kind=='application':
            support=Path(required('LAB_MICROSERVICES_SOURCE')).resolve()
            self.cmd('bash',support/'tools/run-backend-junit.sh','standard')
            self.cmd(str(support/'gradlew'),'--no-daemon',':bootstrap-tests:test')
            self.npm('frontend','test','--','--watch=false')
            self.packaging_command('seed-parity')
        elif self.kind=='nginx-image':
            image=required('LAB_IMAGE_NAMESPACE').rstrip('/')+'/'+self.name+':'+self.release['version']
            environment=dict(os.environ,NGINX_NATIVE_TEST_IMAGE=image)
            for test in ('runtime-credential-test.py','edge-test.py','kubernetes-test.py','route-inventory-test.py','native-test.py'):
                self.cmd('python3','tests/'+test,env=environment)
        else:
            self.cmd('git','diff','--check')
            print('Source-release policy: no application runtime/test claim.')
        (self.state/'tests.json').write_text(json.dumps({'status':'passed','pipeline':self.release['pipeline']})+'\n')

    def build(self):
        version=self.release['version']
        if self.kind=='angular-library':
            self.npm('.','run','build')
            self.npm('.','run','prepare:release')
        elif self.kind=='frontend':
            self.npm('.','run','build:prod')
            # Pages reflects the released source version, not the next candidate.
            self.cmd('npm','--prefix','.','run','build:github',
                env=dict(os.environ,MYSCOUTEE_VERSION=self.release['previous']))
        elif self.kind=='java-base': self.cmd('./gradlew','--no-daemon','--parallel','publishRelease','releaseArchive','-x','test',cwd=self.root/'server')
        elif self.kind=='java-client': self.cmd('./gradlew','--no-daemon','releaseArchive','distZip','distTar','-x','test')
        elif self.kind=='python-deb':
            self.cmd('python3','guides/manuals/build_pdf.py')
            self.cmd('bash','packaging/build_deb.sh')
        elif self.kind in ('go-image','nginx-image'):
            image=required('LAB_IMAGE_NAMESPACE').rstrip('/')+'/'+self.name+':'+version
            self.cmd('docker','build','--network',os.environ.get('LAB_DOCKER_BUILD_NETWORK','default'),
                     '--build-arg','MYSCOUTEE_VERSION='+version,
                     '--label','org.opencontainers.image.version='+version,
                     '--label','org.opencontainers.image.revision='+self.release['source'],'--tag',image,'.')
            image_id=self.cmd('docker','image','inspect','--format','{{.Id}}',image,capture=True)
            (self.state/'images.json').write_text(json.dumps([{'reference':image,'imageId':image_id}],indent=2)+'\n')
        elif self.kind=='application':
            self.packaging_command('release','--','build-production')
            self.capture_application_images()
        else: print('No separate compilation for this project type.')

    @contextmanager
    def kvm_runtime(self, build=False, infrastructure=False):
        # The shared owner reads this exact filename. Temporarily materialize
        # private FILE-variable settings, then restore the tracked source.
        runtime=self.root/'config/microservices/deploy/runtime.json'
        lock=runtime.with_name('images.lock.json')
        saved={p:p.read_bytes() if p.exists() else None for p in (runtime,lock)}
        private=self.state/'kvm-runtime.json'
        backend_keys=('XDG_STATE_HOME','MYSCOUTEE_TERRAFORM_BACKEND','TF_HTTP_ADDRESS','TF_HTTP_LOCK_ADDRESS',
            'TF_HTTP_UNLOCK_ADDRESS','TF_HTTP_USERNAME','TF_HTTP_PASSWORD','TF_HTTP_LOCK_METHOD',
            'TF_HTTP_UNLOCK_METHOD','MYSCOUTEE_TERRAFORM_MODULE_ROOT','MYSCOUTEE_INFRA_OFFLINE')
        saved_environment={key:os.environ.get(key) for key in backend_keys}
        try:
            os.environ['XDG_STATE_HOME']=required('LAB_KVM_STATE_ROOT')
            if os.environ.get('LAB_TERRAFORM_BACKEND','local')=='gitlab':
                name=required('LAB_TERRAFORM_STATE_NAME')
                if not re.fullmatch(r'[a-zA-Z0-9_-]+',name): raise ValueError('Invalid Terraform state name')
                address=required('CI_API_V4_URL')+'/projects/'+required('CI_PROJECT_ID')+'/terraform/state/'+name
                os.environ.update(MYSCOUTEE_TERRAFORM_BACKEND='gitlab',TF_HTTP_ADDRESS=address,
                    TF_HTTP_LOCK_ADDRESS=address+'/lock',TF_HTTP_UNLOCK_ADDRESS=address+'/lock',
                    TF_HTTP_LOCK_METHOD='POST',TF_HTTP_UNLOCK_METHOD='DELETE',
                    TF_HTTP_USERNAME='gitlab-ci-token' if os.environ.get('CI_JOB_TOKEN') else 'oauth2',
                    TF_HTTP_PASSWORD=os.environ.get('CI_JOB_TOKEN') or required('LAB_RELEASE_TOKEN'))
            if build or infrastructure:
                data=json.loads(runtime.read_text())
                overrides=json.loads((self.root/'config/ci/kvm.json').read_text())
                data['lab'].update(overrides.get('lab',{}))
                data['localPort']=overrides.get('localPort',data['localPort'])
                if os.environ.get('LAB_KVM_RUNTIME_CONFIG'):
                    data=json.loads(Path(os.environ['LAB_KVM_RUNTIME_CONFIG']).read_text())
                for variable,target,key in [('LAB_KVM_HTTP_PORT',data,'localPort'),
                        ('LAB_KVM_GRAFANA_PORT',data['lab'],'grafanaPort'),
                        ('LAB_KVM_PROMETHEUS_PORT',data['lab'],'prometheusPort')]:
                    if os.environ.get(variable): target[key]=int(os.environ[variable])
                version=self.release['version']
                prefix=data['images']['prefix']
                data['images'].update(buildTag=version,immutableVersion=version)
                data['images']['frontendBase']=data['images']['frontendBase'].split(':')[0]+':'+version
                for key,value in data['dependencies'].items():
                    if value.startswith(prefix): data['dependencies'][key]=value.split(':')[0]+':'+version
                for key,value in data.get('volumeImages',{}).items():
                    if value.startswith(prefix): data['volumeImages'][key]=value.split(':')[0]+':'+version
                data['environment']['MYSCOUTEE_VERSION']=version
                private.write_text(json.dumps(data,indent=2)+'\n'); private.chmod(0o600)
            if not private.exists(): raise ValueError('Run the manual KVM image build first')
            shutil.copyfile(private,runtime)
            if not build and not infrastructure: shutil.copyfile(self.dist/'kvm-images.lock.json',lock)
            yield
        finally:
            for key,value in saved_environment.items():
                if value is None: os.environ.pop(key,None)
                else: os.environ[key]=value
            for path,value in saved.items():
                if value is None: path.unlink(missing_ok=True)
                else: path.write_bytes(value)

    def kvm(self):
        if self.kind!='application': raise ValueError('KVM requires an application candidate')
        self.verify_artifacts()
        support=Path(required('LAB_MICROSERVICES_SOURCE'))
        with self.kvm_runtime(build=True):
            for action in ('assembly-images','frontend-package','minio-image','support-images','release-simulator-image'):
                self.cmd('bash',support/'tools/lab.sh',action)
            self.cmd('python3',support/'tools/workloads.py','lock-images')
            source_lock=self.root/'config/microservices/deploy/images.lock.json'
            delivery_lock=self.dist/'kvm-images.lock.json'
            if delivery_lock.exists():
                def identity(path):
                    value=json.loads(path.read_text())
                    # Docker adds registry aliases after publication/pull. They
                    # are observations, not changes to the locked image bytes.
                    for image in value['images'].values(): image.pop('sourceDigests',None)
                    return value
                if identity(source_lock)!=identity(delivery_lock):
                    raise ValueError('KVM candidate image identities changed; create a new pipeline.')
            else:
                shutil.copy2(source_lock,delivery_lock)
        images=json.loads((self.dist/'kvm-images.lock.json').read_text())['images']
        inventory=[{'service':name,'reference':item['source'],'imageId':item['id']} for name,item in images.items()]
        assembly_plan=json.loads((self.root/'server/build/microservices/assembly-image-plan.json').read_text())
        # Build/reuse decisions change on retry; keep this job report separate
        # from the immutable candidate delivery files.
        (self.state/'kvm-assembly-plan.json').write_text(json.dumps(assembly_plan,indent=2)+'\n')
        for item in inventory:
            if item['service'] in assembly_plan:
                item['inputFingerprint']=assembly_plan[item['service']]['inputFingerprint']
        (self.state/'kvm-images.json').write_text(json.dumps(inventory,indent=2)+'\n')
        self.record_artifacts()

    def package(self):
        version=self.release['version']
        # Snapshot the precise version/dependency edits before archive creation.
        # It remains local until the manual release gate pushes its tag.
        self.snapshot()
        if self.kind in ('npm','angular-library'):
            self.cmd('npm','pack','./dist' if self.kind=='angular-library' else '.',
                     '--ignore-scripts','--pack-destination',self.dist)
        elif self.kind=='application':
            self.packaging_command('client-tools')
            if os.environ.get('LAB_PARTIAL_DATA')=='true':
                self.packaging_command('release','--','package-partial-release-data',str(self.dist/'partial-data'))
                self.cmd('tar','-czf',self.dist/'partial-data.tar.gz','-C',self.dist,'partial-data')
        elif self.kind in ('java-base','java-client','python-deb'):
            import shutil
            patterns={'java-base':['server/build/releases/*'], 'java-client':['build/releases/*','build/distributions/*','build/libs/*.jar'], 'python-deb':['dist/*.deb']}[self.kind]
            for pattern in patterns:
                for path in self.root.glob(pattern):
                    if path.is_file(): shutil.copy2(path,self.dist/path.name)
        elif self.kind=='frontend':
            self.cmd('tar','-czf',self.dist/(self.name+'-'+version+'-pages.tar.gz'),'-C','docs','.')
            self.cmd('tar','-czf',self.dist/(self.name+'-'+version+'-frontend.tar.gz'),'-C','prod','.')
        elif self.kind in ('source','legacy-source','ci'):
            self.cmd('git','archive','--format=tar.gz','--prefix='+self.name+'-'+version+'/',
                     '-o',self.dist/(self.name+'-'+version+'.tar.gz'),'HEAD')
        if self.spec.get('terraform_module'):
            spec=self.spec['terraform_module']
            module_version=spec.get('version',version)
            terraform_module.package(self.root,spec,module_version,self.dist/terraform_module.filename(spec,module_version))
        self.record_artifacts()

        if self.spec.get('terraform_module'):
            self.publish_terraform_module()

    def publish_terraform_module(self):
        # Small, local infrastructure configuration is an automatic master
        # package. Public application/dependency release gates stay manual.
        if (not os.environ.get('CI_DEFAULT_BRANCH') or
                os.environ.get('CI_COMMIT_BRANCH')!=os.environ['CI_DEFAULT_BRANCH'] or
                os.environ.get('CI_COMMIT_REF_PROTECTED')!='true'):
            print('Terraform module registry publication requires the protected default branch; candidate retained.')
            return
        spec=self.spec['terraform_module']
        version=spec.get('version',self.release['version'])
        terraform_module.publish(self.dist/terraform_module.filename(spec,version),
            spec,version,required('CI_API_V4_URL'),required('CI_PROJECT_ID'),
            required('CI_JOB_TOKEN'),job_token=True)

    def snapshot(self):
        self.cmd('git','add','--update')
        if not (self.state/'snapshot.json').exists() or self.cmd('git','diff','--cached','--name-only',capture=True):
            task=re.match(r'\[[A-Z][A-Z0-9]*-[0-9]+\]',os.environ.get('CI_COMMIT_TITLE',''))
            message=(task.group(0)+' ' if task else '')+'Prepare release candidate '+self.release['version']+'\n\n[skip ci]'
            self.cmd('git','-c','user.name='+os.environ.get('LAB_BOT_NAME','MyScoutee CI'),
                '-c','user.email='+os.environ.get('LAB_BOT_EMAIL','ci@localhost.invalid'),
                'commit','--allow-empty','-m',message)
            (self.state/'snapshot.json').write_text(json.dumps({'revision':self.cmd('git','rev-parse','HEAD',capture=True)})+'\n')

    def publish_local_images(self):
        inventories=[(filename,folder) for filename,folder in
            [('images.json','release'),('kvm-images.json','kvm')]
            if (self.state/filename).exists()]
        if not inventories: return
        self.cmd('docker','login',required('CI_REGISTRY'),'--username',required('CI_REGISTRY_USER'),
                 '--password-stdin',input=required('CI_REGISTRY_PASSWORD')+'\n')
        for filename,folder in inventories:
            for item in json.loads((self.state/filename).read_text()):
                service=item.get('service',self.name)
                if not re.fullmatch(r'[a-z][a-z0-9-]*',service): raise ValueError('Invalid image service')
                reference=required('CI_REGISTRY_IMAGE')+'/'+folder+'/'+service+':'+self.release['version']
                self.cmd('docker','tag',item['imageId'],reference)
                self.cmd('docker','push',reference)
                self.cmd('docker','pull',reference)
                if self.cmd('docker','image','inspect','--format','{{.Id}}',reference,capture=True)!=item['imageId']:
                    raise ValueError('Local release registry changed image identity')

    def record_artifacts(self):
        # Only delivery files, never the DEB staging tree or private local config.
        files=[{'name':p.name, 'sha256':digest(p), 'size':p.stat().st_size}
               for p in sorted(self.dist.iterdir()) if p.is_file()]
        (self.state/'artifact-manifest.json').write_text(json.dumps({'release':self.release,'files':files},indent=2)+'\n')

    def deb(self):
        if self.kind!='application': raise ValueError('DEB adapter requires an application')
        self.verify_artifacts()
        policy=json.loads((self.root/'config/packaging/release-project.json').read_text())
        deb=self.dist/f'{policy["packageName"]}_{self.release["version"]}_amd64.deb'
        if not deb.exists():
            self.cmd('npm','--prefix','config/packaging','run','release','--','package-production',
                     env=dict(os.environ,BUILD_ARTIFACTS='false'))
        self.record_artifacts()

    def sign_deb(self):
        name=json.loads((self.root/'config/packaging/release-project.json').read_text())['packageName']
        version=self.release['version']
        if not (self.dist/f'{name}_{version}_amd64.deb').is_file():
            raise ValueError('Run the manual package:deb job before publishing or deploying a full DEB')
        manifest=self.dist/f'{name}-release_{version}.json'
        if manifest.exists(): return
        # Direct installation uses the native signed package manifest. The
        # GitHub updater catalog has its own owner; do not emit dead URLs for
        # artifacts published only to this local GitLab.
        self.cmd('bash',self.packaging/'release/signing/sign-release-artifacts.sh','--project-root',self.root,
            '--deb',self.dist/f'{name}_{version}_amd64.deb','--client-tools',self.dist/f'{name}-client-tools_{version}.tar.gz',
            '--private-key',required('LAB_SIGNING_KEY'),'--channel','lab','--output-dir',self.dist)
        self.record_artifacts()

    def seal_partial(self):
        inventory=self.dist/'partial-SHA256SUMS'
        files=[p for p in sorted(self.dist.iterdir()) if p.is_file() and not p.name.startswith('partial-SHA256SUMS')]
        inventory.write_text(''.join(digest(p)+'  '+p.name+'\n' for p in files))
        self.cmd('openssl','pkeyutl','-sign','-inkey',required('LAB_SIGNING_KEY'),'-rawin',
                 '-in',inventory,'-out',self.dist/'partial-SHA256SUMS.sig')
        self.record_artifacts()

    def capture_application_images(self):
        policy=json.loads((self.root/'config/packaging/release-project.json').read_text())
        compose=json.loads(self.cmd('docker','compose','-f','docker-compose-prod.yml',
            'config','--no-env-resolution','--format','json',cwd=self.root/'server',capture=True))
        images=[]
        for item in policy['images']:
            ref=item['repository']+':'+self.release['version']+'-'+item['tagSuffix']
            service=compose['services'].get(item['service'])
            if service is None and item.get('container'):
                matches=[value for value in compose['services'].values()
                         if value.get('container_name')==item['container']]
                if len(matches)>1: raise ValueError('Ambiguous container in product image policy')
                if matches: service=matches[0]
            # Registry/simulator are separately released, digest-pinned inputs,
            # not Compose build targets. Preserve those exact bytes under the
            # product package's canonical image alias; never build them here.
            source=None
            if service is not None and not service.get('build'):
                source=service['image']
                if not re.fullmatch(r'[a-z0-9./:_-]+@sha256:[a-f0-9]{64}',source):
                    raise ValueError('External application image must be digest-pinned: '+item['service'])
                self.cmd('docker','pull',source)
                self.cmd('docker','tag',source,ref)
            image_id=self.cmd('docker','image','inspect','--format','{{.Id}}',ref,capture=True)
            image={'reference':ref,'imageId':image_id,'service':item['service']}
            if source: image['source']=source
            images.append(image)
        (self.state/'images.json').write_text(json.dumps(images,indent=2)+'\n')

    def verify_artifacts(self):
        record=json.loads((self.state/'artifact-manifest.json').read_text())
        for item in record['files']:
            if digest(self.dist/item['name'])!=item['sha256']: raise ValueError('Artifact changed after packaging: '+item['name'])
        for filename in ('images.json','kvm-images.json'):
            path=self.state/filename
            if path.exists():
                for image in json.loads(path.read_text()):
                    actual=self.cmd('docker','image','inspect','--format','{{.Id}}',image['reference'],capture=True)
                    if actual!=image['imageId']: raise ValueError('Image changed after build; refusing publication/deploy')

    def release_phase(self):
        if required('CI_COMMIT_BRANCH')!=required('CI_DEFAULT_BRANCH'):
            raise ValueError('Feature candidates cannot be released; merge into the default branch first')
        self.verify_artifacts()
        if (self.state/'published.json').exists():
            # Publication succeeded but a merge may have conflicted or lost its
            # response. Retry only integration, never immutable package uploads.
            self.merge_release()
            return
        project_id=required('CI_PROJECT_ID')
        repository=required('LAB_GITHUB_REPOSITORY')
        required('GH_TOKEN')
        from github_cli import ensure
        ensure()
        # Confirm destination and immutable tag absence before any publication.
        self.cmd('gh','repo','view',repository,'--json','nameWithOwner',capture=True)
        tag='v'+self.release['version']
        github_tags=json.loads(self.cmd('gh','api','repos/'+repository+'/git/matching-refs/tags/'+tag,capture=True))
        if any(t['ref']=='refs/tags/'+tag for t in github_tags): raise ValueError('GitHub release tag already exists')
        existing=api('GET',f'/projects/{project_id}/repository/tags?search=^{tag}$')
        if existing: raise ValueError('Version was already released. Start a fresh pipeline; never move a release tag.')
        # The manual gate authorizes publication, but never creates a signing key.
        if self.kind=='application' and (self.release['delivery']=='deb' or any(self.dist.glob('*.deb'))):
            self.sign_deb()
        elif self.kind=='application': required('LAB_SIGNING_KEY')
        if self.kind in ('npm','angular-library'):
            archive=next(self.dist.glob('*.tgz'))
            registry=required('LAB_NPM_REGISTRY')
            self.cmd('npm','publish',archive,'--registry',registry,'--ignore-scripts')
            package=json.loads((self.root/'package.json').read_text())['name']
            actual=self.cmd('npm','view',package+'@'+self.release['version'],'dist.integrity','--registry',registry,capture=True)
            expected='sha512-'+base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
            if actual!=expected: raise ValueError('Published npm bytes differ from tested tarball')
        elif self.kind in ('java-base','java-client'):
            self.publish_maven(repository)
        elif self.kind in ('go-image','nginx-image'):
            images=json.loads((self.state/'images.json').read_text())
            for image in images:
                self.cmd('docker','push',image['reference']); self.cmd('docker','pull',image['reference'])
                actual=self.cmd('docker','image','inspect','--format','{{.Id}}',image['reference'],capture=True)
                if actual!=image['imageId']: raise ValueError('Published Docker image identity differs')
                image['digest']=self.cmd('docker','image','inspect','--format','{{index .RepoDigests 0}}',image['reference'],capture=True)
            (self.dist/'published-images.json').write_text(json.dumps({'images':images},indent=2)+'\n')
        elif self.kind=='application':
            self.packaging_command('release','--','publish-images')
            kvm=self.state/'kvm-images.json'
            if kvm.exists():
                images=json.loads(kvm.read_text())
                for image in images:
                    target=required('LAB_IMAGE_NAMESPACE').rstrip('/')+'/'+self.name+'-kvm/'+image['service']+':'+self.release['version']
                    self.cmd('docker','tag',image['imageId'],target)
                    self.cmd('docker','push',target); self.cmd('docker','pull',target)
                    if self.cmd('docker','image','inspect','--format','{{.Id}}',target,capture=True)!=image['imageId']:
                        raise ValueError('Published KVM image identity differs')
                    image['digest']=self.cmd('docker','image','inspect','--format','{{index .RepoDigests 0}}',target,capture=True)
                (self.dist/'published-kvm-images.json').write_text(json.dumps({'images':images},indent=2)+'\n')
            if self.release['delivery']=='partial': self.seal_partial()
        if self.spec.get('terraform_module'):
            spec=self.spec['terraform_module']
            module_version=spec.get('version',self.release['version'])
            terraform_module.publish(self.dist/terraform_module.filename(spec,module_version),
                spec,module_version,required('CI_API_V4_URL'),project_id,
                os.environ.get('CI_JOB_TOKEN') or required('LAB_RELEASE_TOKEN'),bool(os.environ.get('CI_JOB_TOKEN')))
        self.publish_local_images()
        # Final tested dependency/version edits are captured in the release tag.
        self.snapshot()
        revision=self.cmd('git','rev-parse','HEAD',capture=True)
        self.push_tag(tag)
        self.push_github_tag(repository,tag)
        links=[]
        for path in sorted(self.dist.rglob('*')):
            if not path.is_file(): continue
            # Raw DEB staging roots/private metadata are never uploaded.
            if path.parent!=self.dist: continue
            endpoint=f'/projects/{project_id}/packages/generic/{self.name}/{self.release["version"]}/{urllib.parse.quote(path.name)}'
            self.upload(path,required('CI_API_V4_URL')+endpoint)
            links.append({'name':path.name,'url':required('CI_API_V4_URL')+endpoint})
        description=''  # Release prose is edited later on GitHub; never a publication prerequisite.
        api('POST',f'/projects/{project_id}/releases',{'tag_name':tag,'name':self.spec.get('release_name',self.name)+' '+self.release['version'],
            'description':description, 'assets':{'links':links}})
        notes=self.state/'release-notes.md'
        notes.write_text(description)
        assets=[p for p in sorted(self.dist.iterdir()) if p.is_file()]
        self.cmd('gh','release','create',tag,*assets,'--repo',repository,
            '--verify-tag','--title',self.spec.get('release_name',self.name)+' '+self.release['version'],'--notes-file',notes)
        (self.state/'published.json').write_text(json.dumps({'revision':revision,'tag':tag,'version':self.release['version']},indent=2)+'\n')
        self.merge_release()

    def github_api(self, method, endpoint, payload=None):
        args=['gh','api','--method',method,endpoint]
        kwargs={'capture':True}
        if payload is not None:
            args+=['--input','-']; kwargs['input']=json.dumps(payload)
        result=self.cmd(*args,**kwargs)
        return json.loads(result) if result else None

    def merge_release(self):
        """Merge the published branch through provider review APIs, never push master."""
        from github_cli import ensure
        ensure()
        published=json.loads((self.state/'published.json').read_text())
        if published['version']!=self.release['version']:
            raise ValueError('Published receipt belongs to another release')
        revision=published['revision']
        if self.cmd('git','rev-parse',published['tag']+'^{commit}',capture=True)!=revision:
            raise ValueError('Published tag differs from release receipt')
        branch='release/'+published['tag']
        target=required('CI_DEFAULT_BRANCH')
        title='Release '+published['tag']
        description='Integrate the published release '+published['tag']+' ('+revision+').'
        receipt=self.state/'release-merges.json'
        merged=json.loads(receipt.read_text()) if receipt.exists() else {}
        project='/projects/'+required('CI_PROJECT_ID')
        repository=required('LAB_GITHUB_REPOSITORY')
        if 'gitlab' not in merged:
            query=urllib.parse.urlencode({'source_branch':branch,'target_branch':target,'scope':'all'})
            requests=api('GET',project+'/merge_requests?'+query)
            request=next((r for r in requests if r['state'] in ('opened','merged')),None)
            if request is None:
                request=api('POST',project+'/merge_requests',{'source_branch':branch,'target_branch':target,
                    'title':title,'description':description,'remove_source_branch':True,'squash':False})
            endpoint=project+'/merge_requests/'+str(request['iid'])
            # GitLab computes mergeability asynchronously after creating an MR.
            for attempt in range(10):
                request=api('GET',endpoint)
                if request.get('detailed_merge_status') not in ('checking','unchecked','preparing'): break
                time.sleep(1)
            if request.get('sha')!=revision:
                raise ValueError('GitLab release branch differs from published commit')
            if request['state']!='merged':
                request=api('PUT',endpoint+'/merge',{'sha':revision,'squash':False,
                    'should_remove_source_branch':True,'merge_commit_message':title+'\n\n[skip ci]'})
            if request['state']!='merged': raise ValueError('GitLab release merge is not complete')
            merged['gitlab']=request['web_url']
            receipt.write_text(json.dumps(merged,indent=2)+'\n')
        if 'github' not in merged:
            base='repos/'+repository
            query=urllib.parse.urlencode({'head':repository.split('/')[0]+':'+branch,'base':target,'state':'all'})
            requests=self.github_api('GET',base+'/pulls?'+query)
            request=next((r for r in requests if r['state']=='open' or r.get('merged_at')),None)
            if request is None:
                request=self.github_api('POST',base+'/pulls',{'head':branch,'base':target,
                    'title':title,'body':description})
            endpoint=base+'/pulls/'+str(request['number'])
            if request['head']['sha']!=revision:
                raise ValueError('GitHub release branch differs from published commit')
            if not request.get('merged_at'):
                result=self.github_api('PUT',endpoint+'/merge',{'sha':revision,'merge_method':'merge',
                    'commit_title':title,'commit_message':description+'\n\n[skip ci]'})
                if not result.get('merged'): raise ValueError('GitHub release merge is not complete')
            merged['github']=request['html_url']
            receipt.write_text(json.dumps(merged,indent=2)+'\n')
        # Remove only our unchanged release ref, after the confirmed merge.
        refs=self.github_api('GET','repos/'+repository+'/git/matching-refs/heads/'+branch)
        for ref in refs:
            if ref['ref']=='refs/heads/'+branch:
                if ref['object']['sha']!=revision: raise ValueError('Release branch changed; retaining it')
                self.github_api('DELETE','repos/'+repository+'/git/refs/heads/'+branch)
        print('Published release integrated through merge requests:',json.dumps(merged))

    def upload(self, path, url, job_token=False):
        parsed=urllib.parse.urlsplit(url)
        connection=(http.client.HTTPSConnection if parsed.scheme=='https' else http.client.HTTPConnection)(parsed.netloc,timeout=600)
        try:
            # Stream large DEBs; never allocate their full size in RAM.
            with path.open('rb') as stream:
                auth={'JOB-TOKEN':required('CI_JOB_TOKEN')} if job_token and os.environ.get('CI_JOB_TOKEN') else {'PRIVATE-TOKEN':required('LAB_RELEASE_TOKEN')}
                connection.request('PUT',parsed.path,body=stream,headers={**auth,
                    'Content-Length':str(path.stat().st_size),'Content-Type':'application/octet-stream'})
                response=connection.getresponse(); response.read()
                if response.status not in (200,201): raise ValueError('Package upload failed: HTTP '+str(response.status))
        finally: connection.close()

    def publish_maven(self, repository):
        # Promote the archived Maven bytes; do not invoke compilation at publish.
        archive=next(self.dist.glob('*-maven.zip'))
        import zipfile
        username=self.cmd('gh','api','user','--jq','.login',capture=True)
        auth=base64.b64encode((username+':'+required('GH_TOKEN')).encode()).decode()
        base='https://maven.pkg.github.com/'+repository
        with zipfile.ZipFile(archive) as source:
            entries=[n for n in source.namelist() if '/'+self.release['version']+'/' in n and not n.endswith('/')]
            if not entries: raise ValueError('Maven release archive contains no versioned artifacts')
            for name in entries:
                if '..' in Path(name).parts or name.startswith('/'): raise ValueError('Invalid Maven artifact path')
                content=source.read(name)
                url=base+'/'+urllib.parse.quote(name,safe='/')
                request=urllib.request.Request(url,data=content,method='PUT',headers={'Authorization':'Basic '+auth,'Content-Type':'application/octet-stream'})
                with urllib.request.urlopen(request,timeout=180) as response: response.read()
                request=urllib.request.Request(url,headers={'Authorization':'Basic '+auth})
                with urllib.request.urlopen(request,timeout=180) as response:
                    actual=hashlib.sha256(response.read()).digest()
                if actual!=hashlib.sha256(content).digest(): raise ValueError('Published Maven artifact differs: '+name)

    def push_github_tag(self, repository, tag):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository): raise ValueError('Invalid GitHub repository')
        helper=self.state/'github-release-askpass'
        helper.write_text('#!/bin/sh\ncase "$1" in *Username*) echo x-access-token;; *) printf "%s\\n" "$GH_TOKEN";; esac\n')
        helper.chmod(0o700)
        try:
            self.cmd('git','-c','credential.helper=','push','--atomic','https://github.com/'+repository+'.git','refs/tags/'+tag,
                'refs/tags/'+tag+':refs/heads/release/'+tag,
                env=dict(os.environ,GIT_ASKPASS=str(helper),GIT_TERMINAL_PROMPT='0'))
        finally: helper.unlink()

    def push_tag(self, tag):
        helper=self.state/'release-askpass'
        helper.write_text('#!/bin/sh\ncase "$1" in *Username*) echo oauth2;; *) printf "%s\\n" "$LAB_RELEASE_TOKEN";; esac\n')
        helper.chmod(0o700)
        url=required('CI_SERVER_URL')+'/'+required('CI_PROJECT_PATH')+'.git'
        try:
            self.cmd('git','tag',tag)
            self.cmd('git','-c','credential.helper=','push','--atomic','-o','ci.skip',url,'refs/tags/'+tag,
                'refs/tags/'+tag+':refs/heads/release/'+tag,
                env=dict(os.environ,GIT_ASKPASS=str(helper),GIT_TERMINAL_PROMPT='0'))
        finally: helper.unlink()

    def downstream(self):
        published=json.loads((self.state/'published.json').read_text())
        group=required('LAB_GROUP_PATH')
        variables={'LAB_UPSTREAM_PROJECT':self.name,'LAB_UPSTREAM_VERSION':published['version'],
                   'LAB_UPSTREAM_REVISION':published['revision']}
        if self.kind in ('npm','angular-library'): variables['LAB_UPSTREAM_PACKAGE']=json.loads((self.root/'package.json').read_text())['name']
        if self.kind in ('go-image','nginx-image'):
            variables['LAB_UPSTREAM_IMAGE']=json.loads((self.dist/'published-images.json').read_text())['images'][0]['digest']
        receipt=[]
        for consumer in consumers(self.projects,self.name):
            if os.environ.get('LAB_CI_PROVIDER')=='github':
                repository=self.projects[consumer]['variables']['LAB_GITHUB_REPOSITORY']
                payload=json.dumps({'event_type':'myscoutee-dependency-release','client_payload':variables})
                self.cmd('gh','api','--method','POST','repos/'+repository+'/dispatches','--input','-',input=payload)
                receipt.append({'project':consumer,'status':'dispatched'})
                continue
            project=urllib.parse.quote(group+'/'+consumer,safe='')
            data=api('GET','/projects/'+project)
            # A successful release, not a merely completed build, emits this event.
            result=api('POST',f'/projects/{data["id"]}/pipeline',{'ref':data['default_branch'],
                'variables':[{'key':k,'value':v} for k,v in variables.items()]})
            receipt.append({'project':consumer,'pipeline':result['id']})
        (self.state/'downstream.json').write_text(json.dumps(receipt,indent=2)+'\n')
        print('Triggered consumer pipelines:',len(receipt))

    def deploy(self):
        if self.kind!='application': raise ValueError('This product has no application deployment')
        self.verify_artifacts()
        if required('LAB_TARGET')=='monolith' and os.environ.get('LAB_MONOLITH_MODE','ssh')=='compose':
            from monolith import deploy
            deploy(self)
            return
        delivery=os.environ.get('LAB_DEPLOY_FORMAT',self.release['delivery'])
        if delivery not in ('deb','partial'): raise ValueError('LAB_DEPLOY_FORMAT must be deb or partial')
        os.environ['LAB_DEPLOY_FORMAT']=delivery
        if required('LAB_TARGET')!='kvm':
            if delivery=='deb': self.sign_deb()
            else:
                # Existing partial installer supports local image IDs. A local
                # VM deploy therefore needs neither registry push nor release.
                images=json.loads((self.state/'images.json').read_text())
                selected=required('LAB_PARTIAL_SERVICES').split(',')
                policy=json.loads((self.root/'config/packaging/release-project.json').read_text())
                mapping={s['name']:s['imageService'] for s in policy['clientTools']['services'] if 'imageService' in s}
                images=[dict(i,service=s) for s in selected for i in images if i['service']==mapping.get(s)]
                if {i['service'] for i in images}!=set(selected): raise ValueError('Partial image selection missing')
                self.cmd('docker','save','-o',self.dist/'partial-images.tar',*[i['reference'] for i in images])
                (self.dist/'partial-images.json').write_text(json.dumps({'images':images},indent=2)+'\n')
                self.seal_partial()
        if required('LAB_TARGET')=='kvm':
            with self.kvm_runtime():
                from infra_assets import check
                check(self)
                self.cmd('bash',Path(__file__).parent/'deploy.sh',self.state)
        else: self.cmd('bash',Path(__file__).parent/'deploy.sh',self.state)

    def infra_start(self):
        if self.kind!='application': raise ValueError('Infrastructure requires an application')
        with self.kvm_runtime(infrastructure=True):
            support=Path(required('LAB_MICROSERVICES_SOURCE'))
            self.cmd('python3',support/'tools/host.py','start')
            from infra_assets import publish, restore
            publish(self)
            restore(self)
            self.cmd('python3',support/'tools/vm.py','start')

    def cluster(self):
        if not (self.state/'deployed-kvm.json').exists(): raise ValueError('Deploy the KVM candidate first')
        from kubernetes import install
        with self.kvm_runtime(): install(self)

    def verify(self):
        target=required('LAB_TARGET')
        options=[]
        if not (self.state/('deployed-'+target+'.json')).exists():
            raise ValueError('This candidate has not successfully deployed to this target')
        if target=='monolith' and os.environ.get('LAB_MONOLITH_MODE','ssh')=='compose':
            receipt=json.loads((self.state/'deployed-monolith.json').read_text())
            os.environ['NODE_EXTRA_CA_CERTS']=receipt['certificate']
            os.environ['LAB_VERIFY_URL']=receipt['url']
            options=['--http-url',receipt['httpUrl']]
        elif target=='kvm':
            with self.kvm_runtime():
                self.cmd('python3',Path(required('LAB_MICROSERVICES_SOURCE'))/'tools/check-public.py')
            return
        elif target=='vmware':
            self.cmd('bash',Path(__file__).parent/'verify-remote.sh',self.state)
            return
        self.packaging_command('verify','--','--url',required('LAB_VERIFY_URL'),
                               '--expected-version',self.release['version'],*options)

    def pages_commit(self, parent):
        """Commit only the built docs from the recorded archive, in this checkout."""
        content=self.state/'pages-content'
        if content.exists(): shutil.rmtree(content)
        docs=content/'docs'
        docs.mkdir(parents=True)
        with tarfile.open(self.dist/(self.name+'-'+self.release['version']+'-pages.tar.gz')) as archive:
            archive.extractall(docs,filter='data')
        index=self.state/'pages.index'
        index.unlink(missing_ok=True)
        env=dict(os.environ,GIT_INDEX_FILE=str(index))
        self.cmd('git','read-tree',parent if parent else '--empty',env=env)
        self.cmd('git','--work-tree='+str(content),'add','--all','--','docs',env=env)
        tree=self.cmd('git','write-tree',capture=True,env=env)
        if parent and tree==self.cmd('git','rev-parse',parent+'^{tree}',capture=True):
            return parent
        message='Publish GitHub Pages docs from pipeline '+self.release['pipeline']
        source=self.release['source']
        timestamp=self.cmd('git','show','-s','--format=%aI',source,capture=True)
        commit_env=dict(os.environ,GIT_AUTHOR_NAME=os.environ.get('LAB_BOT_NAME','MyScoutee CI'),
            GIT_AUTHOR_EMAIL=os.environ.get('LAB_BOT_EMAIL','ci@localhost.invalid'),
            GIT_COMMITTER_NAME=os.environ.get('LAB_BOT_NAME','MyScoutee CI'),
            GIT_COMMITTER_EMAIL=os.environ.get('LAB_BOT_EMAIL','ci@localhost.invalid'),
            GIT_AUTHOR_DATE=timestamp,GIT_COMMITTER_DATE=timestamp)
        arguments=['git','commit-tree',tree]
        if parent: arguments+=['-p',parent]
        arguments+=['-m',message]
        return self.cmd(*arguments,capture=True,env=commit_env)

    def pages(self):
        if self.kind!='frontend': raise ValueError('Pages requires a frontend candidate')
        self.verify_artifacts()
        repository=required('LAB_GITHUB_REPOSITORY')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository): raise ValueError('Invalid GitHub repository')
        required('GH_TOKEN')
        from github_cli import ensure
        ensure()
        helper=self.state/'github-askpass'
        helper.write_text('#!/bin/sh\ncase "$1" in *Username*) echo x-access-token;; *) printf "%s\\n" "$GH_TOKEN";; esac\n')
        helper.chmod(0o700)
        env=dict(os.environ,GIT_ASKPASS=str(helper),GIT_TERMINAL_PROMPT='0')
        remote='https://github.com/'+repository+'.git'
        branch='gh-pages'
        try:
            default=required('CI_DEFAULT_BRANCH')
            default_ref=self.cmd('git','-c','credential.helper=','ls-remote',remote,'refs/heads/'+default,
                capture=True,env=env)
            if not default_ref: raise ValueError('GitHub default branch is missing')
            head=default_ref.split()[0]
            if head!=self.release['source']:
                raise ValueError('GitHub default branch changed after the candidate build')
            published=self.cmd('git','-c','credential.helper=','ls-remote',remote,'refs/heads/'+branch,
                capture=True,env=env)
            parent=published.split()[0] if published else None
            if parent:
                self.cmd('git','-c','credential.helper=','fetch','--no-tags','--depth=1',remote,
                    '+refs/heads/'+branch+':refs/remotes/pages/'+branch,env=env)
                if self.cmd('git','rev-parse','refs/remotes/pages/'+branch,capture=True)!=parent:
                    raise ValueError('Pages branch advanced during preparation')
            commit=self.pages_commit(parent)
            changed=commit!=parent
            if changed:
                self.cmd('git','-c','credential.helper=','push',remote,
                    commit+':refs/heads/'+branch,env=env)
            settings=self.github_api('GET','repos/'+repository+'/pages')
            source={'branch':branch,'path':'/docs'}
            settings_changed=settings.get('build_type')!='legacy' or settings.get('source')!=source
            if settings_changed:
                self.github_api('PUT','repos/'+repository+'/pages',{'build_type':'legacy','source':source})
                settings=self.github_api('GET','repos/'+repository+'/pages')
            if settings.get('build_type')!='legacy' or settings.get('source')!=source:
                raise ValueError('GitHub Pages did not accept the permanent docs branch')
            if changed or settings_changed:
                self.github_api('POST','repos/'+repository+'/pages/builds')
            (self.state/'pages.json').write_text(json.dumps({'repository':repository,'ref':branch,
                'commit':commit,'status':'build_requested' if changed or settings_changed else 'unchanged'},indent=2)+'\n')
            print('Permanent gh-pages/docs branch is current; GitHub Pages deployment is asynchronous.')
        finally: helper.unlink()


def main():
    os.umask(0o077)
    phase=sys.argv[1]
    if phase not in ('prepare','dependencies','test','build','infra_start','cluster','kvm','package','deb','release','downstream','deploy','verify','pages'):
        raise ValueError('Unknown pipeline phase')
    project=Project()
    if phase!='prepare' and project.release is None: raise ValueError('Prepare phase has not completed')
    try:
        getattr(project,'release_phase' if phase=='release' else phase)()
    except Exception:
        if phase=='test': (project.state/'tests.json').write_text(json.dumps({'status':'failed','pipeline':project.release['pipeline']})+'\n')
        raise


if __name__=='__main__':
    main()
