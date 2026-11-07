#!/usr/bin/env python3
"""Prepare the Russian overlay: apply the ZELDA64RUS v1.1 beat patches to a
verified Europe Rev 1 dump and vendor the changed romfs files (exact ROM case)
under resources/mm3d/rus/ with a content manifest. One-time preparation tool;
the setup pipeline only consumes the vendored result, never the user's patch.
"""
import argparse
import fnmatch
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

from setup_game_folder import RESOURCES, romfs_entries, title_id, validate

EUR = '0004000000125600'
SOURCE = {'name': 'LoZMM3D_(PAL_rev1)_RUS_Patch_v1.1',
          'publisher': 'ZELDA64RUS', 'version': '1.1',
          'target': 'The Legend of Zelda: Majora\'s Mask 3D EUR Rev1 3ds CRC32: 943ED937 or 3A87ABAC'}

# The changed-file contract (§ docs/EUR-RUS-RULES.md 2.5), exact ROM case.
EXPECTED_EXPLICIT = [
    'message/eu/eue.gmsg', 'message/ltn16.gzf',
    'layout/EU_English/Joker.Main.gar', 'layout/EU_English/Joker.Main.Ending.gar',
    'layout/EU_English/Joker.Main.FileSelect.gar', 'layout/EU_English/Joker.Main.Play.gar',
    'layout/EU_English/Joker.Main.Play.Countdown.gar', 'layout/EU_English/Joker.Main.Play.HintMovie.gar',
    'layout/EU_English/Joker.Main.Play.Option.gar', 'layout/EU_English/Joker.Main.Play.Perfect.gar',
    'layout/EU_English/Joker.Main.Play.SubMenu.gar', 'layout/EU_English/Joker.Main.Startup.gar',
    'menu/daytelop/eu-en/daytelop_24.ctxb', 'menu/daytelop/eu-en/daytelop_48.ctxb',
    'menu/daytelop/eu-en/daytelop_72.ctxb', 'menu/daytelop/eu-en/daytelop_first.ctxb',
    'menu/daytelop/eu-en/daytelop_last.ctxb', 'menu/daytelop/eu-en/daytelop_new.ctxb',
    'menu/daytelop/eu-en/daytelop_scound.ctxb',
    'menu/savedata_maintainer/eu/english/guideline_parts00.ctxb',
    'os/patch/version.ctxb',
    'actors/zelda2_boss01.gar.lzs', 'actors/zelda2_boss02.gar.lzs',
    'actors/zelda2_boss03.gar.lzs', 'actors/zelda2_boss07.gar.lzs',
    'actors/zelda2_boss_hakugin.gar.lzs', 'actors/zelda2_mag.gar.lzs',
]
EXPECTED_GLOBS = [('layout/map/genbamap/EU_English/*.ctxb', 84)]


def digest(data): return hashlib.sha256(data).hexdigest()


def expected_match(path):
    if path in EXPECTED_EXPLICIT: return True
    return any(fnmatch.fnmatchcase(path, pattern) for pattern, _ in EXPECTED_GLOBS)


def verify_change_set(changed):
    # Count per glob and exact membership both have to hold; extra or missing
    # files mean the patch or the base dump is not what we vendored against.
    unexpected = sorted(p for p in changed if not expected_match(p))
    missing = sorted(p for p in EXPECTED_EXPLICIT if p not in changed)
    counts = {}
    for pattern, want in EXPECTED_GLOBS:
        got = sum(1 for p in changed if fnmatch.fnmatchcase(p, pattern))
        if got != want: counts[pattern] = (want, got)
    if unexpected or missing or counts:
        raise ValueError('RU patch change set mismatch: extra=%r missing=%r counts=%r' % (unexpected[:5], missing[:5], counts))


