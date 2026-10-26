"""Release integration uses reviewed branches; publication retries do not republish."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from project import Project


class ReleaseMergeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {
            'CI_PROJECT_NAME': 'myscoutee-sonarqube', 'CI_PROJECT_DIR': self.directory.name,
            'CI_PROJECT_ID': '21', 'CI_DEFAULT_BRANCH': 'master', 'CI_COMMIT_BRANCH': 'master',
            'CI_SERVER_URL': 'https://gitlab.test', 'CI_PROJECT_PATH': 'group/project',
            'LAB_GITHUB_REPOSITORY': 'owner/project'}, clear=True)
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.project = Project()
        self.project.release = {'version': '1.5.1'}
        self.sha = 'a' * 40
        (self.project.state / 'published.json').write_text(json.dumps({
            'version': '1.5.1', 'tag': 'v1.5.1', 'revision': self.sha}))
        self.gl = {'iid': 3, 'state': 'opened', 'sha': self.sha,
                   'detailed_merge_status': 'mergeable', 'web_url': 'https://gitlab.test/mr/3'}
        self.gh = {'number': 4, 'state': 'open', 'head': {'sha': self.sha},
                   'html_url': 'https://github.com/owner/project/pull/4'}
        self.calls = []
        self.github_conflict = False

    def gitlab(self, method, path, payload=None):
        self.calls.append(('gitlab', method, path, payload))
        if method == 'GET' and '?' in path: return []
        if method == 'PUT': return {**self.gl, 'state': 'merged'}
        return self.gl

    def github(self, method, path, payload=None):
        self.calls.append(('github', method, path, payload))
        if 'matching-refs' in path:
            return [{'ref': 'refs/heads/release/v1.5.1', 'object': {'sha': self.sha}}]
        if method == 'GET': return []
        if method == 'POST': return self.gh
        if method == 'PUT':
            if self.github_conflict: raise ValueError('Merge conflict')
            return {'merged': True}

    def integrate(self):
        with patch('github_cli.ensure'), patch('project.api', side_effect=self.gitlab), \
                patch.object(self.project, 'cmd', return_value=self.sha), \
                patch.object(self.project, 'github_api', side_effect=self.github):
            self.project.merge_release()

    def test_merges_exact_published_commit_and_removes_only_release_branch(self):
        self.integrate()
        merges = [c for c in self.calls if c[1] == 'PUT']
        self.assertEqual(len(merges), 2)
        self.assertTrue(all(c[3]['sha'] == self.sha for c in merges))
        self.assertFalse(merges[0][3]['squash'])
        self.assertEqual(merges[1][3]['merge_method'], 'merge')
        self.assertEqual(merges[0][3]['merge_commit_message'], 'Release v1.5.1\n\n[skip ci]')
        self.assertEqual(merges[1][3]['commit_title'], 'Release v1.5.1')
        self.assertIn('[skip ci]', merges[1][3]['commit_message'])
        creates = [c for c in self.calls if c[1] == 'POST']
        self.assertEqual(creates[0][3]['source_branch'], 'release/v1.5.1')
        self.assertEqual(creates[1][3]['head'], 'release/v1.5.1')
        self.assertEqual(self.calls[-1][1:3], ('DELETE', 'repos/owner/project/git/refs/heads/release/v1.5.1'))

    def test_changed_release_branch_cannot_be_merged(self):
        self.gl['sha'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'differs from published'):
            self.integrate()
        self.assertFalse(any(c[1] in ('PUT', 'DELETE') for c in self.calls))

    def test_conflict_preserves_branch_and_retry_does_not_repeat_completed_merge(self):
        self.github_conflict = True
        with self.assertRaisesRegex(ValueError, 'Merge conflict'): self.integrate()
        self.assertFalse(any(c[1] == 'DELETE' for c in self.calls))
        self.assertEqual(set(json.loads((self.project.state / 'release-merges.json').read_text())), {'gitlab'})
        self.calls.clear(); self.github_conflict = False
        self.integrate()
        self.assertFalse(any(c[0] == 'gitlab' for c in self.calls))

    def test_release_retry_only_integrates_existing_publication(self):
        with patch.object(self.project, 'verify_artifacts'), \
                patch.object(self.project, 'merge_release') as merge, \
                patch.object(self.project, 'cmd') as command, patch('project.api') as api:
            self.project.release_phase()
        merge.assert_called_once_with()
        command.assert_not_called(); api.assert_not_called()

    def test_tag_pushes_include_release_branch_and_never_default_branch(self):
        with patch.object(self.project, 'cmd') as command:
            self.project.push_tag('v1.5.1')
            self.project.push_github_tag('owner/project', 'v1.5.1')
        pushes = [c.args for c in command.call_args_list if 'push' in c.args]
        self.assertEqual(len(pushes), 2)
        for args in pushes:
            self.assertIn('refs/tags/v1.5.1:refs/heads/release/v1.5.1', args)
            self.assertIn('--atomic', args)
            self.assertFalse(any('master' in str(a) or '--force' in str(a) for a in args))


if __name__ == '__main__': unittest.main()
