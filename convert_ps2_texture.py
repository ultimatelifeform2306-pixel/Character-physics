#!/usr/bin/env python3
"""Convert a PS2 character texture sheet into a GTA San Andreas ped texture.

GTA SA ped textures are power-of-two images; 256x256 is the usual size for a
body texture. This resizes the sheet to 256x256 RGBA and writes it as a PNG
with zlib compression level 0 (no compression).

It does not re-arrange the UV islands: where each body part sits on the
texture is decided by the model's UV map, so the sheet must already be laid
out for the target .dff model.

Usage: python3 convert_ps2_texture.py [input.png] [output.png]
"""

import sys

from PIL import Image

SIZE = (256, 256)


def convert(src_path, dst_path):
    img = Image.open(src_path)
    print(f"Input:  {src_path} {img.size[0]}x{img.size[1]} mode={img.mode}")

    # Palettised PS2 dumps (P mode) can carry transparency in the palette;
    # converting to RGBA keeps it.
    img = img.convert("RGBA")

    # PS2 textures often store alpha in the 0-128 range (128 = opaque).
    # If no alpha value goes above 128, scale it up to the PC 0-255 range.
    alpha = img.getchannel("A")
    if 0 < alpha.getextrema()[1] <= 128:
        alpha = alpha.point(lambda a: min(255, a * 2))
        img.putalpha(alpha)
        print("Scaled PS2 alpha (0-128) to 0-255")

    if img.size != SIZE:
        img = img.resize(SIZE, Image.LANCZOS)

    img.save(dst_path, "PNG", compress_level=0, optimize=False)
    print(f"Output: {dst_path} {img.size[0]}x{img.size[1]} RGBA, uncompressed")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "ps2_char.png"
    dst = sys.argv[2] if len(sys.argv) > 2 else "claude.png"
    try:
        convert(src, dst)
    except FileNotFoundError:
        sys.exit(f"Error: '{src}' not found. Put the PS2 texture sheet next to "
                 "this script or pass its path as the first argument.")
