"""The Compose adapter keeps application identity and limits volume initialization."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from monolith import deploy


class MonolithTests(unittest.TestCase):
    def test_both_products_initialize_only_configuration_as_the_image_user(self):
        for product in ('myscoutee-backend', 'myscoutee-template'):
            with self.subTest(product=product), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                services = ['profilemanagement', 'nginx', 'minio', 'mcp']
                if product == 'myscoutee-backend': services += ['registry', 'payment-simulator']
                spec = {'project': product + '-ci-monolith', 'compose': 'server/docker-compose.e2e.yml',
                        'images': {name: name for name in services},
                        'apiEnvironment': {'MEMBER_USER': ''}, 'httpPort': 18081, 'httpsPort': 18443, 'stunPort': 13479}
                source = root / 'config/ci/monolith.json'
                source.parent.mkdir(parents=True)
                source.write_text(json.dumps(spec))
                for relative in ('server/docker/scripts/prepare_dev_runtime_directories.sh',
                                 'server/docker/scripts/ensure_operator_configuration_master_key.sh',
                                 'server/docker/images/profilemanagement/e2e/entrypoint.sh'):
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('#!/bin/sh\nexit 0\n')
                inventory = [{'service': image, 'imageId': 'sha256:' + image} for image in spec['images'].values()]
                spring = root / 'config/nginx/http/spring.conf'
                spring.parent.mkdir(parents=True)
                spring.write_text('return 308 https://$server_name$request_uri;')
                state = root / '.lab'
                state.mkdir()
                (state / 'images.json').write_text(json.dumps(inventory))
                config = {'services': {name: {} for name in {*spec['images'], 'stun'}},
                          'volumes': {'operator-configuration': {}}, 'networks': {}}
                config['services']['profilemanagement'] = {'environment': {'MEMBER_USER': 'fixture-user'}, 'volumes': [
                    {'type': 'volume', 'source': 'operator-configuration', 'target': '/etc/myscoutee/configuration'}]}
                commands = []
                class Candidate:
                    release = {'version': '1.5.1'}
                    def cmd(self, *args, **kwargs):
                        commands.append(args)
                        if args[:2] == ('docker', 'compose') and 'config' in args:
                            return json.dumps(config)
                        if args[:3] == ('docker', 'image', 'inspect'): return '10001:10001'
                        if args[:2] == ('docker', 'inspect'):
                            service = args[-1].removeprefix(spec['project'] + '-')
                            return 'sha256:' + spec['images'][service]
                        return ''
                candidate = Candidate()
                candidate.root, candidate.state = root, state
                deploy(candidate)
                rendered = json.loads((state / 'monolith.compose.json').read_text())
                initializer = rendered['services']['runtime-directories']
                api = rendered['services']['profilemanagement']
                self.assertEqual(initializer['network_mode'], 'none')
                self.assertEqual(initializer['environment']['MYSCOUTEE_RUNTIME_UID'], '10001')
                self.assertEqual([v['source'] for v in initializer['volumes'] if v['type'] == 'volume'], ['operator-configuration'])
                self.assertEqual(api['depends_on']['runtime-directories']['condition'], 'service_completed_successfully')
                self.assertEqual((state / 'monolith.spring.conf').read_text(),
                                 'return 308 https://$server_name:18443$request_uri;')
                receipt = json.loads((state / 'deployed-monolith.json').read_text())
                self.assertEqual(receipt['httpUrl'], 'http://localhost:18081')
                self.assertNotIn('user', api)
                self.assertEqual(api['environment']['MEMBER_USER'], '')
                for service, image in spec['images'].items():
                    self.assertEqual(rendered['services'][service]['image'], 'sha256:' + image)
                self.assertFalse(any('build' in command for command in commands))
