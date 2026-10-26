#!/usr/bin/env python3
"""Explicitly install the versioned conversion; never push or dispatch it."""
import argparse
from pathlib import Path
from catalog import read_catalog

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('workspace',type=Path)
parser.add_argument('--project',action='append')
args=parser.parse_args()
for name,spec in read_catalog().items():
    if args.project and name not in args.project: continue
    root=args.workspace/spec.get('workspace_path',name)
    source=root/'config/ci/github-actions.yml'
    target=root/'.github/workflows/laboratory.yml'
    content=source.read_text()
    if target.exists() and target.read_text()!=content:
        raise ValueError('Existing workflow differs; review before replacement: '+name)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(content)
    print(name+': installed locally; review and commit explicitly to activate')
