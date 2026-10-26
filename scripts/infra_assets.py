"""Explicit manual infrastructure downloads; strict GitLab-only consumption."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request

from project import api, digest, required
import terraform_module

MISSING="Required infrastructure package is missing from the GitLab Package Registry. Run the optional manual 'infra:start' job, then retry."


def inputs(candidate):
    support=Path(required('LAB_MICROSERVICES_SOURCE'))
    versions=json.loads((support/'infra/versions.json').read_text())
    lock=(support/'infra/terraform/.terraform.lock.hcl').read_text()
    provider=re.search(r'provider "registry\.terraform\.io/dmacvicar/libvirt"\s*\{\s*version\s*=\s*"([0-9.]+)"',lock).group(1)
    revision=hashlib.sha256((json.dumps(versions,sort_keys=True)+lock).encode()).hexdigest()
    state=Path(candidate.cmd('python3',support/'tools/runtime_config.py','state',capture=True))
    project=api('GET','/projects/'+urllib.parse.quote(required('LAB_CI_PATH').rsplit('/',1)[0]+'/myscoutee-microservices',safe=''))
    base=required('CI_API_V4_URL')+'/projects/'+str(project['id'])+'/packages/generic/infra-assets/'+revision+'/'
    rows={
        'terraform.zip':dict(versions['terraform'],path=state/'tools'/('terraform-'+versions['terraform']['version']+'.zip')),
        'ubuntu.qcow2':dict(versions['ubuntu'],path=state/'vm/ubuntu-noble.qcow2'),
        'k3s':dict(versions['k3s'],path=state/'tools/k3s'),
        'k3s-airgap-images-amd64.tar.zst':dict(versions['k3sAirgap'],path=state/'tools/k3s-airgap-images-amd64.tar.zst'),
    }
    rows.update({name:dict(spec,path=state/'tools/guest-packages'/name)
                 for name,spec in versions.get('guestPackages',{}).items()})
    return support,state,rows,provider,project,base


def request(url):
    return urllib.request.Request(url,headers={'PRIVATE-TOKEN':required('LAB_RELEASE_TOKEN')})


def download(url,path,sha,authenticated):
    if path.exists() and digest(path)==sha: return
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_name(path.name+'.download')
    try:
        with urllib.request.urlopen(request(url) if authenticated else url,timeout=120) as source, temporary.open('wb') as output:
            shutil.copyfileobj(source,output,1024*1024)
        if digest(temporary)!=sha: raise ValueError('Infrastructure package checksum mismatch: '+path.name)
        temporary.replace(path)
    except urllib.error.HTTPError as error:
        if authenticated and error.code==404: raise ValueError(MISSING) from None
        raise
    finally:
        temporary.unlink(missing_ok=True)


def provider_archive(directory,path):
    data=io.BytesIO()
    with tarfile.open(fileobj=data,mode='w') as archive:
        for item in sorted(directory.iterdir()):
            if not item.is_file() or item.is_symlink(): raise ValueError('Unexpected provider member')
            info=tarfile.TarInfo(item.name);info.size=item.stat().st_size
            info.mode=0o755 if item.name.startswith('terraform-provider-') else 0o644
            with item.open('rb') as stream:archive.addfile(info,stream)
    path.write_bytes(gzip.compress(data.getvalue(),mtime=0))


def inventory(project, revision):
    files={}
    query=urllib.parse.urlencode({'package_type':'generic','package_name':'infra-assets','per_page':100})
    for package in api('GET',f'/projects/{project}/packages?'+query):
        if package['name']!='infra-assets' or package['version']!=revision: continue
        for item in api('GET',f'/projects/{project}/packages/{package["id"]}/package_files?per_page=100'):
            name=item['file_name']
            if name in files and files[name]['sha256']!=item['file_sha256']:
                raise ValueError('Conflicting registry files: '+name)
            files[name]={'sha256':item['file_sha256'],'bytes':item['size']}
    return files


def publish(candidate):
    support,state,rows,provider,project,base=inputs(candidate)
    try:
        check(candidate)
    except ValueError as error:
        if str(error)!=MISSING: raise
    else:
        print('Infrastructure packages already exist; preparation skipped.')
        return
    # Check individual registry files too: an interrupted import may have no
    # completion marker yet. Never re-download a published input from upstream.
    stored=inventory(project['id'],base.rstrip('/').rsplit('/',1)[-1])
    manifest={}
    pending={}
    for name,row in rows.items():
        if name in stored:
            if stored[name]['sha256']!=row['sha256']:
                raise ValueError('Registry infrastructure asset differs from pinned checksum: '+name)
            manifest[name]=stored[name]
            continue
        print('Preparing missing infrastructure asset:',name,flush=True)
        download(row['url'],row['path'],row['sha256'],False)
        pending[name]=row['path']
        manifest[name]={'sha256':row['sha256'],'bytes':row['path'].stat().st_size}
    provider_name='libvirt-linux_amd64.tar.gz'
    if provider_name in stored:
        manifest[provider_name]=stored[provider_name]
    else:
        # Only this explicitly invoked manual phase may install a missing provider.
        environment=dict(os.environ,MYSCOUTEE_TERRAFORM_BACKEND='local',MYSCOUTEE_INFRA_OFFLINE='false')
        candidate.cmd('bash',support/'tools/terraform.sh','validate',env=environment)
        installed=state/'terraform/providers/providers/registry.terraform.io/dmacvicar/libvirt'/provider/'linux_amd64'
        archive=state/'tools'/provider_name
        provider_archive(installed,archive)
        pending[provider_name]=archive
        manifest[provider_name]={'sha256':digest(archive),'bytes':archive.stat().st_size}
    # The manifest is the completion marker: publish it last, and never silently
    # replace a completed package set with different bytes.
    try:
        with urllib.request.urlopen(request(base+'manifest.json'),timeout=60) as response: existing=json.load(response)
        if existing!=manifest: raise ValueError('Infrastructure package set already exists with different bytes')
        print('Infrastructure package set already exists; source checksums match.')
    except urllib.error.HTTPError as error:
        if error.code!=404: raise
        for name,path in pending.items(): candidate.upload(path,base+name)
        path=state/'tools/infra-assets.json'
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        path.write_text(json.dumps(manifest,sort_keys=True)+'\n')
        candidate.upload(path,base+'manifest.json')
    print('Infrastructure assets are available in '+project['web_url']+'/-/packages')


def restore(candidate):
    support,state,rows,provider,project,base=inputs(candidate)
    try:
        with urllib.request.urlopen(request(base+'manifest.json'),timeout=60) as response: manifest=json.load(response)
    except urllib.error.HTTPError as error:
        if error.code==404: raise ValueError(MISSING) from None
        raise
    for name,row in rows.items():
        if manifest[name]['sha256']!=row['sha256']: raise ValueError('Registry asset differs from pinned upstream checksum')
        download(base+name,row['path'],row['sha256'],True)
    archive=state/'tools/libvirt-linux_amd64.tar.gz'
    checksum=manifest['libvirt-linux_amd64.tar.gz']['sha256']
    if not re.fullmatch('[0-9a-f]{64}',checksum): raise ValueError('Invalid provider archive checksum')
    download(base+archive.name,archive,checksum,True)
    mirror=state/'tools/provider-mirror/registry.terraform.io/dmacvicar/libvirt'/provider/'linux_amd64'
    mirror.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive) as bundle:
        for member in bundle:
            if not member.isfile() or Path(member.name).name!=member.name: raise ValueError('Unsafe provider archive')
            destination=mirror/member.name
            if destination.is_symlink(): raise ValueError('Symlinked provider cache')
            with bundle.extractfile(member) as source,destination.open('wb') as target:shutil.copyfileobj(source,target)
            destination.chmod(member.mode & 0o755)
    # Use the published module, with the source digest verified against the
    # pinned checkout. A matching private cache avoids downloading it again.
    spec=json.loads((support/'config/ci/project.json').read_text())['terraform_module']
    version=spec.get('version',candidate.release['version'])
    expected=state/'tools'/('expected-'+terraform_module.filename(spec,version))
    terraform_module.package(support,spec,version,expected)
    module=state/'tools'/terraform_module.filename(spec,version)
    user=api('GET','/user')['username']
    import base64
    url=required('CI_API_V4_URL')+f"/projects/{project['id']}/packages/terraform/modules/{spec['name']}/{spec['system']}/{version}"
    if not module.exists() or digest(module)!=digest(expected):
        auth=base64.b64encode((user+':'+required('LAB_RELEASE_TOKEN')).encode()).decode()
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':'Basic '+auth}),timeout=60) as response:
                data=response.read()
        except urllib.error.HTTPError as error:
            if error.code==404:
                raise ValueError('Required Terraform module is missing from the GitLab Module Registry. Complete the automatic build job on the protected default branch of myscoutee-microservices, then retry.') from None
            raise
        if hashlib.sha256(data).hexdigest()!=digest(expected): raise ValueError('Registry module differs from pinned sources')
        module.write_bytes(data)
    extracted=state/'terraform/registry-module'
    extracted.mkdir(parents=True,exist_ok=True)
    with tarfile.open(module) as bundle:
        for member in bundle:
            path=Path(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isdir() or member.isfile()):
                raise ValueError('Unsafe module archive')
            target=extracted/path
            if target.resolve()!=target: raise ValueError('Symlinked module cache')
            if member.isdir(): target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with bundle.extractfile(member) as source,target.open('wb') as output:shutil.copyfileobj(source,output)
    os.environ['MYSCOUTEE_TERRAFORM_MODULE_ROOT']=str(extracted)
    os.environ['MYSCOUTEE_INFRA_OFFLINE']='true'
    print('Pinned host and guest infrastructure assets verified; upstream bootstrap downloads disabled.')


def check(candidate):
    support,state,rows,provider,project,base=inputs(candidate)
    try:
        with urllib.request.urlopen(request(base+'manifest.json'),timeout=60) as response:
            manifest=json.load(response)
        for name in (*rows,'libvirt-linux_amd64.tar.gz'):
            if name in rows and manifest[name]['sha256']!=rows[name]['sha256']:
                raise ValueError('Registry infrastructure asset differs from pinned checksum')
            probe=request(base+name);probe.method='HEAD'
            with urllib.request.urlopen(probe,timeout=60) as response:
                if int(response.headers['Content-Length'])!=manifest[name]['bytes']:
                    raise ValueError('Registry infrastructure asset differs from recorded size')
    except urllib.error.HTTPError as error:
        if error.code==404: raise ValueError(MISSING) from None
        raise
    return manifest
