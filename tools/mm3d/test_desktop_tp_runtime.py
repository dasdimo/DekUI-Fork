"""Keep vendor build reports portable without modifying runtime files."""
from pathlib import Path
import tempfile
import unittest
import urllib.request
from build_desktop_tp_runtime import sanitize_numpy_metadata


class NumpyMetadataTests(unittest.TestCase):
    def test_vendor_paths_removed_and_other_configuration_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / 'tp-modules/numpy/__config__.py'
            config.parent.mkdir(parents=True)
            config.write_text('report = {"python": r"C:\\Users\\Builder\\Temp\\python.exe", '
                              '"include": r"C:/Users/Builder/Temp/include", '
                              '"version": "3.13", "compiler": "msvc"}\n')
            runtime = config.parent / 'keep.bin'
            runtime.write_bytes(b'unchanged runtime')
            sanitize_numpy_metadata(root)
            source = config.read_text(encoding='utf-8')
            self.assertNotIn('Builder', source)
            values = {}
            exec(compile(source, '__config__.py', 'exec'), values)
            self.assertEqual(values['report']['version'], '3.13')
            self.assertEqual(values['report']['compiler'], 'msvc')
            self.assertEqual(runtime.read_bytes(), b'unchanged runtime')


class DownloadTests(unittest.TestCase):
    def test_retries_try_bare_filename_on_every_source(self):
        import build_desktop_tp_runtime as module
        requested = []

        def fake(url, dest):
            requested.append(url)
            if len(requested) < 3:
                raise OSError('simulated gateway error')
            Path(dest).write_bytes(b'payload')

        original = urllib.request.urlretrieve
        urllib.request.urlretrieve = fake
        try:
            with tempfile.TemporaryDirectory() as folder:
                archive = Path(folder) / 'python.tar.gz'
                module.download('cpython-x.tar.gz', archive)
                self.assertEqual(archive.read_bytes(), b'payload')
        finally:
            urllib.request.urlretrieve = original
        # One prefix only (regression: a full URL here made every attempt fail),
        # and every source sees the same bare filename.
        self.assertEqual(requested, [
            module.PYTHON_SOURCES[0] + 'cpython-x.tar.gz',
            module.PYTHON_SOURCES[1] + 'cpython-x.tar.gz',
            module.PYTHON_SOURCES[0] + 'cpython-x.tar.gz',
        ])
