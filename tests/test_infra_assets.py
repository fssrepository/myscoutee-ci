"""Registry reuse only; the upstream download branch is intentionally untested."""
from pathlib import Path
import sys
import unittest
import tempfile
import urllib.error
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import infra_assets


class RegistryReuseTests(unittest.TestCase):
    def test_complete_registry_skips_download_and_upload(self):
        class Candidate:
            def cmd(self,*args,**kwargs):raise AssertionError('No build or tool installation expected')
            def upload(self,*args,**kwargs):raise AssertionError('No upload expected')
        inputs=(Path('/support'),Path('/state'),{},'0.9.9',{},'http://localhost/packages/')
        with patch.object(infra_assets,'inputs',return_value=inputs), \
             patch.object(infra_assets,'check',return_value={}), \
             patch.object(infra_assets,'download') as download, \
             patch.object(infra_assets.terraform_module,'publish') as publish:
            infra_assets.publish(Candidate())
            download.assert_not_called();publish.assert_not_called()

    def test_interrupted_import_reuses_each_registry_file_without_upstream(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            stored={'guest.deb':{'sha256':'a'*64,'bytes':42},
                    'libvirt-linux_amd64.tar.gz':{'sha256':'b'*64,'bytes':100}}
            class Candidate:
                def cmd(self,*args,**kwargs):raise AssertionError('No provider installation expected')
                def upload(self,path,url):
                    self.uploaded=url.rsplit('/',1)[-1]
            candidate=Candidate()
            inputs=(root,root,{'guest.deb':{'sha256':'a'*64}},'0.9.9',{'id':18,'web_url':'local'},'http://local/set/')
            with patch.object(infra_assets,'inputs',return_value=inputs), \
                 patch.object(infra_assets,'check',side_effect=ValueError(infra_assets.MISSING)), \
                 patch.object(infra_assets,'inventory',return_value=stored), \
                 patch.object(infra_assets,'request',return_value='request'), \
                 patch.object(infra_assets.urllib.request,'urlopen',side_effect=urllib.error.HTTPError('url',404,'missing',{},None)), \
                 patch.object(infra_assets,'download') as download:
                infra_assets.publish(candidate)
                download.assert_not_called()
                self.assertEqual(candidate.uploaded,'manifest.json')
