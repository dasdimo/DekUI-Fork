"""Russian price edits must be guarded by the vendored RU text only."""
import json, re, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/mm3d'))
import localized_prices

RU_ARCHIVE = ROOT / 'resources/mm3d/rus/message/eu/eue.gmsg'
SPEC = json.loads((ROOT / 'resources/mm3d/text/double-prices.json').read_text())
ADJUSTMENTS = json.loads((ROOT / 'resources/mm3d/text/prices-russian.json').read_text())
HEADER = (ROOT / 'src/mm3d/localized_price_data.h').read_text(encoding='utf-8')


def array_rows(name):
    section = re.search(r'inline constexpr std::array<MessageEdit,\d+> '
                        + name + r'\{\{(.*?)\n\}\};', HEADER, re.S)
    rows = {}
    for line in section.group(1).splitlines():
        if not line.strip():
            continue
        match = re.match(r'^\{0x([0-9a-f]{4}),.*?,(0x[0-9a-f]{1,16})ULL,(0x[0-9a-f]{1,16})ULL\},$', line)
        assert match, line[:80]
        rows[int(match.group(1), 16)] = (int(match.group(2), 16), int(match.group(3), 16))
    return rows


class LocalizedRussianPricesTests(unittest.TestCase):
    def expected_guards(self, factor):
        rows = localized_prices.compile_localized(RU_ARCHIVE.read_bytes(), SPEC, 16, factor, ADJUSTMENTS)
        guards = {}
        for mid, raw, new, _, _ in rows:
            guards[mid] = (localized_prices.fnv(raw),
                           localized_prices.fnv(new + bytes(len(raw) - len(new))))
        return guards

    def test_id_sets_match_the_shared_specification(self):
        ids = ({int(x, 16) for x in SPEC['metadata_ids']} | {int(x, 16) for x in SPEC['literal_ids']}
               | {int(x, 16) for x in SPEC['special_literals']})
        for name in ('RussianMessages', 'RussianTripleMessages'):
            with self.subTest(array=name):
                self.assertEqual(set(array_rows(name)), ids)

    def test_russian_guards_match_the_vendored_archive(self):
        for name, factor in (('RussianMessages', 2), ('RussianTripleMessages', 3)):
            with self.subTest(array=name):
                self.assertEqual(array_rows(name), self.expected_guards(factor))

    def test_russian_guards_never_match_the_french_or_spanish_wording(self):
        # Literal price ids carry readable text, so their guard hashes are the
        # language's own bytes; a French or Spanish install misses every row.
        originals = localized_prices.messages(RU_ARCHIVE.read_bytes(), 16)
        for id_set in ('literal_ids', 'special_literals'):
            for value in SPEC[id_set]:
                mid = int(value, 16)
                if mid not in originals or not any(isinstance(t, str) for t in
                                                   localized_prices.decode(originals[mid])):
                    continue
                with self.subTest(mid=value):
                    russian = array_rows('RussianMessages')[mid][0]
                    for other in ('FrenchMessages', 'SpanishMessages'):
                        self.assertNotIn(russian, {guard[0] for guard in array_rows(other).values()})


if __name__ == '__main__':
    unittest.main()
