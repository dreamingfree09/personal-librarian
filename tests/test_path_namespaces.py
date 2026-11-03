from __future__ import annotations

import contextlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from personal_librarian.safety import PathIntent, PathSafetyPolicy, windows_path_kind
from personal_librarian.config import load_config, _validate_root
from personal_librarian.catalogue.database import initialise_catalogue, connect_existing_catalogue
from personal_librarian.catalogue.importers.common import validate_input_file
from personal_librarian.production import application_data_layout
from personal_librarian.desktop.preferences import PreferenceStore
from personal_librarian.desktop.thumbnails import ThumbnailService


class NamespaceTests(unittest.TestCase):
    def test_supported_syntax_and_relative_bases(self):
        policy = PathSafetyPolicy()
        for text, kind in [(r'C:\synthetic\file.txt', 'drive-absolute'),
                           ('D:/synthetic/file.txt', 'drive-absolute'),
                           (r'\\test-server\share\file.txt', 'unc'),
                           ('item.txt', 'relative')]:
            with self.subTest(kind=kind):
                self.assertEqual(windows_path_kind(text), kind)
                self.assertTrue(policy.check_path(text, intent=PathIntent.READ, base_path=r'C:\synthetic').allowed)
        self.assertEqual(policy.check_path('item', intent=PathIntent.READ,
                         base_path=r'\\test-server\share').assessed_path, r'\\test-server\share\item')

    def test_namespace_and_malformed_table_never_allowed(self):
        policy = PathSafetyPolicy()
        names = [r'\\?\C:\synthetic', r'\\.\C:\synthetic',
                 r'\\?\UNC\test-server\share', r'\\?\GLOBALROOT\Device\Synthetic',
                 r'\\?\Volume{00000000-0000-0000-0000-000000000000}\item',
                 r'\??\C:\synthetic', r'\Device\Synthetic',
                 '//?/UNC/test-server/share', r'\\server', r'\\server\\item',
                 r'C:item', 'C:\\bad\x00name', r'C:\synthetic\NUL']
        for name in names:
            for intent in PathIntent:
                with self.subTest(name=name, intent=intent):
                    self.assertFalse(policy.check_path(name, intent=intent).allowed)
                    self.assertFalse(policy.check_path('item', intent=intent, base_path=name).allowed)
        for name in [r'Z:\item', r'\\?\Z:\item', r'\\.\z:\item']:
            self.assertEqual(policy.check_path(name, intent=PathIntent.READ).code, 'RETIRED_DRIVE')

    def test_rejected_namespace_routes_make_no_physical_calls(self):
        routes = [load_config, initialise_catalogue, connect_existing_catalogue,
                  validate_input_file, application_data_layout, PreferenceStore, ThumbnailService,
                  lambda x: _validate_root('data_root', x, PathSafetyPolicy())]
        for route in routes:
            with self.subTest(route=route), contextlib.ExitStack() as stack:
                spies = [stack.enter_context(patch(target, side_effect=AssertionError('physical access')))
                         for target in ('pathlib.Path.open', 'pathlib.Path.stat', 'pathlib.Path.lstat',
                                        'pathlib.Path.resolve', 'sqlite3.connect', 'builtins.open')]
                with self.assertRaises((ValueError, OSError, RuntimeError)):
                    route(r'\\?\UNC\synthetic-server\synthetic-share\input')
                for spy in spies:
                    spy.assert_not_called()

    def test_normal_native_catalogue_and_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config.toml'
            config.write_text('[paths]\n', encoding='utf-8')
            self.assertEqual(load_config(config).source_file, str(config))
            status = initialise_catalogue(root / 'synthetic.sqlite3')
            self.assertTrue(status.up_to_date)


if __name__ == '__main__':
    unittest.main()
