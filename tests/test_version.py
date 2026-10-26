import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('version', Path(__file__).resolve().parents[1]/'scripts/version.py')
version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version)


class VersionTests(unittest.TestCase):
    def test_release_levels_and_delivery(self):
        for kind, expected, delivery in [('major', '2.0.0', 'deb'), ('minor', '1.6.0', 'partial'), ('patch', '1.5.1', 'partial')]:
            with self.subTest(kind=kind):
                actual = version.plan('1.5.0', [], 'release: '+kind)
                self.assertEqual((actual['version'], actual['delivery']), (expected, delivery))

    def test_uses_numeric_latest_release_and_ignores_qa(self):
        self.assertEqual(version.plan('1.5.0', ['v1.9.0', 'v1.10.4', 'v2.0.0-qa.1', 'other'], 'release: patch fix')['version'], '1.10.5')

    def test_task_prefixed_release_levels(self):
        for level in ('major','minor','patch'):
            self.assertEqual(version.release_kind('[MSC-129] release: '+level+' CI configuration'),level)

    def test_major_and_minor_reset_lower_levels(self):
        self.assertEqual(version.next_version('3.8.19', 'major'), '4.0.0')
        self.assertEqual(version.next_version('3.8.19', 'minor'), '3.9.0')

    def test_normal_commits_do_not_release(self):
        for title in ['fix: something', 'docs: release: major', 'release: majorish', 'release: PATCH']:
            self.assertIsNone(version.release_kind(title))

    def test_rejects_ambiguous_versions(self):
        for current in ['01.2.3', '1.2', '1.2.3-qa.1', 'v1.2.3', '1.2.3\n', '$(command)']:
            with self.assertRaises(ValueError):
                version.next_version(current, 'patch')


if __name__ == '__main__':
    unittest.main()
