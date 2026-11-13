"""Focused command tests; no changes to real shell profiles or installation."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

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

    def test_omarchy_open_uses_managed_lifecycle(self):
        with patch.object(ops.shutil, 'which', return_value='/usr/bin/omarchy-launch-webapp'), patch.object(ops, 'managed_webapp') as managed:
            ops.open_app()
            managed.assert_called_once_with()

    def test_browser_only_open_keeps_manual_server_lifecycle(self):
        with patch.object(ops.shutil, 'which', return_value=None), patch.object(ops, 'start') as start, patch.object(ops, 'webapp_port', return_value='9876'), patch.object(ops.webbrowser, 'open', return_value=True) as browser:
            ops.open_app()
            start.assert_called_once_with()
            browser.assert_called_once_with('http://127.0.0.1:9876/')

    def test_window_close_stops_only_owned_browser_and_server(self):
        with tempfile.TemporaryDirectory() as temp:
            proc = Mock(pid=101)
            proc.poll.return_value = None
            events = []
            proc.terminate.side_effect = lambda: events.append('terminate-browser')
            with patch.object(ops, 'HOME', Path(temp)), patch.object(ops, 'installed'), patch.object(ops.shutil, 'which', side_effect=lambda name: '/usr/bin/'+name), patch.object(ops, 'start', side_effect=lambda: events.append('start')), patch.object(ops, 'stop', side_effect=lambda: events.append('stop')), patch.object(ops, 'webapp_port', return_value='9876'), patch.object(ops.subprocess, 'Popen', return_value=proc) as launch, patch.object(ops, 'webapp_clients', side_effect=[[{'pid':101,'address':'0x123','initialClass':'chrome-127.0.0.1__-Default'}],[{'pid':202,'address':'0xother','initialClass':'chromium'}]]), patch.object(ops.time, 'sleep'):
                ops.managed_webapp()
            self.assertEqual(events, ['start','terminate-browser','stop'])
            self.assertIn('--disable-background-mode',launch.call_args.args[0])
            self.assertIn('--user-data-dir='+str(Path(temp)/'webapp-profile'),launch.call_args.args[0])
            self.assertFalse((Path(temp)/'webapp-window.json').exists())

    def test_browser_launch_failure_stops_server(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(ops, 'HOME', Path(temp)), patch.object(ops, 'installed'), patch.object(ops.shutil, 'which', side_effect=lambda name: '/usr/bin/'+name), patch.object(ops, 'start'), patch.object(ops, 'stop') as stop, patch.object(ops, 'webapp_port', return_value='9876'), patch.object(ops.subprocess, 'Popen', side_effect=OSError('launch failed')):
                with self.assertRaises(OSError):
                    ops.managed_webapp()
                stop.assert_called_once_with()

    def test_second_launch_focuses_without_stopping_server(self):
        import fcntl
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'webapp-window.json').write_text('{"address":"0x123","pid":101}')
            with (root/'webapp.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch.object(ops, 'HOME', root), patch.object(ops, 'installed'), patch.object(ops.shutil, 'which', side_effect=lambda name: '/usr/bin/'+name), patch.object(ops, 'start') as start, patch.object(ops, 'stop') as stop, patch.object(ops, 'webapp_clients', return_value=[{'address':'0x123','pid':101}]), patch.object(ops, 'focus_webapp_window') as focus:
                    ops.managed_webapp()
                    start.assert_not_called();stop.assert_not_called()
                    focus.assert_called_once_with('0x123')

    def test_focus_supports_lua_and_legacy_dispatch(self):
        with patch.object(ops.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            ops.focus_webapp_window('0x123')
            self.assertIn('hl.dsp.focus',run.call_args.args[0][-1])
            self.assertEqual(run.call_count,1)
        with patch.object(ops.subprocess, 'run', side_effect=[Mock(returncode=1),Mock(returncode=0)]) as run:
            ops.focus_webapp_window('0x123')
            self.assertEqual(run.call_args.args[0],['hyprctl','dispatch','focuswindow','address:0x123'])
        with self.assertRaisesRegex(RuntimeError,'Invalid'):
            ops.focus_webapp_window('0x123; unexpected()')

    def test_missing_omarchy_is_actionable(self):
        with patch.object(ops, 'installed'), patch.object(ops.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'Chromium'):
                ops.install_webapp()

if __name__ == '__main__':
    unittest.main()
