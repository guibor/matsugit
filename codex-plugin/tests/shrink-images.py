"""Shrink documentation screenshots in place: 256-colour PNG, no dithering.

UI captures have few distinct colours, so this is visually identical at well
under half the size. Files that would not get smaller are left alone.

    python3 codex-plugin/tests/shrink-images.py docs/images/**/*.png
"""
import io
from pathlib import Path
import sys

from PIL import Image


def shrink(path):
    path = Path(path)
    before = path.read_bytes()
    with Image.open(io.BytesIO(before)) as image:
        if image.mode == 'P':
            return len(before), len(before)
        quantized = image.convert('RGB').quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    buffer = io.BytesIO()
    quantized.save(buffer, 'PNG', optimize=True)
    after = buffer.getvalue()
    if len(after) < len(before):
        path.write_bytes(after)
        return len(before), len(after)
    return len(before), len(before)


if __name__ == '__main__':
    total_before = total_after = 0
    for name in sys.argv[1:]:
        before, after = shrink(name)
        total_before += before; total_after += after
        print(f'{name}: {before // 1024} KB -> {after // 1024} KB')
    print(f'total: {total_before // 1024} KB -> {total_after // 1024} KB')
