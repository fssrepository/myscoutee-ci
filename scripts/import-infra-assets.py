#!/usr/bin/env python3
"""Operator import helper: seed GitLab from separately downloaded installers.

Pass only the artifacts to import. Existing files are checksum-verified; a missing
selected file is downloaded from the versioned upstream URL. This is not a CI job.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.parse

from project import Project, api, digest
from infra_assets import download, inventory, provider_archive


class Uploader:
    # Reuse the CI adapter's streaming upload; large images are not held in RAM.
    upload = Project.upload



def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--support',type=Path,required=True,help='myscoutee-microservices checkout')
    parser.add_argument('--project',required=True,help='GitLab project ID or group/project path')
    parser.add_argument('--api-url',default=os.environ.get('CI_API_V4_URL'))
    parser.add_argument('--token-file',type=Path,help='Ignored token file; alternatively LAB_RELEASE_TOKEN')
    parser.add_argument('--ubuntu',type=Path,help='Existing QCOW2, or download destination if missing')
    parser.add_argument('--terraform',type=Path,help='Existing pinned ZIP, or download destination if missing')
    parser.add_argument('--k3s',type=Path,help='Existing k3s binary, or download destination if missing')
    parser.add_argument('--k3s-airgap',dest='k3sAirgap',type=Path,help='Matching offline image archive, or download destination if missing')
    parser.add_argument('--provider-directory',type=Path,help='Already installed libvirt provider directory')
    parser.add_argument('--guest-packages',type=Path,help='Directory of pinned Ubuntu guest DEBs; missing selected files are downloaded here')
    args=parser.parse_args()
    if not args.api_url: parser.error('--api-url or CI_API_V4_URL is required')
    if not any((args.ubuntu,args.terraform,args.k3s,args.k3sAirgap,args.provider_directory,args.guest_packages)):parser.error('Select at least one artifact')
    os.umask(0o077)
    os.environ['CI_API_V4_URL']=args.api_url.rstrip('/')
    if args.token_file:os.environ['LAB_RELEASE_TOKEN']=args.token_file.read_text().strip()
    versions=json.loads((args.support/'infra/versions.json').read_text())
    lock=(args.support/'infra/terraform/.terraform.lock.hcl').read_text()
    revision=hashlib.sha256((json.dumps(versions,sort_keys=True)+lock).encode()).hexdigest()
    project=api('GET','/projects/'+urllib.parse.quote(args.project,safe=''))
    project_id=project['id']
    base=args.api_url.rstrip('/')+f'/projects/{project_id}/packages/generic/infra-assets/{revision}/'
    stored=inventory(project_id,revision)
    uploader=Uploader()

    def upload(path,name,expected):
        actual=digest(path)
        if actual!=expected:raise ValueError('Local checksum mismatch: '+name)
        if name in stored:
            if stored[name]['sha256']!=actual:raise ValueError('Registry version already contains different bytes: '+name)
            print(name+': already in registry; skipped',flush=True)
            return
        uploader.upload(path,base+name)
        verified=inventory(project_id,revision).get(name)
        if not verified or verified['sha256']!=actual:raise ValueError('Uploaded checksum verification failed: '+name)
        stored[name]=verified
        print(name+': uploaded and registry SHA-256 verified',flush=True)

    artifacts={name:versions[key] for key,name in (('ubuntu','ubuntu.qcow2'),('terraform','terraform.zip'),('k3s','k3s'),('k3sAirgap','k3s-airgap-images-amd64.tar.zst'))}
    selected={name:getattr(args,key) for key,name in (('ubuntu','ubuntu.qcow2'),('terraform','terraform.zip'),('k3s','k3s'),('k3sAirgap','k3s-airgap-images-amd64.tar.zst'))}
    artifacts.update(versions.get('guestPackages',{}))
    if args.guest_packages:
        selected.update({name:args.guest_packages/name for name in versions.get('guestPackages',{})})
    for name,path in selected.items():
        if path is None:continue
        expected=artifacts[name]['sha256']
        if name in stored:
            if stored[name]['sha256']!=expected:raise ValueError('Registry checksum differs from pinned source: '+name)
            print(name+': already in registry; skipped',flush=True)
            continue
        if path.exists():
            print(name+': using existing local file',flush=True)
        else:
            print(name+': selected local file is missing; downloading pinned upstream artifact',flush=True)
            download(artifacts[name]['url'],path,expected,False)
        upload(path,name,expected)

    private=Path(__file__).resolve().parents[1]/'.local/import-infra-assets'
    private.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=private) as directory:
        if args.provider_directory:
            provider=args.provider_directory
            rows=[]
            for item in sorted(provider.iterdir()):
                if not item.is_file() or item.is_symlink():raise ValueError('Unexpected provider file')
                rows.append(digest(item)+'  '+item.name+'\n')
            h1='h1:'+base64.b64encode(hashlib.sha256(''.join(rows).encode()).digest()).decode()
            if h1 not in re.findall(r'"(h1:[^"]+)"',lock):raise ValueError('Provider does not match committed Terraform lock')
            archive=Path(directory)/'libvirt-linux_amd64.tar.gz'
            provider_archive(provider,archive)
            upload(archive,archive.name,digest(archive))
        names=set(artifacts)|{'libvirt-linux_amd64.tar.gz'}
        missing=names-stored.keys()
        if missing:
            print('Not imported yet: '+', '.join(sorted(missing))+'. Complete-set marker was not written.')
        else:
            for name,spec in artifacts.items():
                if stored[name]['sha256']!=spec['sha256']:raise ValueError('Pinned asset mismatch')
            path=Path(directory)/'manifest.json'
            path.write_text(json.dumps({name:stored[name] for name in sorted(names)},sort_keys=True)+'\n')
            upload(path,path.name,digest(path))
            print('Infrastructure package set is complete.')
    print('Package registry: '+project['web_url']+'/-/packages')


if __name__=='__main__':
    main()
