"""Paint the small, PS2-sized textures for Frieza [Drip].

Run with any Python that has Pillow:  python3 blender/make_textures.py
Writes PNGs into blender/textures/. Sizes are kept tiny (64-256 px) on purpose;
the model samples them with nearest filtering for the crunchy console look.
"""
import math
import os
import random
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "textures")
os.makedirs(OUT, exist_ok=True)
rnd = random.Random(2306)


def noisy(size, base, amount, blotches=0, blotch_col=None):
    w, h = size
    img = Image.new("RGB", size, base)
    px = img.load()
    for y in range(h):
        for x in range(w):
            d = rnd.randint(-amount, amount)
            r, g, b = px[x, y]
            px[x, y] = (max(0, min(255, r + d)), max(0, min(255, g + d)), max(0, min(255, b + d)))
    dr = ImageDraw.Draw(img)
    for _ in range(blotches):
        cx, cy, r = rnd.randrange(w), rnd.randrange(h), rnd.randint(2, 6)
        dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=blotch_col)
    return img


def save(img, name):
    img.save(os.path.join(OUT, name))


# Jacket: worn purple suede.
jacket = noisy((128, 128), (92, 44, 138), 14, blotches=40, blotch_col=(78, 36, 118))
d = ImageDraw.Draw(jacket)
for y in (0, 63):  # faint panel seams
    d.line((0, y, 127, y), fill=(60, 28, 92))
save(jacket, "jacket.png")

# Ribbed cuffs, hem and collar band.
rib = Image.new("RGB", (64, 32), (82, 38, 124))
d = ImageDraw.Draw(rib)
for x in range(0, 64, 4):
    d.line((x, 0, x, 31), fill=(58, 26, 90))
    d.line((x + 1, 0, x + 1, 31), fill=(104, 52, 152))
save(rib, "rib.png")

# Shirt: black tee with the red "MPLRC GUYS" print. U wraps the torso; the
# chest faces u = 0.75 and v runs from the hem (bottom) to the collar (top).
W, H = 256, 128
shirt = noisy((W, H), (22, 22, 26), 5)
d = ImageDraw.Draw(shirt)
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 15)
cx = int(0.75 * W)
for text, v in (("MPLRC", 0.70), ("GUYS", 0.52)):
    tw = d.textlength(text, font=font)
    y = int((1 - v) * H) - 8
    d.text((cx - tw / 2, y), text, font=font, fill=(200, 34, 30))
px = shirt.load()  # crack the print a little so it reads as screen-printed
for _ in range(220):
    x, y = rnd.randrange(cx - 30, cx + 30), rnd.randrange(20, 70)
    if px[x, y][0] > 120:
        px[x, y] = (120, 22, 22)
save(shirt, "shirt.png")

# Cargo pants: black twill with a couple of seam lines.
pants = noisy((128, 128), (30, 30, 34), 7)
d = ImageDraw.Draw(pants)
for x in (0, 64):
    d.line((x, 0, x, 127), fill=(16, 16, 18))
for y in range(0, 128, 2):  # diagonal twill hint
    d.point(((y * 3) % 128, y), fill=(40, 40, 46))
save(pants, "pants.png")

# Sneakers: red uppers with black wave stripes (TN-style). U wraps around the
# shoe (u=0 and u=0.5 are its two sides) and v runs heel to toe.
shoe = Image.new("RGB", (128, 64))
d = ImageDraw.Draw(shoe)
for y in range(64):
    t = y / 63
    d.line((0, y, 127, y), fill=(int(150 + 70 * t), int(16 + 10 * t), int(16 + 8 * t)))
for centre in (0.0, 0.5):  # u=0 and u=0.5 are the two sides of the shoe
    for k in (-2, -1, 0, 1, 2):
        pts = []
        for y in range(64):
            x = (centre + k * 0.045) * 128 + 3 * math.sin(y / 63 * math.tau * 1.5 + k)
            pts.append((x % 128, y))
        d.line(pts, fill=(14, 10, 12), width=2)
save(shoe, "shoe.png")

# Sole: dark rubber with a red air-unit stripe.
sole = Image.new("RGB", (64, 32), (24, 20, 22))
d = ImageDraw.Draw(sole)
d.rectangle((0, 12, 63, 18), fill=(170, 24, 22))
for x in range(0, 64, 8):
    d.rectangle((x, 13, x + 4, 17), fill=(220, 60, 50))
save(sole, "sole.png")

print("textures written to", OUT)
