"""Install the Android fork's authored HUD from guarded, ROM-derived copy operations."""
import base64
import hashlib
import json
from pathlib import Path
from upgrade_game_resources import atomic_write, checked

CONFIG = 'config/mm3d-local/presentation.json'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def reconstruct(source, spec):
    if digest(source) == spec['sha256']:
        return source
    for variant in spec.get('source_variants', []):
        if digest(source) == variant['sha256']:
            normalized = bytearray(source)
            for op in variant['normalize']:
                at = op['at']
                before = base64.b64decode(op['before'], validate=True)
                after = base64.b64decode(op['after'], validate=True)
                if (len(before) != len(after) or at < 0 or at > len(source) - len(before)
                        or source[at:at+len(before)] != before):
                    raise ValueError('HUD source normalization mismatch')
                normalized[at:at+len(after)] = after
            source = bytes(normalized)
            break
    if digest(source) != spec['source_sha256']:
        raise ValueError('HUD archive has custom changes; retained existing HUD')
    output = bytearray()
    for op in spec['ops']:
        if 'copy' in op:
            at, size = op['copy'], op['size']
            if at < 0 or size < 0 or at + size > len(source):
                raise ValueError('Invalid HUD copy bounds')
            output.extend(source[at:at+size])
        else:
            output.extend(base64.b64decode(op['data'], validate=True))
        if len(output) > spec['size']:
            raise ValueError('HUD output exceeds expected size')
    if len(output) != spec['size'] or digest(output) != spec['sha256']:
        raise ValueError('HUD output checksum mismatch')
    return bytes(output)

def installed_title(user):
    # The installed tree carries exactly one supported game directory.
    mods = user / 'load/mods'
    titles = sorted(p.name for p in mods.iterdir() if p.is_dir()) if mods.is_dir() else []
    if len(titles) != 1 or titles[0] not in ('0004000000125500', '0004000000125600'):
        raise ValueError('Expected one supported installed game under load/mods')
    return titles[0]


def apply(user, resources):
    spec = json.loads((resources/'desktop-hud/layout.json').read_bytes())
    atlas_spec = json.loads((resources/'desktop-hud/upgrade.json').read_bytes())
    texture = (resources/'desktop-hud'/atlas_spec['texture']).read_bytes()
    if digest(texture) != atlas_spec['texture_sha256']:
        raise ValueError('Android HUD atlas checksum mismatch')
    title = installed_title(user)
    archive = checked(user, f'load/mods/{title}/romfs/layout/Joker.Main.New.gar')
    source = archive.read_bytes()
    try:
        updated = reconstruct(source, spec)
    except ValueError as error:
        if digest(source) != spec['source_sha256'] and digest(source) != spec['sha256']:
            print(str(error))
            return  # Never replace another user's authored archive.
        raise
    play_spec = json.loads((resources/'desktop-hud/play.json').read_bytes())
    play = checked(user, f'load/mods/{title}/romfs/layout/Joker.Main.Play.gar')
    play_original = play.read_bytes()
    play_updated = reconstruct(play_original, play_spec)
    config = checked(user, CONFIG)
    raw = config.read_bytes()
    data = json.loads(raw)
    keys = spec['presentation']
    if any(all(data.get(k) == old.get(k) for k in keys) for old in spec['previous']):
        data.update(keys)
    new_config = (json.dumps(data, indent=2)+'\n').encode()
    backup = 'config/dekui-backups/desktop-hud-'+digest(source)[:12]
    if source != updated:
        saved = checked(user, backup+'.gar')
        if not saved.exists(): atomic_write(saved, source)
    if data != json.loads(raw):
        saved = checked(user, backup+'.json')
        if not saved.exists(): atomic_write(saved, raw)
    # Every byte is checked before publishing; a retry safely completes any partial update.
    texture_target = checked(user, f'load/mm3d-model-textures/{title}/hud/'+atlas_spec['texture'])
    if not texture_target.exists() or digest(texture_target.read_bytes()) != digest(texture):
        atomic_write(texture_target, texture)
    pack = checked(user, f'load/mm3d-model-textures/{title}/pack.json')
    if not pack.exists():
        atomic_write(pack, b'{"options":{"skip_mipmap":true,"flip_png_files":true,"use_new_hash":true}}')
    if play_original != play_updated:
        saved = checked(user, 'config/dekui-backups/desktop-play-'+digest(play_original)[:12]+'.gar')
        if not saved.exists(): atomic_write(saved, play_original)
        atomic_write(play, play_updated)
    if source != updated: atomic_write(archive, updated)
    if data != json.loads(raw): atomic_write(config, new_config)


def apply_controls(user, resources):
    spec = json.loads((resources/'desktop-controls/provenance.json').read_bytes())
    replacement = (resources/'desktop-controls/code.bps').read_bytes()
    if digest(replacement) != spec['patch_sha256']:
        raise ValueError('Desktop gameplay input patch checksum mismatch')
    target = checked(user, f'load/mods/{installed_title(user)}/code.bps')
    original = target.read_bytes()
    if digest(original) == spec['patch_sha256']:
        return
    if digest(original) not in (spec['baseline_patch_sha256'], spec.get('legacy_patch_sha256')):
        raise ValueError('Custom gameplay patch retained; cannot apply the default input patch')
    backup = checked(user, 'config/dekui-backups/code-before-desktop-pc-input.bps')
    if not backup.exists(): atomic_write(backup, original)
    atomic_write(target, replacement)
