#!/usr/bin/env python3
"""Prepare a fresh portable user directory from game/mm3d.cci and supplied Restoration.
Never replaces an existing user directory. No keys, ROM or Restoration assets bundled.
"""
import argparse
import json
from pathlib import Path
import shutil
import struct
import tempfile
from probe_rom import probe
from build_release_assets import build, RESOURCES
from release_setup import digest, write
from upgrade_game_resources import RESOURCE_VERSION
import layout_migration


def select(roms, actual):
    # Match by program id when the probe reports one, else by partition bytes + sha256.
    for entry in roms:
        if actual.get('program_id', '').lower() == entry['title_id']:
            if all(actual.get(key) == entry[key] for key in ('remaster_version', 'main_partition_bytes', 'main_partition_sha256')):
                return entry
    for entry in roms:
        if (actual.get('main_partition_bytes'), actual.get('main_partition_sha256')) == \
                (entry['main_partition_bytes'], entry['main_partition_sha256']):
            return entry
    return None


def validate(rom):
    roms = json.loads((RESOURCES / 'supported-rom.json').read_text(encoding='utf-8'))['roms']
    selected = select(roms, probe(rom))
    if selected is None:
        raise ValueError('Unsupported ROM revision/content; expected the verified decrypted USA or Europe Rev 1 dump')
    return selected


def romfs_entries(rom, wanted=None):
    # NCSD -> main NCCH -> standard IVFC level 3. Yields (path, bytes) for the
    # wanted romfs paths (all of them when wanted is None), in table order.
    with rom.open('rb') as stream:
        size = rom.stat().st_size
        def read(at, count):
            if at < 0 or count < 0 or at + count > size:
                raise ValueError('ROM bounds error')
            stream.seek(at); data = stream.read(count)
            if len(data) != count: raise ValueError('Short ROM read')
            return data
        base = struct.unpack('<I', read(0x120,4))[0] * 512
        rb, rn = struct.unpack('<II', read(base+0x1b0,8))
        start, length = base + rb*512 + 0x1000, rn*512-0x1000
        if length <= 0: raise ValueError('Invalid RomFS')
        def rr(at, count):
            if at < 0 or at+count > length: raise ValueError('RomFS bounds error')
            return read(start+at,count)
        h = struct.unpack('<10I',rr(0,40))
        if h[0] != 40: raise ValueError('Unsupported RomFS layout')
        dt, ft, payload = h[3], h[7], h[9]
        visited = set(); found = set()
        def directory(offset, parent, depth=0):
            if depth > 32 or offset in visited: raise ValueError('Cyclic/deep RomFS')
            visited.add(offset)
            _, sibling, child, file, _, n = struct.unpack('<6I',rr(dt+offset,24))
            if n > 1024: raise ValueError('Invalid directory name')
            name = rr(dt+offset+24,n).decode('utf-16le')
            path = parent + (name+'/' if name else '')
            seen_files = set()
            while file != 0xffffffff:
                if file in seen_files: raise ValueError('Cyclic file list')
                seen_files.add(file)
                _, nxt, data_at, data_len, _, n = struct.unpack('<IIQQII',rr(ft+file,32))
                if n > 1024: raise ValueError('Invalid file name')
                filename = path+rr(ft+file+32,n).decode('utf-16le')
                if wanted is None or filename in wanted:
                    if filename in found or data_len > 16*1024*1024: raise ValueError('Invalid asset')
                    yield filename, rr(payload+data_at,data_len)
                    found.add(filename)
                file = nxt
            while child != 0xffffffff:
                child = (yield from directory(child,path,depth+1))
            return sibling
        yield from directory(0,'')
        if wanted is not None and found != wanted: raise ValueError('Required game layouts missing')


def title_id(rom):
    # Program id of the main NCCH, as the lowercase 16-hex-digit string used everywhere.
    with rom.open('rb') as stream:
        base = struct.unpack('<I', _read(stream, 0x120, 4))[0] * 512
        return '%016x' % struct.unpack('<Q', _read(stream, base+0x118, 8))[0]


def _read(stream, at, count):
    stream.seek(at); data = stream.read(count)
    if len(data) != count: raise ValueError('Short ROM read')
    return data


def extract(rom, output):
    manifest = json.loads((RESOURCES / 'setup-fingerprints.json').read_text(encoding='utf-8'))
    wanted = {e['input'][6:] for e in manifest['files'] if e['input_root'] == 'original'}
    wanted.add('layout/Joker.Main.Play.gar')
    tid = title_id(rom)
    if tid not in manifest['titles']:
        raise ValueError('Unsupported ROM revision/content; expected the verified decrypted USA or Europe Rev 1 dump')
    messages = manifest['titles'][tid]['messages']
    wanted.update(messages['source_dir'][6:]+'/'+name+'.gmsg' for name in messages['names'])
    for filename, data in romfs_entries(rom, wanted):
        write(output, 'romfs/'+filename, data)


