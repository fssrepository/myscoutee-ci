#!/usr/bin/env python3
"""Release identity belongs to the pipeline, not to mutable dependency tags."""
import re

VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z')
RELEASE = re.compile(r'(?:\[[A-Z][A-Z0-9]*-[0-9]+\]\s+)?release: (major|minor|patch)(?:\s|$)')


def release_kind(title):
    match = RELEASE.match(title)
    return match.group(1) if match else None


def next_version(current, kind):
    match = VERSION.fullmatch(current)
    if not match or kind not in ('major', 'minor', 'patch'):
        raise ValueError('Expected a stable SemVer and major, minor or patch')
    major, minor, patch = map(int, match.groups())
    if kind == 'major':
        return f'{major + 1}.0.0'
    if kind == 'minor':
        return f'{major}.{minor + 1}.0'
    return f'{major}.{minor}.{patch + 1}'


def plan(baseline, tags, title):
    kind = release_kind(title)
    if kind is None:
        raise ValueError('Release commit must start with release: major, minor or patch')
    candidates = [baseline] + [tag[1:] for tag in tags if tag.startswith('v') and VERSION.fullmatch(tag[1:])]
    if not VERSION.fullmatch(baseline):
        raise ValueError('Invalid baseline version')
    previous = max(candidates, key=lambda value: tuple(map(int, value.split('.'))))
    return {'previous': previous, 'version': next_version(previous, kind), 'kind': kind,
            'delivery': 'deb' if kind == 'major' else 'partial'}
