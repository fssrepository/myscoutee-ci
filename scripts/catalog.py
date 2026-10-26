#!/usr/bin/env python3
"""Workspace ownership and release dependencies; fixtures are not release edges."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPES = {'npm', 'angular-library', 'frontend', 'java-base', 'java-client',
         'go-image', 'nginx-image', 'python-deb', 'application', 'source', 'legacy-source', 'ci'}
# Normal compilation is automatic. This recipe's build itself creates a DEB;
# application DEB and KVM assembly have separate manual jobs.
MANUAL_BUILD_TYPES = {'python-deb'}


def read_catalog():
    return json.loads((ROOT/'ci/projects.json').read_text())


def order(projects, selected=None):
    result, visiting, visited = [], set(), set()
    def visit(name):
        if name not in projects:
            raise ValueError('Unknown dependency: '+name)
        if name in visiting:
            raise ValueError('Dependency cycle: '+name)
        if name in visited:
            return
        if projects[name]['type'] not in TYPES:
            raise ValueError('Unknown recipe type: '+name)
        visiting.add(name)
        for dependency in projects[name].get('depends_on', []):
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
        result.append(name)
    for name in selected or projects:
        visit(name)
    return result


def consumers(projects, dependency):
    return sorted(name for name, item in projects.items() if dependency in item.get('depends_on', []))


if __name__ == '__main__':
    data = read_catalog()
    for name in order(data):
        print(name, data[name]['type'], '->', ', '.join(consumers(data, name)) or '(no consumers)')
