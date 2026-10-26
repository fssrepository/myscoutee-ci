import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from project import Project


class ModulePublicationTests(unittest.TestCase):
    def test_automatic_module_publication_uses_job_identity_only_on_protected_master(self):
        candidate=object.__new__(Project)
        candidate.spec={'terraform_module':{'name':'labkvm','system':'libvirt','version':'1.5.2'}}
        candidate.dist=Path('dist');candidate.release={'version':'1.5.1'}
        environment={'CI_DEFAULT_BRANCH':'master','CI_COMMIT_BRANCH':'master','CI_COMMIT_REF_PROTECTED':'true',
                     'CI_API_V4_URL':'http://gitlab.invalid/api/v4','CI_PROJECT_ID':'18','CI_JOB_TOKEN':'test-job-token'}
        with patch.dict(os.environ,environment,clear=True),patch('project.terraform_module.publish') as publish:
            candidate.publish_terraform_module()
            publish.assert_called_once_with(Path('dist/labkvm-libvirt-1.5.2.tgz'),candidate.spec['terraform_module'],
                '1.5.2',environment['CI_API_V4_URL'],'18','test-job-token',job_token=True)
            publish.reset_mock()
            os.environ['CI_COMMIT_BRANCH']='feature/test'
            candidate.publish_terraform_module()
            publish.assert_not_called()
            os.environ['CI_COMMIT_BRANCH']='master';os.environ['CI_COMMIT_REF_PROTECTED']='false'
            candidate.publish_terraform_module()
            publish.assert_not_called()
