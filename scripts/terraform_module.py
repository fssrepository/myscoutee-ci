"""Package committed Terraform sources and publish immutable module bytes."""
import argparse
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import urllib.error
import urllib.request


def filename(spec, version):
    for value in (spec['name'], spec['system']):
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', value):
            raise ValueError('Invalid Terraform module identity')
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?', version):
        raise ValueError('Invalid Terraform module version')
    return f"{spec['name']}-{spec['system']}-{version}.tgz"


def package(root, spec, version, output):
    filename(spec, version)
    directory=PurePosixPath(spec['directory'])
    if directory.is_absolute() or '..' in directory.parts:
        raise ValueError('Module source must be repository-relative')
    # git archive excludes ignored caches, operator tfvars, state and secrets.
    source=subprocess.check_output(['git','archive','--format=tar','HEAD:'+str(directory)],cwd=root)
    data=io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(source)) as archive, tarfile.open(fileobj=data,mode='w') as result:
        for member in archive:
            path=PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isdir() or member.isfile()):
                raise ValueError('Unsafe Terraform module member')
            if '.terraform' in path.parts or '.local' in path.parts or '.tfstate' in member.name or '.tfvars' in member.name:
                raise ValueError('Operator state cannot enter a Terraform module')
            # Content identity does not change when a release snapshot changes
            # only commit dates or unrelated repository files.
            member.mtime=0; member.uid=member.gid=0; member.uname=member.gname=''; member.pax_headers={}
            result.addfile(member,archive.extractfile(member) if member.isfile() else None)
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(gzip.compress(data.getvalue(),mtime=0))
    return output


def publish(path, spec, version, api_url, project, token, job_token=False):
    filename(spec,version)
    url=f"{api_url}/projects/{project}/packages/terraform/modules/{spec['name']}/{spec['system']}/{version}/file"
    headers={'JOB-TOKEN' if job_token else 'PRIVATE-TOKEN':token}
    if job_token:
        username='gitlab-ci-token'
    else:
        with urllib.request.urlopen(urllib.request.Request(api_url+'/user',headers=headers),timeout=60) as response:
            username=json.load(response)['username']
    download_headers={'Authorization':'Basic '+base64.b64encode((username+':'+token).encode()).decode()}
    content=Path(path).read_bytes()
    try:
        with urllib.request.urlopen(urllib.request.Request(url.removesuffix('/file'),headers=download_headers),timeout=120) as response:
            existing=response.read()
        if existing!=content: raise ValueError('Terraform module version already exists with different bytes')
        print('Terraform module already published; identical bytes verified.')
        return
    except urllib.error.HTTPError as error:
        if error.code!=404: raise RuntimeError('Terraform module lookup failed: HTTP '+str(error.code)) from None
    request=urllib.request.Request(url,data=content,headers={**headers,'Content-Type':'application/octet-stream'},method='PUT')
    with urllib.request.urlopen(request,timeout=120) as response:
        if response.status!=201: raise RuntimeError('Unexpected Terraform module upload response')
    with urllib.request.urlopen(urllib.request.Request(url.removesuffix('/file'),headers=download_headers),timeout=120) as response:
        if hashlib.sha256(response.read()).digest()!=hashlib.sha256(content).digest():
            raise ValueError('Published Terraform module bytes differ')
    print('Terraform module published and downloaded bytes verified.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('package','publish'))
    parser.add_argument('--repository',type=Path,required=True)
    parser.add_argument('--version',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    spec=json.loads((args.repository/'config/ci/project.json').read_text())['terraform_module']
    if args.action=='package': package(args.repository,spec,args.version,args.output)
    else: publish(args.output,spec,args.version,os.environ['CI_API_V4_URL'],os.environ['CI_PROJECT_ID'],
                  os.environ.get('CI_JOB_TOKEN') or os.environ['LAB_RELEASE_TOKEN'],bool(os.environ.get('CI_JOB_TOKEN')))
