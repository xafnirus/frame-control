"""Media planning shared by Frame Control and its own Frame-side player.

No viewer dependencies. Filename hints are suggestions, never guesses from
resolution. Explicit layout wins; conflicting hints require a choice.
"""
import re
from pathlib import Path

LAYOUTS = ('auto', 'mono', 'sbs', 'ou', 'full-sbs', 'full-ou',
           'sbs-rl', 'ou-rl', 'full-sbs-rl', 'full-ou-rl')
VIDEO = {'.mp4', '.mkv', '.mov', '.webm', '.m4v'}
PHOTO = {'.png', '.jpg', '.jpeg'}


def plan(name, layout='auto', metadata=None):
    if layout not in LAYOUTS:
        raise ValueError('Choose a supported media layout: ' + ', '.join(LAYOUTS))
    suffix = Path(name).suffix.lower()
    if suffix in {'.heic', '.heif', '.avif', '.mpo'}:
        raise ValueError('Native spatial-photo containers are not supported yet; export both eyes as SBS or OU PNG/JPEG')
    if suffix == '.splat':
        return {'kind': 'splat', 'layout': 'sbs', 'source': 'renderer'}
    if suffix not in VIDEO | PHOTO:
        raise ValueError('Use MP4/MKV/MOV/WebM video, PNG/JPEG stereo photos, or a .splat file')
    source = 'explicit'
    if layout == 'auto':
        tokens = set(re.split(r'[^a-z0-9]+', Path(name).stem.lower()))
        if tokens & {'rl', 'bt'}:
            raise ValueError('Right-eye-first filename tags need an explicit layout')
        hints = set()
        for value, tags in [('full-sbs', {'fsbs'}), ('full-ou', {'fou', 'ftb'}),
                            ('sbs', {'sbs', 'hsbs', 'lr'}), ('ou', {'ou', 'hou', 'tb', 'htb'})]:
            if tokens & tags:
                hints.add(value)
        if len(hints) > 1:
            raise ValueError('Conflicting stereo filename tags; choose the layout explicitly')
        layout = next(iter(hints), None)
        source = 'filename'
        if not layout:
            # Matroska StereoMode/FFmpeg stereo_mode: known horizontal/vertical packing.
            mode = (metadata or {}).get('stereo_mode')
            layout = {'left_right': 'full-sbs', 'top_bottom': 'full-ou',
                      'right_left': 'full-sbs-rl', 'bottom_top': 'full-ou-rl', 'mono': 'mono'}.get(mode)
            source = 'metadata'
            if mode and layout is None:
                raise ValueError('Unsupported stereo metadata; choose the eye order/layout explicitly')
        if not layout:
            raise ValueError('No stereo layout found; choose mono, SBS or OU with the correct eye order')
    return {'kind': 'video' if suffix in VIDEO else 'photo', 'layout': layout, 'source': source}


def geometry(width, height, layout, sample_aspect_ratio=None, rotation=0):
    """Bound transfer to 1920x1080 while preserving each eye's display aspect."""
    if not 0 < width <= 32768 or not 0 < height <= 32768:
        raise ValueError('Invalid media dimensions')
    if layout not in LAYOUTS[1:]:
        raise ValueError('Resolve the layout before playback')
    if rotation not in (0, 90, 180, 270):
        raise ValueError('Unsupported media rotation; export with rotation applied first')
    if rotation and layout != 'mono':
        raise ValueError('Cannot play rotated stereo media; export with rotation applied and choose its resulting eye packing')
    # ffprobe uses 0:1 or N/A when the source does not specify pixel shape.
    pixel_aspect = 1
    if sample_aspect_ratio not in (None, '', 'N/A', '0:1'):
        ratio = re.fullmatch(r'([0-9]+):([0-9]+)', sample_aspect_ratio) if isinstance(sample_aspect_ratio, str) else None
        if not ratio or not all(int(v) > 0 for v in ratio.groups()):
            raise ValueError('Invalid media pixel aspect ratio')
        pixel_aspect = int(ratio[1]) / int(ratio[2])
    # FFmpeg autorotates before our scale filter. A quarter turn swaps both
    # the raster axes and the source pixel shape.
    if rotation in (90, 270):
        width, height = height, width
        pixel_aspect = 1 / pixel_aspect
    scale = min(1, 1920 / width, 1080 / height)
    w, h = max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)
    packing = {'mono': 1, 'sbs': 2, 'ou': .5, 'full-sbs': 1, 'full-ou': 1}[layout.removesuffix('-rl')]
    # Scaling rounds to even dimensions; raw RGBA carries no aspect metadata.
    aspect = packing * pixel_aspect * (width * h / (height * w))
    return w, h, aspect


def stereo_pixels(data, width, height, layout):
    """Normalize packing and eye order to OpenVR's left-first side-by-side texture."""
    if len(data) != width * height * 4:
        raise ValueError('Incomplete RGBA frame')
    reverse = layout.endswith('-rl')
    base = layout.removesuffix('-rl')
    stride = width * 4
    if base in ('sbs', 'full-sbs') and reverse:
        if width % 2:
            raise ValueError('Side-by-side media needs an even width')
        half = stride // 2
        return b''.join(data[y*stride+half:(y+1)*stride] + data[y*stride:y*stride+half]
                        for y in range(height)), width, height
    if base not in ('ou', 'full-ou'):
        return data, width, height
    if height % 2:
        raise ValueError('Over-under media needs an even height')
    half = height // 2
    left, right = (half, 0) if reverse else (0, half)
    return b''.join(data[(y+left)*stride:(y+left+1)*stride] +
                    data[(y+right)*stride:(y+right+1)*stride] for y in range(half)), width*2, half
