"""Check scoped FILE inputs without SSH or access to operator credentials."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class RemoteInputsTests(unittest.TestCase):
    def test_file_inputs_replace_operator_paths_and_are_cleaned(self):
        helper = Path(__file__).resolve().parents[1] / 'scripts/remote.sh'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'client-tools').mkdir()
            (root / 'client-tools/remote-transport.sh').write_text('''
remote_transport_setup() {
  test "$REMOTE_KEY_FILE" = "$LAB_SSH_PRIVATE_KEY"
  test "$REMOTE_SSH_OPTIONS" = "-o ConnectTimeout=8 -o UserKnownHostsFile=$LAB_SSH_KNOWN_HOSTS"
  test "$LOCAL_FORWARD_PORTS" = '8080:80,8443:443'
  test "$(stat -c %a "$config")" = 600
  test "$(stat -c %a "$REMOTE_KEY_FILE")" = 600
}
remote_transport_cleanup() { :; }
''')
            (root / 'input.env').write_text('REMOTE_KEY_FILE=/unavailable/operator/key\n'
                'REMOTE_SSH_OPTIONS="-o ConnectTimeout=8"\nREMOTE_HOST_KEY_CHECKING=yes\n')
            (root / 'key').write_text('fixture-only')
            (root / 'known-hosts').write_text('fixture-only')
            result = subprocess.run(['bash', '-ec',
                'state="$1"; packaging="$1"; target=vmware; source "$2"; prepare_remote_transport',
                '_', str(root), str(helper)], env={**os.environ,
                    'LAB_INSTALL_CONFIG': str(root / 'input.env'),
                    'LAB_SSH_PRIVATE_KEY': str(root / 'key'),
                    'LAB_SSH_KNOWN_HOSTS': str(root / 'known-hosts'),
                    'LAB_FORWARD_PORTS': '8080:80,8443:443'}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertFalse((root / 'install-vmware.env').exists())
            self.assertTrue((root / 'input.env').exists())
