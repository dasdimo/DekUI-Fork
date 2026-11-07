import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from prepare_rus_overlay import _backward_lz77_uncompress, exefs_files

EUR_ROM = Path("D:/Games/N3DS/Zelda_Majora_Mask/Legend of Zelda, The - Majora's "
               "Mask 3D (Europe) (En,Fr,De,Es,It) (Rev 1)/Legend of Zelda, The - "
               "Majora's Mask 3D (Europe) (En,Fr,De,Es,It) (Rev 1).cci")


class BackwardLz77Test(unittest.TestCase):
    # The full decode path (footer, flags, literal and match tokens, backward
    # copies) is verified against the real base: the EUR Rev 1 code slot and
    # the RU patch author's extracted code.bin (CRC 0xffdf1ee8) below. These
    # tests cover the rejection guards so a raw slot falls back unchanged.
    def test_plain_stream_returns_none(self):
        self.assertIsNone(_backward_lz77_uncompress(b'plain' * 20))
        self.assertIsNone(_backward_lz77_uncompress(b'short'))

    def test_footer_bottom_out_of_range_returns_none(self):
        # 3dstool only accepts a bottom pointer in 8..11
        footer = struct.pack('<II', (20 << 24) | 18, 0)
        self.assertIsNone(_backward_lz77_uncompress(b'\x00' * 100 + footer))

    def test_footer_top_below_bottom_returns_none(self):
        footer = struct.pack('<II', (8 << 24) | 7, 0)
        self.assertIsNone(_backward_lz77_uncompress(b'\x00' * 100 + footer))

    def test_footer_top_beyond_length_returns_none(self):
        footer = struct.pack('<II', (8 << 24) | 500, 0)
        self.assertIsNone(_backward_lz77_uncompress(b'\x00' * 100 + footer))

    @unittest.skipUnless(EUR_ROM.exists(), 'local EUR Rev 1 dump not present')
    def test_eur_rev1_code_slot_matches_rupatch_base(self):
        # exefs.bpm's MirrorFile records CRC 0xffdf1ee8 for the author's
        # unmodified code.bin; our decode of the compressed slot must match.
        code = exefs_files(EUR_ROM)['code.bin']
        self.assertEqual(len(code), 0x5B1000)
        self.assertEqual(zlib.crc32(code), 0xffdf1ee8)

    def test_exefs_files_synthetic_tables(self):
        code = b'\x11' * 64  # no valid footer: extracted raw
        banner = b'bnrbanner!' * 2
        data = bytearray(0x4000 + 0x40000)
        struct.pack_into('<I', data, 0x120, 0x20)  # partition 0 -> NCCH at 0x4000
        table = 0x4000 + 0x2c00
        data[table:table + 8] = b'.code\x00\x00\x00'
        struct.pack_into('<II', data, table + 8, 0, len(code))
        data[table + 0x10:table + 0x18] = b'.banner\x00'
        struct.pack_into('<II', data, table + 0x18, len(code), len(banner))
        data_at = 0x4000 + 0x2e00
        data[data_at:data_at + len(code)] = code
        data[data_at + len(code):data_at + len(code) + len(banner)] = banner
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.cci'
            path.write_bytes(data)
            files = exefs_files(path)
        self.assertEqual(files['code.bin'], code)
        self.assertEqual(files['banner.bnr'], banner)
        self.assertNotIn('main.bin', files)


if __name__ == '__main__':
    unittest.main()
