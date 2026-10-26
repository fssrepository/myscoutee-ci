"""Reconcile existing dashboards without overwriting environment settings."""
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from kubernetes import configure_environment, dashboard


class DashboardTests(unittest.TestCase):
    def test_registration_repairs_missing_binding_and_is_idempotent(self):
        class API:
            def __init__(self):
                self.environment = {'id': 3, 'name': 'kvm', 'external_url': 'https://app.example',
                                    'cluster_agent': None, 'kubernetes_namespace': None}
                self.writes = []

            def api(self, method, path, payload=None):
                if method == 'GET':
                    return [self.environment] if '?' in path else self.environment
                raise AssertionError('Shared agent bindings must use GraphQL')

            def graphql(self, query, variables):
                payload=variables['input']
                self.writes.append(payload)
                self.environment.update(cluster_agent={'id': 1},
                                        kubernetes_namespace=payload['kubernetesNamespace'])
                return {'environmentUpdate': {'errors': []}}

        lab = API()
        for _ in range(2):
            self.assertEqual(configure_environment(lab, '/projects/14', {'id': 1},
                             {'environment': 'kvm', 'namespace': 'product'}), 3)
        self.assertEqual(lab.writes, [{'id': 'gid://gitlab/Environment/3',
                         'clusterAgentId': 'gid://gitlab/Clusters::Agent/1', 'kubernetesNamespace': 'product'}])
        self.assertEqual(lab.environment['external_url'], 'https://app.example')

    def test_new_environment_uses_declared_agent_and_namespace(self):
        class API:
            def api(self, method, path, payload=None):
                if method == 'GET': return [] if '?' in path else {'id': 4}
                self.created = (method, path, payload)
                return {'id': 4}

            def graphql(self, query, variables):
                self.binding=variables['input']
                return {'environmentUpdate': {'errors': []}}

        lab = API()
        self.assertEqual(configure_environment(lab, '/projects/15', {'id': 2},
                         {'environment': 'kvm', 'namespace': 'template'}), 4)
        self.assertEqual(lab.created, ('POST', '/projects/15/environments',
                         {'name': 'kvm'}))
        self.assertEqual(lab.binding['clusterAgentId'], 'gid://gitlab/Clusters::Agent/2')
        self.assertEqual(lab.binding['kubernetesNamespace'], 'template')

    def test_ready_pod_without_agent_connection_is_not_success(self):
        class API:
            def api(self, *args):
                return [{'id': 1, 'name': 'backend-kvm', 'config_project': {'path_with_namespace': 'group/ci'}}]

            def graphql(self, *args):
                return {'project': {'clusterAgent': {'connections': {'nodes': []}}}}

        with patch('kubernetes.time.sleep'), patch('builtins.print'), patch('kubernetes.configure_environment') as configure:
            with self.assertRaisesRegex(RuntimeError, 'not connected'):
                dashboard(API(), 'group/myscoutee-backend', 'group/ci')
            configure.assert_not_called()


if __name__ == '__main__':
    unittest.main()
