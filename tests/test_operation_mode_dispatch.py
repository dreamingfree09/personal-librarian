"""Operation modes must be enforced before physical dispatch (mock-only)."""
import contextlib
import io
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from personal_librarian import cli


class PhysicalModeDispatchTests(unittest.TestCase):
    def test_explicit_modes_never_dispatch_physical_operations(self):
        for mode in ('dry-run', 'read-only'):
            for command, args, target in (
                ('execute', ['--plan-id', 'p', '--item-id', 'i', '--quarantine-root', 'unused', '--confirm-quarantine'], 'execute_quarantine'),
                ('restore', ['e', '--confirm-restore'], 'restore_quarantine'),
            ):
                with self.subTest(mode=mode, command=command), patch.object(cli, target, return_value={}) as spy, contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                    result = cli.main(['--mode', mode, 'quarantine', command, '--database', 'unused', '--actor', 'test', *args])
                    self.assertEqual(result, 2)
                    spy.assert_not_called()

    def test_implicit_mode_preserves_confirmed_narrow_route(self):
        for command, args, target in (
            ('execute', ['--plan-id', 'p', '--item-id', 'i', '--quarantine-root', 'unused', '--confirm-quarantine'], 'execute_quarantine'),
            ('restore', ['e', '--confirm-restore'], 'restore_quarantine'),
        ):
            with self.subTest(command=command), patch.object(cli, target) as spy, patch.object(cli, '_show_structured'):
                self.assertEqual(cli.main(['quarantine', command, '--database', 'unused', '--actor', 'test', *args]), 0)
                spy.assert_called_once()
                self.assertTrue(spy.call_args.kwargs['confirm_quarantine' if command == 'execute' else 'confirm_restore'])

    def test_missing_confirmation_is_not_invented(self):
        for command, args, target, key in (
            ('execute', ['--plan-id', 'p', '--item-id', 'i', '--quarantine-root', 'unused'], 'execute_quarantine', 'confirm_quarantine'),
            ('restore', ['e'], 'restore_quarantine', 'confirm_restore'),
        ):
            with self.subTest(command=command), patch.object(cli, target) as spy, patch.object(cli, '_show_structured'):
                cli.main(['quarantine', command, '--database', 'unused', '--actor', 'test', *args])
                self.assertFalse(spy.call_args.kwargs[key])

    def test_equals_mode_syntax_and_action_mode(self):
        with patch.object(cli, 'restore_quarantine') as spy, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--mode=dry-run', 'quarantine', 'restore', 'e', '--database', 'unused', '--actor', 'test', '--confirm-restore']), 2)
            with self.assertRaises(SystemExit) as raised:
                cli.main(['--mode=action', 'quarantine', 'restore', 'e', '--database', 'unused', '--actor', 'test', '--confirm-restore'])
            self.assertEqual(raised.exception.code, 2)
            spy.assert_not_called()

    def test_read_only_status_remains_available(self):
        with patch.object(cli, 'quarantine_status') as spy, patch.object(cli, '_show_structured'):
            self.assertEqual(cli.main(['--mode', 'read-only', 'quarantine', 'status', 'e', '--database', 'unused']), 0)
            spy.assert_called_once()
