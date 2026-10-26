#!/usr/bin/env python3
"""Materialize each repository's thin, versioned config/ci entry from the catalog."""
import argparse
import json
from pathlib import Path
from catalog import read_catalog, MANUAL_BUILD_TYPES


def files(name,spec):
    descriptor={'project':name,**{k:v for k,v in spec.items() if k!='workspace_path'}}
    variables={**spec.get('variables',{}),'LAB_APPLICATION':str(spec['type']=='application').lower(),
               'LAB_FRONTEND':str(spec['type']=='frontend').lower(),'LAB_HEAVY_BUILD':str(spec['type'] in MANUAL_BUILD_TYPES).lower()}
    include=('include:\n  - local: /.gitlab-ci.yml\n' if spec['type']=='ci' else
        'include:\n  - project: "$LAB_CI_PATH"\n    ref: "$LAB_CI_REF"\n    file: /ci/project.gitlab-ci.yml\n')
    pipeline='# Shared steps are pinned by the lab bootstrap; project settings stay here.\n'+include
    pipeline+='variables:\n'+''.join('  '+k+': '+json.dumps(v)+'\n' for k,v in sorted(variables.items()))
    return {'project.json':json.dumps(descriptor,indent=2)+'\n','pipeline.yml':pipeline,
            'github-actions.yml':(Path(__file__).resolve().parents[1]/'examples/github-actions.yml').read_text()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace',type=Path)
    parser.add_argument('--check',action='store_true',help='Validate existing entries without writing')
    parser.add_argument('--update',action='store_true',help='Update existing generated CI entries after catalog edits')
    args=parser.parse_args()
    for name,spec in read_catalog().items():
        root=args.workspace/spec.get('workspace_path',name)
        if not (root/'.git').exists(): raise ValueError('Missing checkout: '+name)
        for filename,content in files(name,spec).items():
            path=root/'config/ci'/filename
            if path.exists() and path.read_text()==content: continue
            if args.check: raise ValueError('Missing/stale CI entry: '+name+'/'+filename)
            if path.exists() and not args.update: raise ValueError('Existing CI entry differs; inspect before --update: '+str(path))
            path.parent.mkdir(parents=True,exist_ok=True); path.write_text(content)
        print(name+': config/ci entry verified' if args.check else name+': config/ci entry ready')


if __name__=='__main__': main()
