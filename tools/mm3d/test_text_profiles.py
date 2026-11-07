"""Contracts for the per-title message text profiles in setup-fingerprints.json."""
import json, struct, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/mm3d'))
import build_release_assets, classic_localized_text, classic_owl_text, single_screen_text as text

FINGERPRINTS = json.loads((ROOT / 'resources/mm3d/setup-fingerprints.json').read_text())

# Stock English owl prompt payload, byte-identical in the USA and Europe
# archives (verified against both verified Rev 1 partitions).
STOCK_PROMPT = bytes.fromhex(
    '7f003a0000007f003a000100536176657f003a00000020796f75722070726f67726573732'
    '07f3a000b00757020746f207468697320706f696e743f7f01007f003a0002007f002f0002'
    '005965737f01004e6f7f003a000b007f000000')


def gmsg(language, entries):
    rows, payload, at = b'', b'', 16 + 20 * len(entries)
    for mid, raw in entries:  # caller controls order so payload offsets stay even
        rows += struct.pack('<H10xII', mid, at, len(raw))
        payload += raw
        at += len(raw)
    return b'GMSG\x01\x00\x00\x00' + struct.pack('<II', len(entries), language) + rows + payload


class TextProfileTests(unittest.TestCase):
    def test_profiles_cover_their_extracted_archives(self):
        for title, profile in FINGERPRINTS['titles'].items():
            messages = profile['messages']
            english = messages['text']['english']
            self.assertEqual(english['name'], messages['names'][0], title)
            self.assertEqual(english['language'], 16 if profile['region'] == 'eur' else 2, title)
            self.assertEqual(set(messages['text']['localized']),
                             {n for n in messages['names'] if n != english['name']}, title)

    def test_localized_names_match_the_builder_specifications(self):
        for title, profile in FINGERPRINTS['titles'].items():
            messages = profile['messages']
            for name in messages['text']['localized']:
                self.assertIn(name, classic_localized_text.SPEC, title)
            self.assertEqual(messages['text']['localized'],
                             [n for n in messages['names']
                              if n in classic_localized_text.SPEC], title)

    def test_owl_preparation_follows_the_profile_language(self):
        fixture = gmsg(16, [(0x0C01, STOCK_PROMPT), (0x10, b'\x00')])
        out, header, used = classic_owl_text.prepare(fixture, 16)
        archive = text.messages(out, 16)
        self.assertEqual(len(archive[0x0C01]), 1024)
        self.assertGreater(used, len(STOCK_PROMPT))
        self.assertEqual(archive[0x10], b'\x00')
        self.assertIn('ClassicOwlReplacements', header)
        # A USA-coded reader must reject the Europe archive and vice versa.
        with self.assertRaises(ValueError):
            classic_owl_text.prepare(fixture, 2)

    def test_asset_build_requires_exactly_one_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'romfs/message/us').mkdir(parents=True)
            self.assertEqual(build_release_assets.message_profile(root, FINGERPRINTS),
                             FINGERPRINTS['titles']['0004000000125500']['messages'])
            (root / 'romfs/message/eu').mkdir(parents=True)
            with self.assertRaises(ValueError):
                build_release_assets.message_profile(root, FINGERPRINTS)
            empty = root / 'empty'
            empty.mkdir()
            with self.assertRaises(ValueError):
                build_release_assets.message_profile(empty, FINGERPRINTS)


if __name__ == '__main__':
    unittest.main()
