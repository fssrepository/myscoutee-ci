"""Exercise real source transformations without builds or external writes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import tarfile
import unittest
from contextlib import nullcontext
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from configure import load_env, resolve, upsert
from project import Project, digest


class ConfigurationTests(unittest.TestCase):
    def test_maven_file_credentials_survive_the_packaging_shell(self):
        for name in ('myscoutee-backend','myscoutee-template'):
            with self.subTest(project=name), tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'gradle.properties'
                path.write_text('gpr.user=fixture-user\ngpr.key=fixture-token\n')
                with patch.dict(os.environ,{'CI_PROJECT_DIR':directory,'CI_PROJECT_NAME':name,
                        'LAB_GRADLE_PROPERTIES':str(path)},clear=True):
                    Project()
                    result=subprocess.run(['/bin/sh','-c',
                        'test "$GITHUB_ACTOR" = fixture-user && test "$GITHUB_TOKEN" = fixture-token'],
                        capture_output=True,text=True)
                    self.assertEqual(result.returncode,0)
                    self.assertEqual(result.stdout,'')

    def test_dotenv_never_executes_or_expands_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'
            path.write_text('GROUP=myscoutee\nTEXT="$(touch never)"\nEMPTY=\n# comment\n')
            self.assertEqual(load_env(path),{'GROUP':'myscoutee','TEXT':'$(touch never)','EMPTY':''})
            self.assertFalse((Path(directory)/'never').exists())

    def test_public_defaults_and_private_file_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory); (path/'secret').write_text('private test value')
            self.assertEqual(resolve({'value':'public'}, {}, path),'public')
            self.assertEqual(resolve({'from_env':'KEY','from_file':True},{'KEY':'secret'},path),'private test value')
            with self.assertRaises(ValueError): resolve({'from_env':'KEY','required':True},{},path)

    def test_reconcile_is_idempotent_and_scoped(self):
        class API:
            def __init__(self): self.records=[]; self.writes=[]
            def api(self,method,path,payload=None):
                if method=='GET': return self.records
                self.writes.append((method,path,payload)); self.records=[payload]; return payload
        api=API()
        spec={'key':'TARGET','environment':'vmware','protected':True}
        upsert(api,'/projects/1',spec,'first')
        upsert(api,'/projects/1',spec,'first')
        self.assertEqual(len(api.writes),1)
        upsert(api,'/projects/1',spec,'second')
        self.assertEqual(api.writes[-1][0],'PUT')
        self.assertIn('filter%5Benvironment_scope%5D=vmware',api.writes[-1][1])


class CandidateTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('git'), 'Native Git Pages integration')
    def test_pages_commit_uses_built_docs_without_cloning_or_source_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'CI_PROJECT_DIR': directory, 'CI_PROJECT_NAME': 'myscoutee'}, clear=True):
            root=Path(directory)
            subprocess.run(['git','init','-q',str(root)],check=True)
            (root/'package.json').write_text('{"version":"1.5.0"}\n')
            subprocess.run(['git','-C',str(root),'add','package.json'],check=True)
            subprocess.run(['git','-C',str(root),'-c','user.name=Test',
                '-c','user.email=test@example.invalid','commit','-qm','source'],check=True)
            source=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
            candidate=Project()
            candidate.release={'version':'1.5.1','pipeline':'42','source':source}
            docs=root/'built-docs';docs.mkdir()
            (docs/'index.html').write_text('<h1>Pages</h1>')
            (docs/'.nojekyll').touch()
            archive=candidate.dist/'myscoutee-1.5.1-pages.tar.gz'
            with tarfile.open(archive,'w:gz') as output:
                for file in docs.iterdir(): output.add(file,arcname=file.name)
            first=candidate.pages_commit(None)
            files=subprocess.check_output(['git','-C',str(root),'ls-tree','-r','--name-only',first],text=True).splitlines()
            self.assertEqual(files,['docs/.nojekyll','docs/index.html'])
            self.assertEqual(candidate.pages_commit(first),first)
            (docs/'index.html').write_text('<h1>Updated</h1>')
            with tarfile.open(archive,'w:gz') as output:
                for file in docs.iterdir(): output.add(file,arcname=file.name)
            second=candidate.pages_commit(first)
            self.assertEqual(subprocess.check_output(['git','-C',str(root),'rev-parse',second+'^'],text=True).strip(),first)
            self.assertEqual(subprocess.check_output(['git','-C',str(root),'diff-tree',
                '--no-commit-id','--name-only','-r',second],text=True).splitlines(),['docs/index.html'])

    def test_pages_requires_github_cli_before_preparing_publication(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'CI_PROJECT_DIR': directory, 'CI_PROJECT_NAME': 'myscoutee',
                'CI_PROJECT_ID': '12', 'GH_TOKEN': 'fixture',
                'LAB_GITHUB_REPOSITORY': 'example/myscoutee'}, clear=True):
            candidate = Project()
            candidate.release = {'version': '1.5.1', 'pipeline': '42'}
            with patch.object(candidate, 'verify_artifacts'), \
                    patch('github_cli.ensure', side_effect=ValueError('GitHub CLI unavailable')) as ensure, \
                    patch.object(candidate, 'cmd') as command:
                with self.assertRaisesRegex(ValueError, 'GitHub CLI unavailable'):
                    candidate.pages()
            ensure.assert_called_once_with()
            command.assert_not_called()
            self.assertFalse((candidate.state / 'pages-publish').exists())

    def test_infra_start_reconciles_terraform_without_building_application(self):
        for name in ('myscoutee-backend', 'myscoutee-template'):
            with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                    'CI_PROJECT_DIR': directory, 'CI_PROJECT_NAME': name,
                    'LAB_MICROSERVICES_SOURCE': '/owned/runtime'}, clear=True):
                candidate = Project()
                with patch.object(candidate, 'kvm_runtime', return_value=nullcontext()), \
                     patch('infra_assets.publish') as publish, patch('infra_assets.restore') as restore, \
                     patch.object(candidate, 'cmd') as command:
                    candidate.infra_start()
                publish.assert_called_once_with(candidate)
                restore.assert_called_once_with(candidate)
                self.assertEqual([tuple(map(str, call.args)) for call in command.call_args_list], [
                    ('python3', '/owned/runtime/tools/host.py', 'start'),
                    ('python3', '/owned/runtime/tools/vm.py', 'start')])

    def test_kvm_retry_report_does_not_change_immutable_delivery_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'CI_PROJECT_DIR': directory, 'CI_PROJECT_NAME': 'myscoutee-backend',
                'LAB_MICROSERVICES_SOURCE': '/owned/runtime'}, clear=True):
            candidate = Project()
            lock = candidate.root / 'config/microservices/deploy/images.lock.json'
            lock.parent.mkdir(parents=True)
            lock.write_text(json.dumps({'images': {'help': {'source': 'help:1', 'id': 'sha256:original'}}}))
            plan = candidate.root / 'server/build/microservices/assembly-image-plan.json'
            plan.parent.mkdir(parents=True)
            with patch.object(candidate, 'verify_artifacts'), \
                 patch.object(candidate, 'kvm_runtime', return_value=nullcontext()), \
                 patch.object(candidate, 'cmd'):
                for action in ('build', 'reuse'):
                    lock.write_text(json.dumps({'images': {'help': {'source': 'help:1', 'id': 'sha256:original',
                        'sourceDigests': [] if action == 'build' else ['registry.example/help@sha256:published']}}}))
                    plan.write_text(json.dumps({'help': {'inputFingerprint': 'a' * 64, 'action': action}}))
                    candidate.kvm()
                    self.assertFalse((candidate.dist / 'kvm-assembly-plan.json').exists())
                    self.assertEqual(json.loads((candidate.state / 'kvm-assembly-plan.json').read_text())['help']['action'], action)
                    manifest = (candidate.state / 'artifact-manifest.json').read_bytes()
                    if action == 'build': initial = manifest
                    else: self.assertEqual(manifest, initial)
                lock.write_text(json.dumps({'images': {'help': {'source': 'help:1', 'id': 'sha256:changed'}}}))
                with self.assertRaisesRegex(ValueError, 'image identities changed'):
                    candidate.kvm()

    def test_local_registry_contains_releases_not_candidate_versions(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'CI_PROJECT_DIR': directory, 'CI_PROJECT_NAME': 'myscoutee-backend',
                'CI_REGISTRY': 'registry.test', 'CI_REGISTRY_IMAGE': 'registry.test/product',
                'CI_REGISTRY_USER': 'fixture', 'CI_REGISTRY_PASSWORD': 'fixture'}, clear=True):
            candidate = Project()
            candidate.release = {'version': '1.5.1', 'pipeline': '42'}
            for filename,service in [('images.json','nginx'),('kvm-images.json','help')]:
                (candidate.state / filename).write_text(json.dumps([
                    {'service': service, 'imageId': 'sha256:original'}]))
            with patch.object(candidate, 'cmd', return_value='sha256:original') as command:
                candidate.publish_local_images()
            pushed = [call.args[2] for call in command.call_args_list if call.args[:2] == ('docker', 'push')]
            self.assertEqual(pushed, ['registry.test/product/release/nginx:1.5.1',
                                     'registry.test/product/kvm/help:1.5.1'])

    def test_kvm_verification_uses_the_existing_native_owner(self):
        for name in ('myscoutee-backend','myscoutee-template'):
            with self.subTest(project=name), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{
                    'CI_PROJECT_DIR':directory,'CI_PROJECT_NAME':name,'LAB_TARGET':'kvm',
                    'LAB_VERIFY_URL':'http://wrong-environment.invalid',
                    'LAB_MICROSERVICES_SOURCE':'/owned/runtime'},clear=True):
                candidate=Project(); candidate.release={'version':'1.5.1'}
                with patch.object(candidate,'packaging_command') as command, \
                     patch.object(candidate,'kvm_runtime',return_value=nullcontext()) as runtime, \
                     patch.object(candidate,'cmd') as native:
                    with self.assertRaisesRegex(ValueError,'not successfully deployed'): candidate.verify()
                    command.assert_not_called()
                    (candidate.state/'deployed-kvm.json').write_text(json.dumps({
                        'target':'kvm','version':'1.5.1','installed':True,'url':'http://127.0.0.1:18029'}))
                    candidate.verify()
                    command.assert_not_called()
                    runtime.assert_called_once()
                    native.assert_called_once_with('python3',Path('/owned/runtime/tools/check-public.py'))

    def test_application_release_keeps_artifacts_in_its_own_repository(self):
        for name in ('myscoutee-backend', 'myscoutee-template'):
            repository = 'example/' + name
            environment = {'CI_PROJECT_NAME': name, 'CI_PROJECT_ID': '14',
                'CI_COMMIT_BRANCH': 'master', 'CI_DEFAULT_BRANCH': 'master',
                'CI_API_V4_URL': 'https://gitlab.invalid/api/v4', 'GH_TOKEN': 'test',
                'LAB_SIGNING_KEY': 'provided-key', 'LAB_GITHUB_REPOSITORY': repository,
                'LAB_GITHUB_RELEASE_REPOSITORY': 'example/public-frontend'}
            with self.subTest(project=name), tempfile.TemporaryDirectory() as directory, \
                    patch.dict(os.environ, {**environment, 'CI_PROJECT_DIR': directory}, clear=True):
                candidate = Project()
                candidate.release = {'version': '1.5.1', 'delivery': 'partial'}
                artifact = candidate.dist / 'client-tools.tar.gz'
                artifact.write_bytes(b'tested package')
                deb = candidate.dist / (name + '_1.5.1_amd64.deb')
                deb.write_bytes(b'already packaged DEB')
                def command(*args, **kwargs):
                    if 'matching-refs' in str(args): return '[]'
                    if args[:2] == ('git', 'rev-parse'): return 'a' * 40
                    return ''
                with patch('github_cli.ensure'), patch('project.api', return_value=[]) as api, \
                        patch.object(candidate, 'verify_artifacts'), \
                        patch.object(candidate, 'packaging_command'), \
                        patch.object(candidate, 'seal_partial'), \
                        patch.object(candidate, 'sign_deb') as sign_deb, \
                        patch.object(candidate, 'snapshot'), \
                        patch.object(candidate, 'merge_release') as merge, \
                        patch.object(candidate, 'push_tag') as gitlab_tag, \
                        patch.object(candidate, 'push_github_tag') as github_tag, \
                        patch.object(candidate, 'upload') as upload, \
                        patch.object(candidate, 'cmd', side_effect=command) as calls:
                    candidate.release_phase()
                gitlab_tag.assert_called_once_with('v1.5.1')
                merge.assert_called_once_with()
                github_tag.assert_called_once_with(repository, 'v1.5.1')
                sign_deb.assert_called_once_with()
                self.assertEqual({c.args[0] for c in upload.call_args_list}, {artifact, deb})
                self.assertTrue(all('/packages/generic/'+name+'/1.5.1/' in c.args[1] for c in upload.call_args_list))
                publications = [c.args for c in calls.call_args_list
                                if c.args[:3] == ('gh', 'release', 'create')]
                self.assertEqual(len(publications), 1)
                self.assertIn(artifact, publications[0])
                self.assertIn(deb, publications[0])
                self.assertEqual(publications[0][publications[0].index('--repo') + 1], repository)
                self.assertFalse(any('public-frontend' in str(c.args) for c in calls.call_args_list))
                self.assertEqual(api.call_args.args[:2], ('POST', '/projects/14/releases'))
                self.assertEqual(json.loads((candidate.state / 'published.json').read_text())['version'], '1.5.1')

    def test_image_projects_publish_the_recorded_build_without_rebuilding(self):
        for name in ('myscoutee-nginx','myscoutee-mcp','myscoutee-registry','myscoutee-payment-simulator'):
            with self.subTest(project=name), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                    'CI_PROJECT_NAME':name,'CI_PROJECT_DIR':directory,'CI_PROJECT_ID':'9',
                    'CI_COMMIT_BRANCH':'master','CI_DEFAULT_BRANCH':'master',
                    'CI_API_V4_URL':'https://gitlab.test/api/v4', 'GH_TOKEN':'fixture',
                    'LAB_GITHUB_REPOSITORY':'example/'+name},clear=True):
                candidate=Project(); candidate.release={'version':'1.5.1'}
                reference='ghcr.io/example/'+name+':1.5.1'
                (candidate.state/'images.json').write_text(json.dumps([
                    {'reference':reference,'imageId':'sha256:built'}]))
                def command(*args,**kwargs):
                    if 'matching-refs' in str(args): return '[]'
                    if args[:3]==('docker','image','inspect'):
                        return 'sha256:built' if '{{.Id}}' in args else reference+'@sha256:digest'
                    return 'a'*40 if args[:2]==('git','rev-parse') else ''
                with patch('github_cli.ensure'), patch('project.api',return_value=[]), \
                        patch.object(candidate,'verify_artifacts'),patch.object(candidate,'snapshot'), \
                        patch.object(candidate,'publish_local_images') as local, \
                        patch.object(candidate,'push_tag'),patch.object(candidate,'push_github_tag'), \
                        patch.object(candidate,'upload'),patch.object(candidate,'merge_release'), \
                        patch.object(candidate,'cmd',side_effect=command) as calls:
                    candidate.release_phase()
                operations=[c.args for c in calls.call_args_list]
                self.assertIn(('docker','push',reference),operations)
                self.assertIn(('docker','pull',reference),operations)
                self.assertFalse(any(c[:2]==('docker','build') for c in operations))
                local.assert_called_once_with()
                self.assertEqual(json.loads((candidate.dist/'published-images.json').read_text())['images'][0]['imageId'],'sha256:built')

    def test_application_records_separately_released_images_without_rebuilding(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{
            'CI_PROJECT_DIR':directory,'CI_PROJECT_NAME':'myscoutee-backend'},clear=True):
            candidate=Project(); candidate.release={'version':'1.5.1'}
            policy=candidate.root/'config/packaging/release-project.json'; policy.parent.mkdir(parents=True)
            policy.write_text(json.dumps({'images':[{'service':'registry-demo','container':'registry-demo','repository':'myscoutee-registry','tagSuffix':'prod'}]}))
            source='ghcr.io/example/registry:1.5.0@sha256:'+'a'*64
            def execute(*args,**kwargs):
                if args[:2]==('docker','compose'): return json.dumps({'services':{'registry':{'container_name':'registry-demo','image':source}}})
                if args[:3]==('docker','image','inspect'): return 'sha256:'+'b'*64
                return ''
            with patch.object(candidate,'cmd',side_effect=execute) as command:
                candidate.capture_application_images()
            self.assertIn(('docker','pull',source),[call.args for call in command.call_args_list])
            self.assertIn(('docker','tag',source,'myscoutee-registry:1.5.1-prod'),[call.args for call in command.call_args_list])
            self.assertEqual(json.loads((candidate.state/'images.json').read_text())[0]['source'],source)
            source='ghcr.io/example/registry:latest'
            with patch.object(candidate,'cmd',side_effect=execute) as command:
                with self.assertRaisesRegex(ValueError,'digest-pinned'): candidate.capture_application_images()
            self.assertEqual(command.call_count,1)

    def test_feature_release_stops_before_artifacts_or_external_writes(self):
        for name in ('myscoutee-backend','myscoutee-template'):
            with self.subTest(project=name), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{
                'CI_PROJECT_DIR':directory,'CI_PROJECT_NAME':name,
                'CI_COMMIT_BRANCH':'feature/MSC-129-ci-1.5.1','CI_DEFAULT_BRANCH':'master'},clear=True):
                candidate=Project()
                with patch.object(candidate,'verify_artifacts') as verify, patch.object(candidate,'cmd') as command:
                    with self.assertRaisesRegex(ValueError,'cannot be released'): candidate.release_phase()
                verify.assert_not_called(); command.assert_not_called()

    @unittest.skipUnless(shutil.which('git'), 'Native Git prepare integration')
    def test_application_patch_initializes_own_versioned_environment(self):
        for name,filename in [('myscoutee-backend','.env'),('myscoutee-template','.env.example')]:
            with self.subTest(project=name), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{
                'CI_PROJECT_DIR':directory,'CI_PROJECT_NAME':name,'CI_PIPELINE_ID':'151',
                'LAB_SOURCE_BASE':'https://unused.invalid/group','CI_COMMIT_TITLE':'MSC-129: configuration'},clear=True):
                root=Path(directory); (root/'server').mkdir()
                source=root/'server'/filename
                source.write_text('MYSCOUTEE_VERSION=1.5.0\nPROJECT='+name+'\n')
                (root/'VERSION').write_text('1.5.0\n')
                def git(*args): subprocess.run(['git',*args],cwd=root,check=True,capture_output=True)
                git('init','-q'); git('config','user.name','Fixture'); git('config','user.email','fixture@localhost.invalid')
                git('add','.'); git('commit','-qm','baseline'); git('tag','v1.5.0')
                candidate=Project(); candidate.prepare()
                self.assertEqual(candidate.release['version'],'1.5.1')
                self.assertEqual(candidate.release['delivery'],'partial')
                self.assertEqual(source.read_text(),'MYSCOUTEE_VERSION=1.5.1\nPROJECT='+name+'\n')
                self.assertEqual((root/'server/.env').read_text(),source.read_text())

    def test_full_deb_publish_requires_separate_manual_packaging(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{
            'CI_PROJECT_DIR':directory,'CI_PROJECT_NAME':'myscoutee-backend'},clear=True):
            candidate=Project(); candidate.release={'version':'2.0.0','delivery':'deb'}
            policy=candidate.root/'config/packaging/release-project.json'; policy.parent.mkdir(parents=True)
            policy.write_text(json.dumps({'packageName':'myscoutee'}))
            with patch.object(candidate,'deb') as deb, patch.object(candidate,'cmd') as command:
                with self.assertRaisesRegex(ValueError,'manual package:deb'): candidate.sign_deb()
            deb.assert_not_called(); command.assert_not_called()

    def test_automatic_application_package_never_builds_deb(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{
            'CI_PROJECT_DIR':directory,'CI_PROJECT_NAME':'myscoutee-backend'},clear=True):
            candidate=Project(); candidate.release={'version':'2.0.0','delivery':'deb'}
            with patch.object(candidate,'snapshot'), patch.object(candidate,'record_artifacts'), patch.object(candidate,'deb') as deb, patch.object(candidate,'packaging_command') as command:
                candidate.package()
            command.assert_called_once_with('client-tools'); deb.assert_not_called()

    @unittest.skipUnless(shutil.which('git'), 'Git archive integration runs on the native group runner')
    def test_source_archive_contains_candidate_version_not_old_head(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'CI_PROJECT_DIR':directory,'CI_PROJECT_NAME':'myscoutee-skills','CI_PIPELINE_ID':'71','CI_COMMIT_TITLE':'release: minor'},clear=True):
            root=Path(directory)
            def git(*args): return subprocess.run(['git',*args],cwd=root,check=True,capture_output=True,text=True)
            git('init','-q'); git('config','user.name','Fixture'); git('config','user.email','fixture@localhost.invalid')
            # Runner initializes with an empty Git template (no info directory).
            shutil.rmtree(root/'.git/info',ignore_errors=True)
            (root/'VERSION').write_text('1.2.3\n'); git('add','VERSION'); git('commit','-qm','baseline')
            Project().prepare()
            candidate=Project()
            with patch.object(candidate, 'upload', side_effect=AssertionError('Candidate upload')):
                candidate.package()
            import tarfile
            with tarfile.open(candidate.dist/'myscoutee-skills-1.3.0.tar.gz') as archive:
                self.assertEqual(archive.extractfile('myscoutee-skills-1.3.0/VERSION').read(),b'1.3.0\n')
            candidate.verify_artifacts()
            next(candidate.dist.iterdir()).write_text('tampered')
            with self.assertRaises(ValueError): candidate.verify_artifacts()

    @unittest.skipUnless(shutil.which('git'), 'Native Git snapshot integration')
    def test_frontend_snapshot_excludes_generated_docs_and_private_configuration(self):
        for name in ('myscoutee', 'myscoutee-template-frontend'):
            with self.subTest(project=name), tempfile.TemporaryDirectory() as directory, \
                    patch.dict(os.environ, {'CI_PROJECT_DIR': directory, 'CI_PROJECT_NAME': name}, clear=True):
                root = Path(directory)
                def git(*args):
                    return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
                git('init', '-q'); git('config', 'user.name', 'Fixture')
                git('config', 'user.email', 'fixture@localhost.invalid')
                (root / '.gitignore').write_text('/.lab/\n/docs/\n')
                (root / 'docs').mkdir()
                (root / 'source.txt').write_text('old source')
                git('add', '.'); git('commit', '-qm', 'baseline')
                (root / 'source.txt').write_text('new source')
                (root / 'docs/new.js').write_text('new build')
                (root / 'docs/keys').mkdir()
                (root / 'docs/keys/private.json').write_text('private fixture')
                candidate = Project(); candidate.release = {'version': '1.5.1'}
                candidate.snapshot()
                self.assertEqual(git('show', 'HEAD:source.txt'), 'new source')
                tracked = git('ls-tree', '-r', '--name-only', 'HEAD').splitlines()
                self.assertNotIn('docs/new.js', tracked)
                self.assertNotIn('docs/keys/private.json', tracked)
                self.assertFalse(any(p.startswith('.lab/') for p in tracked))

    def test_unpublished_vmware_candidate_deploys_without_release(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'CI_PROJECT_DIR':directory,'CI_PROJECT_NAME':'myscoutee-template','LAB_TARGET':'vmware','LAB_DEPLOY_FORMAT':'deb'},clear=True):
            candidate=Project(); candidate.release={'version':'2.0.0','delivery':'deb'}
            with patch.object(candidate,'verify_artifacts'), patch.object(candidate,'sign_deb') as sign, patch.object(candidate,'cmd') as command:
                candidate.deploy()
            sign.assert_called_once(); self.assertEqual(command.call_args.args[0],'bash')
            self.assertFalse((candidate.state/'published.json').exists())

    def test_partial_uses_product_service_mapping_and_existing_image_id(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'CI_PROJECT_DIR':directory,'CI_PROJECT_NAME':'myscoutee-backend','LAB_TARGET':'vmware','LAB_DEPLOY_FORMAT':'partial','LAB_PARTIAL_SERVICES':'registry'},clear=True):
            candidate=Project(); candidate.release={'version':'1.5.1','delivery':'partial'}
            policy=candidate.root/'config/packaging/release-project.json'; policy.parent.mkdir(parents=True)
            policy.write_text(json.dumps({'clientTools':{'services':[{'name':'registry','imageService':'registry-demo'},
                {'name':'mongodb','container':'mongodb','environment':'MONGO_IMAGE','sameUpstream':True}]}}))
            (candidate.state/'images.json').write_text(json.dumps([{'service':'registry-demo','imageId':'sha256:abc','reference':'old'}]))
            with patch.object(candidate,'verify_artifacts'), patch.object(candidate,'seal_partial'), patch.object(candidate,'cmd') as command:
                candidate.deploy()
            self.assertEqual(command.call_args_list[0].args[-1],'old')
            self.assertEqual(json.loads((candidate.dist/'partial-images.json').read_text())['images'][0]['service'],'registry')

    def test_kvm_private_configuration_is_restored_after_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'CI_PROJECT_DIR':directory,'CI_PROJECT_NAME':'myscoutee-template','LAB_KVM_STATE_ROOT':directory+'/.local/state'},clear=True):
            candidate=Project(); candidate.release={'version':'2.0.0'}
            runtime=candidate.root/'config/microservices/deploy/runtime.json'; runtime.parent.mkdir(parents=True)
            runtime.write_text('original'); runtime.with_name('images.lock.json').write_text('original lock')
            (candidate.state/'kvm-runtime.json').write_text('private')
            (candidate.dist/'kvm-images.lock.json').write_text('new lock')
            with self.assertRaises(RuntimeError):
                with candidate.kvm_runtime():
                    self.assertEqual(runtime.read_text(),'private'); raise RuntimeError('fixture failure')
            self.assertEqual(runtime.read_text(),'original')
            self.assertEqual(runtime.with_name('images.lock.json').read_text(),'original lock')


if __name__=='__main__': unittest.main()