def rus_overlay(block):
    # Vendored RU overlay under resources/mm3d/rus; every file is verified
    # against the overlay manifest before it can reach the installed tree.
    manifest_path = RESOURCES / block['manifest']
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    files = {}
    for entry in manifest['files']:
        data = (manifest_path.parent / entry['path']).read_bytes()
        if len(data) != entry['size'] or digest(data) != entry['sha256']:
            raise ValueError('Russian overlay content drifted from its manifest: ' + entry['path'])
        files[entry['path']] = data
    return files


def setup(root, restoration, selected_rom=None, copy_game=True, reference_game=False):
    rom = selected_rom or root/'game/mm3d.cci'
    if not copy_game and not reference_game and rom.resolve().parent != root.resolve() and rom.resolve() != (root/'game/mm3d.cci').resolve():
        raise ValueError('Place the game beside the application before starting setup.')
    layout_policy = layout_migration.policy(RESOURCES)
    selected = validate(rom)
    title = selected['title_id']
    output = root/'user'
    if output.exists(): raise ValueError('user directory already exists; refusing to replace settings or saves')
    destination = root/'game/mm3d.cci'
    if copy_game and destination.exists() and destination.resolve() != rom.resolve():
        validate(destination)  # Never replace an existing game file.
    stage = Path(tempfile.mkdtemp(prefix='.mm3d-setup-',dir=root))
    installed_rom = False
    try:
        original = stage/'setup/original'
        extract(rom,original)
        profile=json.loads((RESOURCES / 'setup-fingerprints.json').read_text(encoding='utf-8'))['titles'][title]
        mod_root=stage/('load/mods/'+title)
        rus=rus_overlay(profile['rus']) if 'rus' in profile else None
        if rus is not None:
            # The Russian archives become the expansion base, so the generated
            # eue.gmsg keeps the slot expansion but carries RU text.
            base=profile['messages']['source_dir'][6:]+'/'
            for path,data in rus.items():
                if path.startswith(base):
                    write(original,'romfs/'+path,data)
        build(original,restoration,mod_root,profile.get('rus',{}).get('messages'))
        if rus is not None:
            # Remaining RU files ride along as a plain mod copy; generated
            # output wins (eue.gmsg was built from these very bytes).
            for path,data in rus.items():
                if not (mod_root/'romfs'/path).exists():
                    write(mod_root,'romfs/'+path,data)
        write(stage, layout_migration.BASELINE, layout_migration.baseline(layout_policy))
        (stage/('load/textures/'+title)).mkdir(parents=True)
        shutil.copytree(RESOURCES/'defaults',stage/'config/mm3d-local')
        write(stage, 'config/qt-config.ini', b'[Utility]\ncustom_textures=true\ncustom_textures\\default=false\n[Layout]\nlayout_option=1\nlayout_option\\default=false\n[Renderer]\nuse_hw_shader=false\nuse_hw_shader\\default=false\nasync_shader_compilation=false\nasync_shader_compilation\\default=false\nuse_disk_shader_cache=false\nuse_disk_shader_cache\\default=false\nuse_vsync=true\nuse_vsync\\default=true\nresolution_factor=4\nresolution_factor\\default=false\ngraphics_api=2\ngraphics_api\\default=false\n')
        p=stage/'config/mm3d-local/notebook.json'; obj=json.loads(p.read_text(encoding='utf-8'))
        obj['source_archive']='setup/original/romfs/layout/Joker.Main.Play.SubMenu.gar'
        obj['fade_source']='setup/original/romfs/layout/Joker.gar'
        p.write_text(json.dumps(obj,indent=2)+'\n')
        (stage/'setup/ready.json').write_text(json.dumps({'version':1,'resource_version':RESOURCE_VERSION,'layout_version':layout_migration.VERSION,'rom_sha256':selected['main_partition_sha256'],'title_id':title})+'\n')
        if copy_game and not destination.exists():
            shutil.copyfile(rom, stage/'game-copy.cci')
            validate(stage/'game-copy.cci')
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation prevents an overlapping setup from replacing a ROM.
            with destination.open('xb') as target:
                installed_rom = True
                with (stage/'game-copy.cci').open('rb') as source:
                    shutil.copyfileobj(source, target)
            (stage/'game-copy.cci').unlink()
        stage.rename(output)
    except BaseException:
        if installed_rom:
            destination.unlink(missing_ok=True)
        raise
    finally:
        if stage.exists(): shutil.rmtree(stage)
    return output


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--restoration',type=Path,required=True)
    a=p.parse_args()
    try: print('Prepared:',setup(a.root,a.restoration))
    except (ValueError,OSError) as error: p.exit(1,str(error)+'\n')
