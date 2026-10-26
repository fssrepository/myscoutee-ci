import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from catalog import read_catalog, order, consumers


class CatalogTests(unittest.TestCase):
    def test_all_projects_have_acyclic_release_dependencies(self):
        projects = read_catalog()
        result = order(projects)
        self.assertEqual(len(result), len(projects))
        for name, item in projects.items():
            for dependency in item['depends_on']:
                self.assertLess(result.index(dependency), result.index(name))

    def test_template_never_inherits_backend_only_services(self):
        chain = order(read_catalog(), ['myscoutee-template'])
        self.assertIn('myscoutee-template-frontend', chain)
        self.assertNotIn('myscoutee-backend', chain)
        self.assertNotIn('myscoutee-payment-simulator', chain)
        self.assertNotIn('myscoutee-registry', chain)

    def test_fixture_relationship_is_not_a_release_cycle(self):
        data = read_catalog()
        self.assertIn('myscoutee-backend', data['myscoutee-packaging']['fixtures'])
        self.assertLess(order(data).index('myscoutee-packaging'), order(data).index('myscoutee-backend'))

    def test_components_release_triggers_both_frontends(self):
        self.assertEqual(consumers(read_catalog(),'myscoutee-components'), ['myscoutee','myscoutee-template-frontend'])

    def test_cycles_and_unknown_dependencies_fail(self):
        with self.assertRaises(ValueError):
            order({'a':{'type':'npm','depends_on':['a']}})
        with self.assertRaises(ValueError):
            order({'a':{'type':'npm','depends_on':['b']}})
