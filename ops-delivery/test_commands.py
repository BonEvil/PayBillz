"""Focused command tests; no changes to real shell profiles or installation."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('ops', Path(__file__).with_name('paybillz.py'))
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)

class CommandTests(unittest.TestCase):
    def test_path_is_idempotent_and_preserves_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / '.bashrc'
            profile.write_text('# existing configuration\n')
            with patch.dict(os.environ, {'SHELL':'/bin/bash'}), patch.object(ops, 'BIN', root / 'a bin'):
                ops.configure_path(root)
                ops.configure_path(root)
            contents = profile.read_text()
            self.assertTrue(contents.startswith('# existing configuration\n'))
            self.assertEqual(contents.count('# PayBillz command'), 1)
            self.assertIn("'", contents)  # directory with spaces is shell quoted
            self.assertTrue((root / '.profile').exists())

    def test_failed_download_never_installs_or_stops(self):
        with patch.object(ops, 'installed'), patch.object(ops.shutil, 'which', return_value='/usr/bin/git'), patch.object(ops, 'run', side_effect=RuntimeError('offline')), patch.object(ops, 'install') as install:
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                ops.update()
            install.assert_not_called()

    def test_explicit_source_does_not_fetch(self):
        with patch.object(ops, 'installed'), patch.object(ops, 'run') as run, patch.object(ops, 'install') as install:
            ops.update('/source')
            run.assert_not_called()
            install.assert_called_once_with('/source')

if __name__ == '__main__':
    unittest.main()
