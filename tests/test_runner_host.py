import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
spec=importlib.util.spec_from_file_location('runner_host',Path(__file__).resolve().parents[1]/'scripts/runner-host.py')
host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)


class RunnerHostTests(unittest.TestCase):
    def test_busy_runner_is_not_migrated_and_pause_is_restored(self):
        class API:
            def __init__(self): self.project={'group_id':1};self.writes=[]
            def api(self,method,path,payload=None):
                if method=='PUT': self.writes.append(payload);return
                if path.startswith('/groups/'): return [{'id':2,'paused':False}]
                if '/jobs?' in path: return [{'id':123}]
                return {'tag_list':['lab-build']}
        api=API()
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(host,'INVENTORY',Path(temp)/'inventory.json'), \
                 patch.object(host.os,'geteuid',return_value=0),patch.object(host,'check_owned',return_value=None), \
                 patch.object(host.shutil,'which',return_value='/usr/bin/setfacl'), \
                 patch.object(host.pwd,'getpwnam',return_value=SimpleNamespace(pw_name='operator')), \
                 patch.object(host,'LocalGitLab',return_value=api),patch.object(host,'run') as run:
                with self.assertRaisesRegex(ValueError,'active jobs'):
                    host.apply({'RUNNER_OPERATOR':'operator','RUNNER_STATE_DIR':Path(temp)/'build-runner'})
                run.assert_not_called()
        self.assertEqual(api.writes,[{'paused':True},{'paused':False}])

    def test_refuses_adopting_an_existing_personal_account(self):
        identity=SimpleNamespace(pw_name='operator',pw_uid=1000,pw_dir='/home/USER',pw_shell='/bin/bash')
        with patch.object(host.pwd,'getpwnam',return_value=identity):
            with self.assertRaisesRegex(ValueError,'not owned'):
                host.check_owned({'RUNNER_USER':'operator','RUNNER_HOME':Path('/home/USER')},{})

    def test_refuses_replacing_unowned_system_service(self):
        with tempfile.TemporaryDirectory() as temp:
            unit=Path(temp)/'service';unit.write_text('Administrator service')
            with patch.object(host,'UNIT',unit),patch.object(host.pwd,'getpwnam',side_effect=KeyError):
                with self.assertRaisesRegex(ValueError,'owned service'):
                    host.check_owned({'RUNNER_USER':'ciuser'}, {})
            self.assertEqual(unit.read_text(),'Administrator service')

    def test_transfer_does_not_chown_through_candidate_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);candidate=root/'candidate';candidate.mkdir()
            outside=root/'outside';outside.mkdir();(outside/'secret').write_text('private')
            (candidate/'link').symlink_to(outside,target_is_directory=True)
            identity=SimpleNamespace(pw_name='ciuser',pw_uid=123,pw_gid=123)
            with patch.object(host,'run'),patch.object(host,'traverse'),patch.object(host.os,'chown') as chown:
                host.transfer(candidate,identity)
            self.assertNotIn(outside/'secret',[call.args[0] for call in chown.call_args_list])
            self.assertTrue(all(call.kwargs=={'follow_symlinks':False} for call in chown.call_args_list))

    def test_transferred_state_retains_kvm_and_ssh_private_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'state';root.mkdir(mode=0o770)
            key=root/'id_ed25519';key.write_text('test only');key.chmod(0o660)
            tool=root/'tool';tool.write_text('test only');tool.chmod(0o770)
            identity=SimpleNamespace(pw_name='ciuser',pw_uid=123,pw_gid=123)
            with patch.object(host,'run') as run,patch.object(host,'traverse'),patch.object(host.os,'chown'):
                host.transfer(root,identity)
            self.assertEqual(root.stat().st_mode & 0o777,0o700)
            self.assertEqual(key.stat().st_mode & 0o777,0o600)
            self.assertEqual(tool.stat().st_mode & 0o777,0o700)
            self.assertIn(('setfacl','-R','-P','-b',root),[call.args for call in run.call_args_list])
            self.assertIn(('setfacl','-R','-P','-k',root),[call.args for call in run.call_args_list])

    def test_paths_refuse_systemd_substitution_and_links(self):
        for value in ('/tmp/%u','/tmp/path\nUser=root','/tmp/with space'):
            with self.assertRaises(ValueError): host.path(value)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'real').mkdir();(root/'link').symlink_to(root/'real')
            with self.assertRaisesRegex(ValueError,'symlink'): host.path(str(root/'link'))

    def test_service_drops_identity_and_has_no_boot_enablement(self):
        config={'RUNNER_USER':'ciuser','RUNNER_STATE_DIR':Path('/srv/ci/.local/state/build-runner'),
            'RUNNER_HOME':Path('/srv/ci/.local/home'),'RUNNER_TOOL_DIRS':[Path('/opt/jdk')],
            'RUNNER_JAVA_HOME':Path('/opt/jdk')}
        content=host.unit(config)
        self.assertIn('User=ciuser\nGroup=ciuser',content)
        self.assertIn('UMask=0077',content)
        self.assertNotIn('[Install]',content)
        self.assertNotIn('ExecStart=sudo',content)