def _backward_lz77_uncompress(data):
    # NCCH code compression (3dstool CBackwardLz77): the stream is decoded
    # back-to-front; bytes before the footer's top pointer stay in place.
    # Returns None when the slot carries no valid footer, i.e. it is raw.
    comp = len(data)
    if comp < 8: return None
    top_bottom, original_bottom = struct.unpack_from('<II', data, comp - 8)
    u_top = top_bottom & 0xFFFFFF
    u_bottom = top_bottom >> 24
    if not 8 <= u_bottom <= 11: return None
    if not u_bottom <= u_top <= comp: return None
    uncomp = comp + original_bottom
    out = bytearray(data) + bytearray(original_bottom)
    p_dest = uncomp
    p_src = comp - u_bottom
    p_end = comp - u_top
    while p_src > p_end:
        p_src -= 1
        flag = out[p_src]
        for i in range(8):
            if (flag << i) & 0x80 == 0:
                if p_dest - p_end < 1 or p_src - p_end < 1: return None
                p_dest -= 1; p_src -= 1
                out[p_dest] = out[p_src]
            else:
                if p_src - p_end < 2: return None
                p_src -= 1
                size = out[p_src]
                p_src -= 1
                offset = ((size & 0x0F) << 8 | out[p_src]) + 3
                size = (size >> 4 & 0x0F) + 3
                if size > p_dest - p_end: return None
                p_data = p_dest + offset
                if p_data > uncomp: return None
                for _ in range(size):
                    p_dest -= 1; p_data -= 1
                    out[p_dest] = out[p_data]
            if p_src <= p_end: break
    return bytes(out)


def exefs_files(rom):
    # The verified Rev 1 dumps store the exefs with the legacy ".code/.banner/
    # .icon" name table after the NCCH header; locate it by the .code tag and
    # use 3dstool's extraction names (beat patches those). The code slot is
    # NCCH-compressed in the Rev 1 dumps; the RU patch author extracted it with
    # 3dstool -xvtfu, so uncompress it the same way (fall back to raw bytes if
    # the slot carries no compression footer).
    names = {'.code': 'code.bin', '.main': 'main.bin', '.logo': 'logo.bin',
             '.banner': 'banner.bnr', '.icon': 'icon.icn',
             'code': 'code.bin', 'main': 'main.bin', 'logo': 'logo.bin',
             'banner': 'banner.bnr', 'icon': 'icon.icn'}
    with rom.open('rb') as stream:
        stream.seek(0x120); base = struct.unpack('<I', stream.read(4))[0] * 512
        stream.seek(base); header = stream.read(0x40000)
        at = header.find(b'.code\x00')
        if at < 0: raise ValueError('Unsupported exefs layout')
        table = at; data_at = at + 0x200; files = {}
        for _ in range(5):
            name = header[table:table+8].rstrip(b'\0').decode('latin1')
            if name not in names: break
            off, length = struct.unpack_from('<II', header, table+8)
            table += 0x10
            if length == 0: continue  # empty fixed slot; the table is ordered
            stream.seek(base + data_at + off)
            data = stream.read(length)
            if len(data) != length: raise ValueError('Short exefs read')
            if name in ('.code', 'code'):
                data = _backward_lz77_uncompress(data) or data
            files[names[name]] = data
        if 'code.bin' not in files: raise ValueError('Unsupported exefs layout')
        return files


def _beat_version(beat):
    if not beat.exists(): return None
    try:
        out = subprocess.run([str(beat), '-v'], capture_output=True, text=True, timeout=10, input='')
    except (OSError, subprocess.TimeoutExpired):
        return 'present'
    for line in (out.stdout + out.stderr).splitlines():
        if 'BPM' in line.upper() or 'BPS' in line.upper():
            return line.strip()
    return (out.stdout + out.stderr).strip().splitlines()[0] if (out.stdout + out.stderr).strip() else 'present'


def _read_number(data, at):
    # byuu's beat variable-length integer (nall/beat/multi.hpp readNumber).
    value = 0
    shift = 1
    while True:
        byte = data[at[0]]
        at[0] += 1
        value += (byte & 0x7f) * shift
        if byte & 0x80:
            return value
        shift <<= 7
        value += shift


