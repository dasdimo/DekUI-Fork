"""The Russian single-screen wording compiles only against the vendored RU archive."""
import json, re, struct, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/mm3d'))
import single_screen_text as text

RU_ARCHIVE = ROOT / 'resources/mm3d/rus/message/eu/eue.gmsg'
RU_SPEC = json.loads((ROOT / 'resources/mm3d/text/single-screen-russian.json').read_text())
HEADER = ROOT / 'src/mm3d/single_screen_localized_data.h'


class SingleScreenRussianTests(unittest.TestCase):
    def test_russian_rows_compile_against_the_vendored_archive(self):
        rows = text.compile_messages(RU_ARCHIVE.read_bytes(), RU_SPEC)
        self.assertEqual({mid for mid, _, _, _, _, _ in rows},
                         {int(e['id'], 16) for e in RU_SPEC['edits']})
        for mid, _, _, data, tokens, _ in rows:
            self.assertEqual(text.decode(data), tokens)
            lines = 1
            for t in tokens:
                if t == (1,):
                    lines += 1
                if t == (2,) or t == (0,):
                    self.assertLessEqual(lines, 4)
                    lines = 1

    def test_generated_header_carries_the_russian_array(self):
        header = HEADER.read_text(encoding='utf-8')
        for array in ('FrenchReplacements', 'SpanishReplacements'):
            self.assertRegex(header, rf'inline constexpr std::array<Replacement,\d+> {array}\{{')
        section = re.search(r'inline constexpr std::array<Replacement,(\d+)> RussianReplacements\{\{(.*?)\n\}\};',
                            header, re.S)
        self.assertIsNotNone(section)
        ids = {int(e['id'], 16) for e in RU_SPEC['edits']}
        self.assertEqual(int(section.group(1)), len(ids))
        ids = {int(m, 16) for m in re.findall(r'^\s*\{0x([0-9a-f]{4}),', section.group(2), re.M)}
        self.assertEqual(ids, {int(e['id'], 16) for e in RU_SPEC['edits']})

    def test_russian_guards_reject_any_other_wording(self):
        data = bytearray(RU_ARCHIVE.read_bytes())
        count = struct.unpack_from('<I', data, 8)[0]
        target = int(RU_SPEC['edits'][0]['id'], 16)
        for i in range(count):
            at = 16 + i * 20
            if struct.unpack_from('<H', data, at)[0] == target:
                off, size = struct.unpack_from('<II', data, at + 12)
                self.assertGreater(size, 1)
                data[off + size - 2] ^= 0x01  # change the payload's last codepoint
                break
        else:
            self.fail(f'{target:04x} missing from the vendored archive')
        with self.assertRaises(ValueError):
            text.compile_messages(bytes(data), RU_SPEC)

    def test_english_wording_in_the_same_slot_satisfies_no_russian_guard(self):
        from double_prices import encode
        data = RU_ARCHIVE.read_bytes()
        count = struct.unpack_from('<I', data, 8)[0]
        originals = {}
        for i in range(count):
            at = 16 + i * 20
            mid = struct.unpack_from('<H', data, at)[0]
            off, size = struct.unpack_from('<II', data, at + 12)
            originals[mid] = data[off:off + size]
        edit = RU_SPEC['edits'][0]
        mid = int(edit['id'], 16)
        tokens = list(text.decode(originals[mid]))
        tokens[int(edit['token_index'])] = 'Press SELECT to open the inventory.'
        english = encode(tokens)
        rows = [(m, english if m == mid else r) for m, r in originals.items()]
        payload, at = b'', 16 + 20 * len(rows)
        table = b''
        for m, raw in rows:
            table += struct.pack('<H10xII', m, at, len(raw))
            payload += raw
            at += len(raw)
        fixture = (b'GMSG\x01\x00\x00\x00' + struct.pack('<II', len(rows), 16)
                   + table + payload)
        with self.assertRaises(ValueError):
            text.compile_messages(fixture, RU_SPEC)
        # Only the swapped token broke the guard: the untouched archive compiles.
        text.compile_messages(data, RU_SPEC)


if __name__ == '__main__':
    unittest.main()
