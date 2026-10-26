import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from retention import candidate, clean, retained


class RetentionTests(unittest.TestCase):
    def test_keeps_newest_candidates_on_each_branch(self):
        rows=[{'id':i,'ref':'master' if i<5 else 'feature/test'} for i in range(1,9)]
        self.assertEqual(retained(rows,2),{3,4,7,8})

    def test_receipts_and_symlinks_protect_working_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary).resolve()/'1';state=directory/'app/.lab';state.mkdir(parents=True)
            (state/'plan.json').write_text(json.dumps({'project':'myscoutee-backend','pipeline':'1'}))
            self.assertIsNotNone(candidate(directory,'myscoutee-backend',1))
            for receipt in ('published.json','deployed-monolith.json','deployed-kvm.json'):
                (state/receipt).write_text('{}')
                self.assertIsNone(candidate(directory,'myscoutee-backend',1))
                (state/receipt).unlink()
            self.assertIsNone(candidate(directory,'myscoutee-template',1))
            self.assertIsNone(candidate(directory,'myscoutee-backend',2))
            link=Path(temporary)/'link';link.symlink_to(directory,target_is_directory=True)
            self.assertIsNone(candidate(link,'myscoutee-backend',1))

    def test_cleanup_is_scoped_and_resumes_runner(self):
        with tempfile.TemporaryDirectory() as temporary:
            state=Path(temporary).resolve();directory=state/'build-runner/builds/14/1'
            local=directory/'myscoutee-backend/.lab';local.mkdir(parents=True)
            (local/'plan.json').write_text('{"project":"myscoutee-backend","pipeline":"1"}')
            writes=[]
            class Lab:
                project={'group_id':1}
                def api(self,method,path,payload=None):
                    if method!='GET':writes.append((method,path,payload));return None
                    if path.startswith('/groups/1/projects'):return [{'id':14,'path':'myscoutee-backend'}]
                    if path.startswith('/groups/1/runners'):return [{'id':2}]
                    if '/repository/branches?' in path:return [{'name':'master'}]
                    if path=='/runners/2':return {'tag_list':['lab-build'],'paused':False}
                    if '/pipelines/1/jobs' in path:return [{'id':11,'name':'release','status':'manual','artifacts':[]}]
                    if '/pipelines?' in path:return [{'id':i,'ref':'master','status':'manual'} for i in (3,2,1)]
                    if '/packages?' in path:return [{'id':9,'name':'myscoutee-backend','version':'candidate-1'},
                        {'id':10,'name':'myscoutee-backend','version':'1.5.1'},
                        {'id':12,'name':'infra-assets','version':'candidate-1'}]
                    if '/registry/repositories?' in path:return []
                    raise AssertionError(path)
            lab=Lab();lab.state=state
            with patch('retention.protected_mounts',return_value=[]):
                clean(lab,{'keep_candidates_per_branch':2},False)
                self.assertTrue(directory.exists());self.assertEqual(writes,[])
                clean(lab,{'keep_candidates_per_branch':2},True)
            self.assertFalse(directory.exists())
            self.assertIn(('DELETE','/projects/14/packages/9',None),writes)
            self.assertNotIn(('DELETE','/projects/14/packages/10',None),writes)
            self.assertNotIn(('DELETE','/projects/14/packages/12',None),writes)
            self.assertEqual(writes[-1],('PUT','/runners/2',{'paused':False}))