def apply_bps(patch, source):
    # BPS1 (bps spec, byuu): SourceRead/TargetRead/SourceCopy/TargetCopy with
    # separate relative cursors, then a 12-byte CRC-32 footer.
    at = [0]
    def number(): return _read_number(patch, at)
    if patch[:4] != b'BPS1':
        raise ValueError('Inner patch is not BPS1')
    at[0] = 4
    source_size = number(); target_size = number()
    metadata = number()
    at[0] += metadata
    if source_size != len(source):
        raise ValueError('BPS source size mismatch')
    out = bytearray(target_size)
    out_at = 0
    source_at = 0
    target_at = 0
    while at[0] < len(patch) - 12:
        record = number()
        code = record & 3
        length = (record >> 2) + 1
        if code == 0:
            out[out_at:out_at+length] = source[out_at:out_at+length]
        elif code == 1:
            out[out_at:out_at+length] = patch[at[0]:at[0]+length]
            at[0] += length
        elif code == 2:
            move = number()
            source_at += (move >> 1) * (-1 if move & 1 else 1)
            if source_at < 0 or source_at + length > len(source):
                raise ValueError('BPS source cursor out of range')
            out[out_at:out_at+length] = source[source_at:source_at+length]
            source_at += length
        else:
            move = number()
            target_at += (move >> 1) * (-1 if move & 1 else 1)
            if target_at < 0 or target_at >= out_at:
                raise ValueError('BPS target cursor out of range')
            for n in range(length):
                out[out_at + n] = out[target_at + n]
            target_at += length
        out_at += length
    if out_at != target_size:
        raise ValueError('BPS apply length mismatch')
    source_crc = int.from_bytes(patch[len(patch)-12:len(patch)-8], 'little')
    target_crc = int.from_bytes(patch[len(patch)-8:len(patch)-4], 'little')
    patch_crc = int.from_bytes(patch[len(patch)-4:], 'little')
    masked = lambda v: v & 0xffffffff
    if masked(source_crc) not in (masked(zlib.crc32(source)), masked(~zlib.crc32(source))):
        raise ValueError('BPS source CRC mismatch')
    if masked(target_crc) not in (masked(zlib.crc32(bytes(out))), masked(~zlib.crc32(bytes(out)))):
        raise ValueError('BPS target CRC mismatch')
    if masked(patch_crc) not in (masked(zlib.crc32(patch[:-4])), masked(~zlib.crc32(patch[:-4]))):
        raise ValueError('BPS patch CRC mismatch')
    return bytes(out)


def apply_bpm(data, source):
    # BPM1 multi-file patch (nall/beat/multi.hpp apply): CreatePath/CreateFile/
    # ModifyFile/MirrorFile records over a source tree, CRC-32 trailed.
    at = [0]
    def number(): return _read_number(data, at)
    if data[:4] != b'BPM1':
        raise ValueError('Patch is not BPM1')
    at[0] = 4
    metadata = number()
    at[0] += metadata
    out = dict(source)
    while at[0] < len(data) - 4:
        record = number()
        action = record & 3
        name_len = (record >> 2) + 1
        name = data[at[0]:at[0]+name_len].decode('utf-8')
        at[0] += name_len
        if action == 0:
            continue  # directory marker; files are materialized on demand
        if action == 1:
            size = number()
            out[name] = data[at[0]:at[0]+size]
            at[0] += size
            crc = int.from_bytes(data[at[0]:at[0]+4], 'little'); at[0] += 4
            if crc & 0xffffffff not in (zlib.crc32(out[name]), ~zlib.crc32(out[name]) & 0xffffffff):
                raise ValueError('BPM created file CRC mismatch: ' + name)
            continue
        origin = number()
        origin_is_target = origin & 1
        source_len = origin >> 1
        source_name = name if source_len == 0 else data[at[0]:at[0]+source_len].decode('utf-8')
        at[0] += source_len
        if origin_is_target:
            if source_name not in out:
                raise ValueError('BPM origin is missing from the target tree: ' + source_name)
            base = out[source_name]
        else:
            if source_name not in source:
                raise ValueError('BPM source file missing: ' + source_name)
            base = source[source_name]
        if action == 2:
            size = number()
            out[name] = apply_bps(data[at[0]:at[0]+size], base)
            at[0] += size
        else:
            out[name] = base
            crc = int.from_bytes(data[at[0]:at[0]+4], 'little'); at[0] += 4
            if crc & 0xffffffff not in (zlib.crc32(base), ~zlib.crc32(base) & 0xffffffff):
                raise ValueError('BPM mirrored file CRC mismatch: ' + name)
    trailer = int.from_bytes(data[len(data)-4:], 'little')
    if trailer not in (zlib.crc32(data[:len(data)-4]), ~zlib.crc32(data[:len(data)-4]) & 0xffffffff):
        raise ValueError('BPM patch CRC mismatch')
    return out


def _verify_against_base_tree(base_dir, files):
    # Exact file set + byte equality against a tree shipped in the patch bundle.
    if not base_dir.is_dir():
        raise ValueError('Missing patch base tree: ' + str(base_dir))
    theirs = {p.relative_to(base_dir).as_posix(): p.read_bytes() for p in base_dir.rglob('*') if p.is_file()}
    if theirs.keys() != files.keys():
        missing = sorted(theirs.keys() - files.keys())[:5]
        extra = sorted(files.keys() - theirs.keys())[:5]
        raise ValueError('Base tree file set mismatch: missing=%r extra=%r' % (missing, extra))
    differing = sorted(rel for rel in theirs if theirs[rel] != files[rel])
    if differing:
        raise ValueError('Base tree bytes differ: %r' % differing[:5])


