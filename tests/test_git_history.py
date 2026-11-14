from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from matsugit.git_history import entries, read


@unittest.skipUnless(shutil.which('git'), 'Git required')
class GitHistoryTests(unittest.TestCase):
    def test_rename_and_scoped_read_leave_checkout_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            def git(*args):
                return subprocess.check_output(['git','-C',str(root),*args])
            git('init','-q','-b','main')
            git('config','user.name','Test Author')
            git('config','user.email','test@example.invalid')
            source = root/'old.md'
            source.write_text('## First\nOriginal\n')
            git('add','old.md'); git('commit','-qm','First')
            git('mv','old.md','new name.md'); git('commit','-qm','Rename')
            source = root/'new name.md'
            source.write_text('## First\nLatest saved\n')
            before = git('status','--porcelain')
            items, repository = entries(str(source))
            self.assertEqual(repository,root)
            self.assertEqual(len(items),2)
            self.assertEqual(items[-1]['path'],'old.md')
            for item in items:
                self.assertEqual(read(str(source),item['id'])['text'],'## First\nOriginal\n')
            with self.assertRaisesRegex(ValueError,'this document'):
                read(str(source),'git:'+'0'*40)
            self.assertEqual(source.read_text(),'## First\nLatest saved\n')
            self.assertEqual(git('status','--porcelain'),before)
