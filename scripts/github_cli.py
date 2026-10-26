"""Provide the pinned GitHub CLI when a native runner has no system installation."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def ensure():
    if shutil.which('gh'):
        return
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64'):
        raise ValueError('Install GitHub CLI on this runner architecture')
    spec = json.loads((ROOT/'ci/tools.json').read_text())['githubCli']
    # Shared between this runner's pipelines, inside its existing private state.
    base = Path(os.environ.get('CI_BUILDS_DIR', ROOT/'.local'))/'tools'
    directory = base/('gh-'+spec['version'])
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    binary = directory/'gh'
    with (directory/'install.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not binary.is_file():
            print('Installing checksum-pinned GitHub CLI '+spec['version'], flush=True)
            with tempfile.TemporaryDirectory(dir=directory) as temporary:
                archive = Path(temporary)/'gh.tar.gz'
                with urllib.request.urlopen(spec['url'], timeout=120) as response, archive.open('wb') as output:
                    shutil.copyfileobj(response, output)
                if hashlib.sha256(archive.read_bytes()).hexdigest() != spec['sha256']:
                    raise ValueError('GitHub CLI checksum mismatch')
                executable = Path(temporary)/'gh'
                with tarfile.open(archive) as package:
                    member = package.getmember(spec['member'])
                    if not member.isfile():
                        raise ValueError('GitHub CLI archive member is not a regular file')
                    with package.extractfile(member) as source, executable.open('wb') as output:
                        shutil.copyfileobj(source, output)
                executable.chmod(0o700)
                executable.replace(binary)
    os.environ['PATH'] = str(directory)+os.pathsep+os.environ.get('PATH', '')
