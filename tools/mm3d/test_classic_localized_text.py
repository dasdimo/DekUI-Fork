import hashlib
import json
import re
import struct
import unittest
import tempfile
from pathlib import Path
import classic_localized_text as localized


class ClassicLocalizedTextTests(unittest.TestCase):
    def test_flow_and_line_breaks(self):
        for name, spec in localized.SPEC.items():
            with self.subTest(language=name):
                tokens = localized.tokens(spec)
                self.assertEqual(tokens.count((2,)), 4)
                self.assertEqual(tokens.count((0x27,)), 4)
                self.assertEqual(tokens.count((0x2f, 2)), 1)
                self.assertEqual(tokens.count((0x31, 1)), 4)
                for page in spec['pages'][:4]:
                    self.assertGreater(len(page.splitlines()), 0)
                    self.assertLessEqual(len(page.splitlines()), 4)
                # Conservative copy limit, not a substitute for font/render testing.
                for page in spec['pages'] + spec['return']:
                    self.assertLessEqual(len(page.splitlines()), 4)
                    for line in page.splitlines():
                        self.assertLessEqual(len(re.sub(r'\{[^}]+\}', '', line)), 34)
                self.assertEqual(localized.decode(localized.encode(tokens)), tokens)

    def test_bundled_native_text_and_capacity(self):
        # Synthetic native archives keep CI independent of private game files.
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            for name, spec in localized.SPEC.items():
                native = localized.encode(['Native prompt', (0x2f, 2),
                    spec['choices'][0], (1,), spec['choices'][1], (0,)])
                failure = localized.encode(['No more time', (0x29, 30), (0,)])
                data = bytearray(16 + 3 * 20)
                data[:8] = b"GMSG\x01\0\0\0"
                struct.pack_into('<II', data, 8, 3, spec['language'])
                for i, (mid, raw) in enumerate(((0xc01, native), (0x1b8a, native), (0x1b94, failure))):
                    struct.pack_into('<H', data, 16+i*20, mid)
                    struct.pack_into('<IIII', data, 20+i*20, 0x3fffffff, 0xff0001, len(data), len(raw))
                    data.extend(raw)
                (source/(name+'.gmsg')).write_bytes(data)
            assets, _ = localized.build(source)
        for name, spec in localized.SPEC.items():
            data = assets[name+'.gmsg']
            self.assertEqual(struct.unpack_from('<I', data, 12)[0], spec['language'])
            entries = localized.entries(data)
            for mid, size in ((0xc01, 1536), (0x1b8a, 128)):
                raw = entries[mid][1]
                self.assertEqual(len(raw), size)
                native = localized.decode(raw)
                self.assertIn((0x2f, 2), native)
                for choice in spec['choices']:
                    self.assertIn(choice, native)
            # Last-night failure stays native and keeps its timed dismissal.
            self.assertIn((0x29, 30), localized.decode(entries[0x1b94][1]))

    RU_ARCHIVE = Path(__file__).resolve().parents[2] / 'resources/mm3d/rus/message/eu/eue.gmsg'
    RU_HEADER = Path(__file__).resolve().parents[2] / 'src/mm3d/classic_localized_text.h'

    def russian_row(self):
        rows, _ = localized.collect(self.RU_ARCHIVE.parent, ['eue'])
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_header_carries_three_language_rows(self):
        header = self.RU_HEADER.read_text(encoding='utf-8')
        self.assertIn(f'std::array<Dialogue,{len(localized.SPEC)}>', header)
        for language in sorted(spec['language'] for spec in localized.SPEC.values()):
            self.assertIn('    {' + str(language) + ',', header)
        self.assertEqual(len(re.findall(r'^    \{\d+,', header, re.M)), 3)

    def test_russian_row_guards_match_the_vendored_archive(self):
        _, owl, classic, returned, song, questions = self.russian_row()
        header = self.RU_HEADER.read_text(encoding='utf-8')
        row = [line for line in header.splitlines() if line.startswith('    {16,')][0]
        # The three bare guards sit between the returned-wording recipe and the
        # Song-of-Time recipe; recipe-internal hashes always follow a length.
        guards_match = re.search(
            r'\},(0x[0-9a-f]{1,16})ULL,(0x[0-9a-f]{1,16})ULL,(0x[0-9a-f]{1,16})ULL,\{', row)
        self.assertIsNotNone(guards_match)
        guards = [int(h, 16) for h in guards_match.groups()]
        expected = [localized.text.fnv(raw.ljust(len(owl), b'\0'))
                    for raw in (owl, classic, returned)]
        self.assertEqual(guards, expected)
        # The authored wording round-trips through the real codec.
        for raw in (classic, returned, *questions):
            self.assertEqual(localized.encode(localized.decode(raw)).rstrip(b'\0'),
                             raw.rstrip(b'\0'))
        native = localized.decode(owl)
        self.assertIn((0x2f, 2), native)
        for choice in localized.SPEC['eue']['choices']:
            self.assertIn(choice, native)
        # Stock EUR-English owl prompt must NOT satisfy the language-16 guard.
        from test_text_profiles import STOCK_PROMPT
        self.assertNotEqual(localized.text.fnv(STOCK_PROMPT.ljust(len(owl), b'\0')), guards[0])


if __name__ == '__main__':
    unittest.main()
