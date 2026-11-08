"""The standalone render sync helpers do not need preview-only modules or assets."""
import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gif_cinema import durability


class DurabilityTests(unittest.TestCase):
    def test_success_replaces_content_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_bytes(b'old')
            durability.durable_write(path, b'new')
            self.assertEqual(path.read_bytes(), b'new')
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_file_sync_failure_keeps_old_content_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_bytes(b'old')
            with patch('gif_cinema.durability.os.fsync', side_effect=OSError(errno.EIO, 'sync failed')):
                with self.assertRaises(OSError):
                    durability.durable_write(path, b'new')
            self.assertEqual(path.read_bytes(), b'old')
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_replace_failure_keeps_old_content_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            path.write_bytes(b'old')
            with patch('gif_cinema.durability.os.replace', side_effect=OSError(errno.EIO, 'replace failed')):
                with self.assertRaises(OSError):
                    durability.durable_write(path, b'new')
            self.assertEqual(path.read_bytes(), b'old')
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_directory_open_ignores_only_unsupported_errors(self):
        with patch('gif_cinema.durability.os.name', 'posix'):
            for error, allowed in ((errno.EINVAL, True), (errno.ENOSYS, True), (errno.EACCES, False), (errno.EIO, False)):
                with self.subTest(error=error), patch('gif_cinema.durability.os.open', side_effect=OSError(error, 'fixture')):
                    if allowed:
                        durability.sync_directory('fixture')
                    else:
                        with self.assertRaises(OSError):
                            durability.sync_directory('fixture')

    def test_directory_sync_always_closes_descriptor(self):
        with patch('gif_cinema.durability.os.name', 'posix'):
            for error, allowed in ((errno.EINVAL, True), (errno.EIO, False)):
                with self.subTest(error=error), patch('gif_cinema.durability.os.open', return_value=123), \
                        patch('gif_cinema.durability.os.fsync', side_effect=OSError(error, 'fixture')), \
                        patch('gif_cinema.durability.os.close') as close:
                    if allowed:
                        durability.sync_directory('fixture')
                    else:
                        with self.assertRaises(OSError):
                            durability.sync_directory('fixture')
                    close.assert_called_once_with(123)

    def test_non_posix_directory_sync_does_not_open_directory(self):
        with patch('gif_cinema.durability.os.name', 'nt'), patch('gif_cinema.durability.os.open') as opened:
            durability.sync_directory('fixture')
        opened.assert_not_called()


if __name__ == '__main__':
    unittest.main()
