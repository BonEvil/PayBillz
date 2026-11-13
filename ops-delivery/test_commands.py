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

    def test_omarchy_launcher_uses_local_icon_and_starts_server_on_launch(self):
        with patch.object(ops, 'installed'), patch.object(ops.shutil, 'which', return_value='/usr/bin/omarchy-webapp-install'), patch.object(ops, 'webapp_port', return_value='9876'), patch.object(ops, 'run') as run:
            ops.install_webapp()
            args = run.call_args.args
            self.assertEqual(args[1:3], ('PayBillz','http://127.0.0.1:9876/'))
            self.assertEqual(args[3], ops.APP / 'bills/static/bills/pwa/icon-512.png')
            self.assertIn('"open" "--port" "9876"', args[4])
            self.assertIn('PAYBILLZ_HOME=', args[4])

    def test_open_starts_server_before_launching_omarchy(self):
        order = []
        with patch.object(ops, 'start', side_effect=lambda: order.append('start')), patch.object(ops, 'webapp_port', return_value='9876'), patch.object(ops.shutil, 'which', return_value='/usr/bin/omarchy-launch-webapp'), patch.object(ops, 'run', side_effect=lambda *args: order.append(args)):
            ops.open_app()
        self.assertEqual(order, ['start', ('/usr/bin/omarchy-launch-webapp','http://127.0.0.1:9876/')])

    def test_missing_omarchy_is_actionable(self):
        with patch.object(ops, 'installed'), patch.object(ops.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'Chromium'):
                ops.install_webapp()

if __name__ == '__main__':
    unittest.main()
