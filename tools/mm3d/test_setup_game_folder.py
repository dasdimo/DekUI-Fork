import configparser
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from setup_game_folder import setup, validate, extract, RESOURCES

USA_FACTS = {'program_id': '0004000000125500', 'remaster_version': 2,
             'main_partition_bytes': 654643200,
             'main_partition_sha256': '9c756279e3ec00bb9009f92ca2e7b9ec8b1fcdfcd9de057658b209caa24323da'}
EUR_FACTS = {'program_id': '0004000000125600', 'remaster_version': 2,
             'main_partition_bytes': 668647424,
             'main_partition_sha256': 'a26108ef34b49df421cca20eda1b4f38f596ebef9ac6b9c70a64245be055a722'}


class GameFolderTests(unittest.TestCase):
    def test_supported_rom_manifest_is_dual_profile_v2(self):
        data = json.loads((RESOURCES/'supported-rom.json').read_text())
        self.assertEqual(data['schema'], 2)
        self.assertEqual({e['title_id'] for e in data['roms']}, {'0004000000125500', '0004000000125600'})
        self.assertEqual({e['region'] for e in data['roms']}, {'usa', 'eur'})
        for entry in data['roms']:
            self.assertEqual(entry['remaster_version'], 2)
            self.assertTrue(entry['description'])
        facts = {e['title_id']: (e['main_partition_bytes'], e['main_partition_sha256']) for e in data['roms']}
        self.assertEqual(facts[USA_FACTS['program_id']],
                         (USA_FACTS['main_partition_bytes'], USA_FACTS['main_partition_sha256']))
        self.assertEqual(facts[EUR_FACTS['program_id']],
                         (EUR_FACTS['main_partition_bytes'], EUR_FACTS['main_partition_sha256']))
        # The fingerprints manifest keys message profiles by the same title ids.
        titles = json.loads((RESOURCES/'setup-fingerprints.json').read_text())['titles']
        self.assertEqual(set(titles), {e['title_id'] for e in data['roms']})
        for title, profile in titles.items():
            self.assertEqual(profile['messages']['names'], list(profile['messages']['hashes']))
            self.assertEqual({h for h in profile['messages']['hashes'].values()},
                             {h for h in profile['messages']['hashes'].values() if len(h) == 64})

    def test_validate_selects_europe_profile(self):
        with patch('setup_game_folder.probe', return_value=EUR_FACTS):
            selected = validate(Path('mm3d.cci'))
        self.assertEqual(selected['title_id'], '0004000000125600')
        self.assertEqual(selected['region'], 'eur')
        with patch('setup_game_folder.probe', return_value=USA_FACTS):
            selected = validate(Path('mm3d.cci'))
        self.assertEqual(selected['title_id'], '0004000000125500')

    def test_validate_rejects_europe_id_with_wrong_content(self):
        with patch('setup_game_folder.probe', return_value=dict(EUR_FACTS, main_partition_sha256='0'*64)):
            with self.assertRaisesRegex(ValueError, 'Unsupported ROM'): validate(Path('mm3d.cci'))
        with patch('setup_game_folder.probe', return_value=dict(EUR_FACTS, main_partition_bytes=1)):
            with self.assertRaisesRegex(ValueError, 'Unsupported ROM'): validate(Path('mm3d.cci'))

    def test_validate_falls_back_to_partition_identity(self):
        anonymous = {k: v for k, v in EUR_FACTS.items() if k != 'program_id'}
        with patch('setup_game_folder.probe', return_value=anonymous):
            selected = validate(Path('mm3d.cci'))
        self.assertEqual(selected['title_id'], '0004000000125600')

    def test_setup_creates_empty_texture_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rom=root/'original.cci';rom.write_bytes(b'original')
            with patch('setup_game_folder.validate', return_value={'title_id':'0004000000125500','main_partition_sha256':'0'*64}), patch('setup_game_folder.extract',
                    side_effect=lambda rom,out:out.mkdir(parents=True)), patch('setup_game_folder.build'):
                setup(root,root,rom)
            self.assertEqual(json.loads((root/'user/setup/ready.json').read_text())['title_id'], '0004000000125500')
            self.assertEqual(json.loads((root/'user/setup/ready.json').read_text())['rom_sha256'], '0'*64)
            textures=root/'user/load/textures/0004000000125500'
            self.assertTrue(textures.is_dir())
            self.assertEqual(list(textures.iterdir()),[])
            self.assertEqual(rom.read_bytes(),b'original')
            config = configparser.ConfigParser()
            config.read(root/'user/config/qt-config.ini')
            for key in ('use_hw_shader', 'async_shader_compilation'):
                self.assertFalse(config.getboolean('Renderer', key))
                self.assertFalse(config.getboolean('Renderer', key + '\\default'))
            self.assertEqual(config.getint('Renderer', 'graphics_api'), 2)


    def test_missing_rom(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(OSError): setup(Path(t),Path(t))
            self.assertFalse((Path(t)/'user').exists())

    def test_existing_user_preserved(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'user').mkdir();save=root/'user/save';save.write_bytes(b'keep')
            with patch('setup_game_folder.validate'), self.assertRaises(ValueError): setup(root,root)
            self.assertEqual(save.read_bytes(),b'keep')

    def test_wrong_revision(self):
        with patch('setup_game_folder.probe',return_value={'program_id':'wrong'}):
            with self.assertRaises(ValueError):validate(Path('mm3d.cci'))

    def test_truncated_extraction(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);rom=root/'mm3d.cci';rom.write_bytes(b'NCSD')
            with self.assertRaises(ValueError):extract(rom,root/'output')
            self.assertFalse((root/'output').exists())


if __name__=='__main__':unittest.main()