def prepare(rom, patch_dir, work):
    selected = validate(rom)
    if selected['title_id'] != EUR:
        raise ValueError('The Russian overlay is defined for the Europe Rev 1 base only')
    beat_version = _beat_version(patch_dir / '_soft/beat.exe')
    bpm = {}
    for name in ('romfs.bpm', 'exefs.bpm'):
        for candidate in (patch_dir/name, patch_dir/'ZELDA64RUS'/name):
            if candidate.exists(): bpm[name] = candidate; break
        else:
            raise ValueError('Missing patch: ' + name)
    stock = {path: data for path, data in romfs_entries(rom)}
    stock_exefs = exefs_files(rom)
    # If the bundle ships the base trees the patch was built against, our
    # extraction has to match them exactly; otherwise the BPM's own CRC and
    # size checks bind our dump to the patch.
    for base, files in ((patch_dir/'original/romfs', stock), (patch_dir/'original/exefs', stock_exefs)):
        if base.is_dir() and any(base.rglob('*')):
            _verify_against_base_tree(base, files)
    patched_romfs = apply_bpm(bpm['romfs.bpm'].read_bytes(), stock)
    patched_exefs = apply_bpm(bpm['exefs.bpm'].read_bytes(), stock_exefs)
    for base, files in ((patch_dir/'_soft/romfs', patched_romfs), (patch_dir/'_soft/exefs', patched_exefs)):
        if base.is_dir():
            _verify_against_base_tree(base, files)
    changed = {rel: data for rel, data in patched_romfs.items() if data != stock[rel]}
    verify_change_set(changed)
    # Keep a browsable copy of exactly the changed tree for reviewers.
    shutil.rmtree(work, ignore_errors=True)
    changed_dir = work/'changed'
    for rel, data in sorted(changed.items()):
        target = changed_dir/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return {'romfs': changed, 'stock_romfs': {rel: stock[rel] for rel in changed},
            'code': (stock_exefs['code.bin'], patched_exefs['code.bin']),
            'beat_version': beat_version}


def vendor(result, dest):
    # Exact-case ROM paths; code.bin/icon/banner stay metadata-only (the deck
    # never shows exefs art and its code.bps overlay targets stock code).
    if dest.exists(): shutil.rmtree(dest)
    for rel, data in result['romfs'].items():
        target = dest/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    stock_code, patched_code = result['code']
    manifest = {
        'schema': 1,
        'source': SOURCE,
        'files': [{'path': rel, 'size': len(data), 'sha256': digest(data),
                   'stock_sha256': digest(result['stock_romfs'][rel])}
                  for rel, data in sorted(result['romfs'].items())],
        'exefs': {
            'code.bin': {'vendored': False, 'changed': False,
                         'stock_sha256': digest(stock_code), 'patched_sha256': digest(patched_code),
                         'note': 'The RU patch leaves code.bin byte-identical (its CRC 0xffdf1ee8 is '
                                 'the unmodified base, verified by exefs.bpm). Stock EUR code is '
                                 'NCCH-compressed in the .cci; decoded here it is byte-identical to '
                                 'the decoded USA code, which the shipped code.bps targets. No code '
                                 'composition is needed for Russian text.'},
            'icon.icn': {'vendored': False, 'changed': True,
                         'note': 'The RU patch restyles the exefs icon (Russian title art); the deck '
                                 'never shows exefs icon/banner art.'},
            'banner.bnr': {'vendored': False, 'changed': False,
                           'note': 'The deck never shows exefs icon/banner art.'},
        },
    }
    (dest/'manifest.json').write_text(json.dumps(manifest, indent=1)+'\n')
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rom', type=Path, required=True)
    p.add_argument('--patch', type=Path, required=True, help='LoZMM3D_(PAL_rev1)_RUS_Patch_v1.1 directory')
    p.add_argument('--work', type=Path, default=Path('.scratch/rus-build'))
    p.add_argument('--write', action='store_true', help='vendor the result into resources/mm3d/rus/')
    args = p.parse_args()
    result = prepare(args.rom, args.patch, args.work)
    print('changed romfs files:', len(result['romfs']), 'bytes:', sum(len(d) for d in result['romfs'].values()))
    print('exefs code changed:', result['code'][0] != result['code'][1], 'beat:', result['beat_version'] or 'unused (BPM1 applied natively)')
    if args.write:
        manifest = vendor(result, RESOURCES/'rus')
        print('vendored:', len(manifest['files']), 'files ->', RESOURCES/'rus')


if __name__ == '__main__':
    main()
