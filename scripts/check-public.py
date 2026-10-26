#!/usr/bin/env python3
"""Check publishable files, without reading ignored local credentials."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ['.gitattributes', '.dockerignore', '.gitignore', '.env.example', '.gitlab-ci.yml', 'compose.yaml', 'README.md',
          'LICENSE', 'scripts', 'tests', 'examples', 'guides', 'runner', 'ci', 'config/ci', '.gitlab/agents', 'compose.kvm.yaml']
PATTERNS = [re.compile(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----'),
            re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|glpat-[A-Za-z0-9_-]{20,}|glrt-[A-Za-z0-9_-]{20,})'),
            re.compile(r'/home/' + r'(?!USER(?:/|\b))[a-zA-Z0-9_-]+/')]


def public_files():
    paths = []
    for name in PUBLIC:
        entry = ROOT/name
        if entry.is_dir():
            paths.extend(p for p in entry.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
        elif entry.is_file():
            paths.append(entry)
    return sorted(paths)


def check():
    for path in public_files():
        if path.is_symlink() or path.suffix in ('.pem', '.key', '.env', '.credentials'):
            raise ValueError(f'Private or linked file in public inventory: {path.relative_to(ROOT)}')
        # Generated PDFs and the reviewed brand logo have versioned text sources.
        if path.suffix in ('.pdf', '.png'):
            continue
        data = path.read_text()
        if any(pattern.search(data) for pattern in PATTERNS):
            raise ValueError(f'Potential private data: {path.relative_to(ROOT)} (value withheld)')
    for path in (ROOT/'scripts').glob('*.sh'):
        subprocess.run(['bash', '-n', str(path)], check=True)
    print(f'Public inventory checked: {len(public_files())} files; shell syntax passed.')


if __name__ == '__main__':
    check()
