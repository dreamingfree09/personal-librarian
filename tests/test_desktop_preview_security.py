from __future__ import annotations
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PIL import Image
from PySide6.QtGui import QImage
from personal_librarian.desktop.thumbnails import ThumbnailService, ThumbnailTask

class PreviewSecurityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = ThumbnailService(self.root / 'app', max_size=(32, 32))

    def image(self, name, fmt, mode='RGB', size=(64, 32), **kwargs):
        path = self.root / name
        Image.new(mode, size, (10, 40, 70, 100) if mode == 'RGBA' else (10, 40, 70)).save(path, format=fmt, **kwargs)
        return path

    def reject(self, path):
        before = path.read_bytes()
        result = self.service.load(path, content_identity=path.name)
        self.assertIsNotNone(result.error)
        self.assertIsNone(result.cache_path)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(list(self.service.cache_root.rglob('*.png')))
        self.assertFalse(list(self.service.cache_root.rglob('*.tmp')))

    def test_supported_formats_render_through_windows_qt(self):
        for ext, fmt in [('jpg','JPEG'), ('jpeg','JPEG'), ('png','PNG'), ('gif','GIF'), ('webp','WEBP')]:
            with self.subTest(fmt=fmt, ext=ext):
                path = self.image('normal.' + ext, fmt)
                before = path.read_bytes()
                result = self.service.load(path, content_identity=ext)
                self.assertIsNone(result.error)
                rendered = QImage(str(result.cache_path))
                self.assertFalse(rendered.isNull())
                self.assertEqual((rendered.width(), rendered.height()), (32,16))
                self.assertEqual(path.read_bytes(), before)

    def test_excluded_formats_cannot_use_approved_suffix(self):
        for fmt in ('TIFF', 'BMP', 'PPM'):
            with self.subTest(fmt=fmt):
                self.reject(self.image(fmt + '.jpg', fmt))

    def test_all_accepted_format_mismatches_reject(self):
        pairs = [('jpg','JPEG'),('png','PNG'),('gif','GIF'),('webp','WEBP')]
        for ext, expected in pairs:
            for _, actual in pairs:
                if expected != actual:
                    with self.subTest(ext=ext, actual=actual):
                        self.reject(self.image(actual + '.' + ext, actual))

    def test_decoder_selection_restricted_before_load(self):
        path = self.image('valid.png','PNG')
        original = Image.open
        with patch('personal_librarian.desktop.thumbnails.Image.open', wraps=original) as opened:
            self.assertIsNone(self.service.load(path, content_identity='valid').error)
        self.assertEqual(opened.call_args.kwargs['formats'], ['PNG'])

    def test_wmf_emf_and_corrupt_bytes_reject(self):
        for i, data in enumerate((b'\xd7\xcd\xc6\x9a' + b'\0' * 64, b'\x01\0\0\0' + b'\0' * 36 + b' EMF' + b'\0' * 64, b'not an image', b'')):
            path=self.root / f'unsupported-{i}.png'; path.write_bytes(data); self.reject(path)

    def test_pixel_limit_precedes_transform(self):
        path=self.image('large.png','PNG')
        with patch('personal_librarian.desktop.thumbnails.MAX_SOURCE_PIXELS', 100), patch('personal_librarian.desktop.thumbnails.ImageOps.exif_transpose') as transform:
            self.reject(path)
        transform.assert_not_called()

    def test_bomb_warning_and_error_fail_closed(self):
        path=self.image('bomb.png','PNG')
        for limit in (1500,100):
            with self.subTest(limit=limit), patch.object(Image,'MAX_IMAGE_PIXELS',limit):
                self.reject(path)

    def test_orientation_and_transparency_preserved(self):
        exif=Image.Exif(); exif[274]=6
        path=self.image('rotated.jpg','JPEG',exif=exif)
        result=self.service.load(path,content_identity='orientation')
        with Image.open(result.cache_path) as thumbnail:
            self.assertEqual(thumbnail.size,(16,32))
        path=self.image('alpha.png','PNG',mode='RGBA')
        result=self.service.load(path,content_identity='alpha')
        with Image.open(result.cache_path) as thumbnail:
            self.assertEqual(thumbnail.getpixel((0,0))[3],100)

    def test_problematic_metadata_and_partial_cache_are_rejected(self):
        path=self.image('metadata.jpg','JPEG')
        for error in (ValueError('invalid metadata'), SyntaxError('invalid metadata'), OSError('truncated image')):
            with patch('personal_librarian.desktop.thumbnails.ImageOps.exif_transpose',side_effect=error):
                self.reject(path)
        original=Image.Image.save
        def interrupted(image, target, *args, **kwargs):
            target.write(b'partial')
            raise OSError('synthetic cache failure')
        with patch.object(Image.Image,'save',interrupted):
            self.reject(path)

    def test_cache_reuse_and_worker_emission(self):
        path=self.image('cached.png','PNG')
        first=self.service.load(path,content_identity='cached')
        with patch.object(Path,'open',side_effect=AssertionError('should not reread source')):
            second=self.service.load(path,content_identity='cached')
        self.assertEqual(first,second)
        results=[]
        task=ThumbnailTask(self.service,str(path),'cached','token')
        task.signals.loaded.connect(lambda token,image,error: results.append((token,image.isNull(),error)))
        task.run()
        self.assertEqual(results,[('token',False,'')])

if __name__ == '__main__':
    unittest.main()
