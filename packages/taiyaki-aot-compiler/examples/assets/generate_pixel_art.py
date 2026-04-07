#!/usr/bin/env python3
"""Generate pixel art PNG assets for pixel_forest.js demo.

Uses only Python built-in modules (struct, zlib) — no Pillow needed.
Run: python examples/assets/generate_pixel_art.py
"""

import struct
import zlib
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def write_png(filename, width, height, pixels):
    """Write RGBA pixel data as a PNG file.
    pixels: list of (r, g, b, a) tuples, row-major, top-to-bottom.
    """

    def chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))

    raw = b""
    for y in range(height):
        raw += b"\x00"  # filter: none
        for x in range(width):
            r, g, b, a = pixels[y * width + x]
            raw += struct.pack("BBBB", r, g, b, a)

    idat = chunk(b"IDAT", zlib.compress(raw, 9))
    iend = chunk(b"IEND", b"")

    path = os.path.join(SCRIPT_DIR, filename)
    with open(path, "wb") as f:
        f.write(sig + ihdr + idat + iend)
    print(f"  Created {path} ({width}x{height})")


def make_image(width, height, fill=(0, 0, 0, 0)):
    return [fill] * (width * height)


def set_pixel(img, w, h, x, y, color):
    if 0 <= x < w and 0 <= y < h:
        img[y * w + x] = color


def fill_rect(img, w, h, x0, y0, rw, rh, color):
    for dy in range(rh):
        for dx in range(rw):
            set_pixel(img, w, h, x0 + dx, y0 + dy, color)


def draw_circle_filled(img, w, h, cx, cy, r, color):
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                set_pixel(img, w, h, cx + dx, cy + dy, color)


# ──────────────────────────────────────────────
#  Color Palette
# ──────────────────────────────────────────────
T = (0, 0, 0, 0)  # transparent
BLACK = (20, 16, 24, 255)
DARK_BROWN = (80, 50, 30, 255)
BROWN = (140, 95, 55, 255)
LIGHT_BROWN = (190, 140, 80, 255)
SKIN = (230, 180, 140, 255)
DARK_GREEN = (30, 80, 40, 255)
GREEN = (50, 150, 50, 255)
LIGHT_GREEN = (100, 200, 80, 255)
BRIGHT_GREEN = (140, 230, 100, 255)
DARK_BLUE = (20, 40, 100, 255)
BLUE = (50, 100, 200, 255)
LIGHT_BLUE = (120, 180, 240, 255)
SKY_BLUE = (160, 210, 250, 255)
WHITE = (240, 240, 245, 255)
GRAY = (140, 140, 150, 255)
DARK_GRAY = (80, 80, 90, 255)
RED = (200, 50, 40, 255)
ORANGE = (230, 140, 40, 255)
YELLOW = (240, 220, 60, 255)
GOLD = (255, 200, 50, 255)
PURPLE = (120, 50, 160, 255)
DARK_PURPLE = (60, 30, 80, 255)
PINK = (220, 120, 160, 255)
TEAL = (40, 180, 160, 255)
DIRT_DARK = (100, 65, 35, 255)
DIRT = (140, 95, 55, 255)
DIRT_LIGHT = (170, 120, 70, 255)
STONE_DARK = (90, 90, 100, 255)
STONE = (130, 130, 140, 255)
STONE_LIGHT = (170, 170, 180, 255)
MOSS = (60, 120, 50, 255)
WATER_DEEP = (30, 60, 140, 255)
WATER = (50, 110, 190, 255)
WATER_LIGHT = (90, 160, 220, 255)
WATER_SURFACE = (120, 190, 240, 200)

CAPE_DARK = (40, 60, 140, 255)
CAPE = (60, 90, 180, 255)
CAPE_LIGHT = (90, 120, 210, 255)
HAT_DARK = (100, 40, 30, 255)
HAT = (160, 60, 40, 255)
HAT_LIGHT = (200, 90, 60, 255)
BOOT_DARK = (60, 40, 25, 255)
BOOT = (100, 65, 40, 255)
TUNIC = (70, 130, 60, 255)
TUNIC_DARK = (45, 90, 40, 255)
TUNIC_LIGHT = (100, 160, 80, 255)
BELT = (160, 120, 50, 255)
EYE = (255, 255, 255, 255)
PUPIL = (30, 30, 50, 255)


# ──────────────────────────────────────────────
#  Player Sprite Sheet: 16x24 per frame
#  Layout: 4 columns x 4 rows
#  Row 0: idle (2 frames + 2 empty)
#  Row 1: run (4 frames)
#  Row 2: jump-up, jump-down, 2 empty
#  Row 3: (reserved)
# ──────────────────────────────────────────────
def generate_player():
    FW, FH = 16, 24
    COLS, ROWS = 4, 4
    W, H = FW * COLS, FH * ROWS
    img = make_image(W, H)

    def put(frame_col, frame_row, local_pixels):
        """Place pixel art into a frame. local_pixels: list of (x, y, color)."""
        ox = frame_col * FW
        oy = frame_row * FH
        for x, y, c in local_pixels:
            set_pixel(img, W, H, ox + x, oy + y, c)

    def draw_character(fc, fr, leg_phase=0, arm_phase=0, y_off=0):
        """Draw the adventurer character.
        leg_phase: 0=stand, 1=left-forward, 2=right-forward
        arm_phase: 0=down, 1=back, 2=forward
        y_off: vertical offset (for bobbing)
        """
        px = []

        # Hat (wide brim adventurer hat)
        for x in range(3, 13):
            px.append((x, 2 + y_off, HAT_DARK))  # brim
        for x in range(4, 12):
            px.append((x, 1 + y_off, HAT))
        for x in range(5, 11):
            px.append((x, 0 + y_off, HAT))
        for x in range(6, 10):
            px.append((x, 1 + y_off, HAT_LIGHT))  # highlight

        # Head
        for x in range(5, 11):
            px.append((x, 3 + y_off, SKIN))
            px.append((x, 4 + y_off, SKIN))
            px.append((x, 5 + y_off, SKIN))
        # Hair sides
        px.append((4, 3 + y_off, DARK_BROWN))
        px.append((4, 4 + y_off, DARK_BROWN))
        px.append((11, 3 + y_off, DARK_BROWN))
        px.append((11, 4 + y_off, DARK_BROWN))
        # Eyes
        px.append((6, 4 + y_off, EYE))
        px.append((7, 4 + y_off, PUPIL))
        px.append((9, 4 + y_off, EYE))
        px.append((10, 4 + y_off, PUPIL))
        # Mouth
        px.append((7, 5 + y_off, DARK_BROWN))
        px.append((8, 5 + y_off, DARK_BROWN))

        # Neck
        px.append((7, 6 + y_off, SKIN))
        px.append((8, 6 + y_off, SKIN))

        # Torso (tunic)
        for y in range(7, 13):
            for x in range(5, 11):
                c = TUNIC if (x + y) % 3 != 0 else TUNIC_DARK
                px.append((x, y + y_off, c))
        # Tunic highlights
        px.append((6, 8 + y_off, TUNIC_LIGHT))
        px.append((7, 9 + y_off, TUNIC_LIGHT))
        # Belt
        for x in range(5, 11):
            px.append((x, 11 + y_off, BELT))
        px.append((8, 11 + y_off, GOLD))  # buckle

        # Cape (behind, visible on sides)
        px.append((4, 7 + y_off, CAPE_DARK))
        px.append((4, 8 + y_off, CAPE))
        px.append((4, 9 + y_off, CAPE))
        px.append((4, 10 + y_off, CAPE_LIGHT))
        px.append((4, 11 + y_off, CAPE))
        px.append((4, 12 + y_off, CAPE_DARK))
        px.append((11, 7 + y_off, CAPE_DARK))
        px.append((11, 8 + y_off, CAPE))
        px.append((11, 9 + y_off, CAPE))
        px.append((11, 10 + y_off, CAPE_LIGHT))
        px.append((11, 11 + y_off, CAPE))
        px.append((11, 12 + y_off, CAPE_DARK))

        # Arms
        if arm_phase == 0:  # arms down
            px.append((4, 8 + y_off, SKIN))
            px.append((4, 9 + y_off, SKIN))
            px.append((11, 8 + y_off, SKIN))
            px.append((11, 9 + y_off, SKIN))
        elif arm_phase == 1:  # left back, right forward
            px.append((3, 8 + y_off, SKIN))
            px.append((3, 9 + y_off, SKIN))
            px.append((12, 7 + y_off, SKIN))
            px.append((12, 8 + y_off, SKIN))
        elif arm_phase == 2:  # left forward, right back
            px.append((3, 7 + y_off, SKIN))
            px.append((3, 8 + y_off, SKIN))
            px.append((12, 8 + y_off, SKIN))
            px.append((12, 9 + y_off, SKIN))

        # Legs
        if leg_phase == 0:  # standing
            for x in [6, 7]:
                px.append((x, 13 + y_off, TUNIC_DARK))
                px.append((x, 14 + y_off, DARK_BROWN))
                px.append((x, 15 + y_off, BOOT))
                px.append((x, 16 + y_off, BOOT))
                px.append((x, 17 + y_off, BOOT_DARK))
            for x in [9, 10]:
                px.append((x, 13 + y_off, TUNIC_DARK))
                px.append((x, 14 + y_off, DARK_BROWN))
                px.append((x, 15 + y_off, BOOT))
                px.append((x, 16 + y_off, BOOT))
                px.append((x, 17 + y_off, BOOT_DARK))
            # Boot toe
            px.append((5, 17 + y_off, BOOT_DARK))
            px.append((11, 17 + y_off, BOOT_DARK))
        elif leg_phase == 1:  # left forward
            for x in [5, 6]:
                px.append((x, 13 + y_off, TUNIC_DARK))
                px.append((x, 14 + y_off, BOOT))
                px.append((x, 15 + y_off, BOOT))
                px.append((x, 16 + y_off, BOOT_DARK))
            for x in [9, 10]:
                px.append((x, 13 + y_off, TUNIC_DARK))
                px.append((x, 14 + y_off, BOOT))
                px.append((x, 15 + y_off, BOOT))
                px.append((x, 16 + y_off, BOOT))
                px.append((x, 17 + y_off, BOOT_DARK))
            px.append((4, 16 + y_off, BOOT_DARK))
            px.append((11, 17 + y_off, BOOT_DARK))
        elif leg_phase == 2:  # right forward
            for x in [6, 7]:
                px.append((x, 13 + y_off, TUNIC_DARK))
                px.append((x, 14 + y_off, BOOT))
                px.append((x, 15 + y_off, BOOT))
                px.append((x, 16 + y_off, BOOT))
                px.append((x, 17 + y_off, BOOT_DARK))
            for x in [10, 11]:
                px.append((x, 13 + y_off, TUNIC_DARK))
                px.append((x, 14 + y_off, BOOT))
                px.append((x, 15 + y_off, BOOT))
                px.append((x, 16 + y_off, BOOT_DARK))
            px.append((5, 17 + y_off, BOOT_DARK))
            px.append((12, 16 + y_off, BOOT_DARK))

        put(fc, fr, px)

    # Row 0: Idle (2 frames)
    draw_character(0, 0, leg_phase=0, arm_phase=0, y_off=0)
    draw_character(1, 0, leg_phase=0, arm_phase=0, y_off=1)

    # Row 1: Run (4 frames)
    draw_character(0, 1, leg_phase=1, arm_phase=1, y_off=0)
    draw_character(1, 1, leg_phase=0, arm_phase=0, y_off=1)
    draw_character(2, 1, leg_phase=2, arm_phase=2, y_off=0)
    draw_character(3, 1, leg_phase=0, arm_phase=0, y_off=1)

    # Row 2: Jump-up, Jump-down
    draw_character(0, 2, leg_phase=0, arm_phase=2, y_off=0)
    draw_character(1, 2, leg_phase=0, arm_phase=1, y_off=1)

    write_png("player.png", W, H, img)


# ──────────────────────────────────────────────
#  Tileset: 16x16 per tile, 8 columns x 8 rows
#  0: grass top        1: grass top var2
#  2: dirt             3: dirt var2
#  4: stone            5: stone cracked
#  6: mossy stone      7: empty
#  8: water1           9: water2
#  10: water3          11: water4
#  12: bridge plank    13: bridge railing
#  14: thorn           15: empty
#  16: flower-red      17: flower-blue
#  18: mushroom        19: crystal
#  20: torch-on1       21: torch-on2
#  22: grass-blade     23: bush
#  24..31: tree parts (trunk, leaves, etc.)
# ──────────────────────────────────────────────
def generate_tileset():
    TS = 16
    COLS, ROWS = 8, 8
    W, H = TS * COLS, TS * ROWS
    img = make_image(W, H)

    def tile_rect(tile_id, x, y, rw, rh, color):
        ox = (tile_id % COLS) * TS
        oy = (tile_id // COLS) * TS
        fill_rect(img, W, H, ox + x, oy + y, rw, rh, color)

    def tile_pixel(tile_id, x, y, color):
        ox = (tile_id % COLS) * TS
        oy = (tile_id // COLS) * TS
        set_pixel(img, W, H, ox + x, oy + y, color)

    # Tile 0: Grass top
    fill_rect(img, W, H, 0, 0, TS, TS, DIRT)
    tile_rect(0, 0, 0, 16, 4, GREEN)
    tile_rect(0, 0, 4, 16, 2, DARK_GREEN)
    # Grass blade details
    for x in [1, 3, 5, 8, 10, 13]:
        tile_pixel(0, x, 0, BRIGHT_GREEN)
    for x in [2, 6, 11, 14]:
        tile_pixel(0, x, 0, LIGHT_GREEN)
    # Dirt texture below
    tile_pixel(0, 3, 8, DIRT_LIGHT)
    tile_pixel(0, 7, 10, DIRT_DARK)
    tile_pixel(0, 12, 9, DIRT_LIGHT)
    tile_pixel(0, 5, 13, DIRT_DARK)

    # Tile 1: Grass top variant 2
    ox, oy = TS, 0
    fill_rect(img, W, H, ox, oy, TS, TS, DIRT)
    tile_rect(1, 0, 0, 16, 4, GREEN)
    tile_rect(1, 0, 4, 16, 2, DARK_GREEN)
    for x in [0, 4, 7, 9, 12, 15]:
        tile_pixel(1, x, 0, BRIGHT_GREEN)
    for x in [2, 6, 10, 14]:
        tile_pixel(1, x, 0, LIGHT_GREEN)
    # Small flower in grass
    tile_pixel(1, 4, 1, YELLOW)
    tile_pixel(1, 3, 2, GREEN)
    tile_pixel(1, 5, 2, GREEN)
    tile_pixel(1, 11, 1, PINK)
    tile_pixel(1, 10, 2, GREEN)
    tile_pixel(1, 12, 2, GREEN)

    # Tile 2: Dirt
    fill_rect(img, W, H, 2 * TS, 0, TS, TS, DIRT)
    for pos in [(2, 3), (8, 1), (13, 5), (5, 9), (10, 12), (1, 14), (14, 8)]:
        tile_pixel(2, pos[0], pos[1], DIRT_DARK)
    for pos in [(4, 7), (11, 2), (7, 13), (0, 6), (15, 10)]:
        tile_pixel(2, pos[0], pos[1], DIRT_LIGHT)
    # Small stones
    tile_pixel(2, 6, 4, STONE_DARK)
    tile_pixel(2, 12, 11, STONE_DARK)

    # Tile 3: Dirt variant 2
    fill_rect(img, W, H, 3 * TS, 0, TS, TS, DIRT)
    for pos in [(1, 2), (9, 4), (14, 7), (4, 11), (7, 14), (11, 1)]:
        tile_pixel(3, pos[0], pos[1], DIRT_DARK)
    for pos in [(3, 5), (12, 9), (6, 12), (0, 0), (15, 15)]:
        tile_pixel(3, pos[0], pos[1], DIRT_LIGHT)
    # Root
    tile_pixel(3, 5, 1, DARK_BROWN)
    tile_pixel(3, 6, 1, DARK_BROWN)
    tile_pixel(3, 7, 2, DARK_BROWN)

    # Tile 4: Stone
    fill_rect(img, W, H, 4 * TS, 0, TS, TS, STONE)
    tile_rect(4, 0, 0, 16, 1, STONE_LIGHT)
    tile_rect(4, 0, 15, 16, 1, STONE_DARK)
    tile_rect(4, 0, 0, 1, 16, STONE_LIGHT)
    tile_rect(4, 15, 0, 1, 16, STONE_DARK)
    # Mortar lines
    tile_rect(4, 0, 7, 16, 1, STONE_DARK)
    tile_rect(4, 8, 0, 1, 8, STONE_DARK)
    tile_rect(4, 4, 7, 1, 9, STONE_DARK)
    tile_rect(4, 12, 7, 1, 9, STONE_DARK)
    # Highlights
    tile_pixel(4, 3, 3, STONE_LIGHT)
    tile_pixel(4, 10, 4, STONE_LIGHT)
    tile_pixel(4, 6, 11, STONE_LIGHT)
    tile_pixel(4, 14, 12, STONE_LIGHT)

    # Tile 5: Stone cracked
    fill_rect(img, W, H, 5 * TS, 0, TS, TS, STONE)
    tile_rect(5, 0, 0, 16, 1, STONE_LIGHT)
    tile_rect(5, 0, 15, 16, 1, STONE_DARK)
    tile_rect(5, 0, 7, 16, 1, STONE_DARK)
    tile_rect(5, 8, 0, 1, 8, STONE_DARK)
    tile_rect(5, 4, 7, 1, 9, STONE_DARK)
    # Crack
    for pos in [(6, 2), (7, 3), (7, 4), (8, 5), (8, 6), (9, 9), (10, 10), (10, 11), (11, 12)]:
        tile_pixel(5, pos[0], pos[1], DARK_GRAY)

    # Tile 6: Mossy stone
    fill_rect(img, W, H, 6 * TS, 0, TS, TS, STONE)
    tile_rect(6, 0, 0, 16, 1, STONE_LIGHT)
    tile_rect(6, 0, 15, 16, 1, STONE_DARK)
    tile_rect(6, 0, 7, 16, 1, STONE_DARK)
    # Moss patches
    for pos in [(2, 1), (3, 1), (3, 2), (4, 2), (10, 0), (11, 0), (11, 1), (12, 1)]:
        tile_pixel(6, pos[0], pos[1], MOSS)
    for pos in [(1, 8), (2, 8), (2, 9), (13, 8), (14, 8), (14, 9)]:
        tile_pixel(6, pos[0], pos[1], DARK_GREEN)
    for pos in [(3, 0), (11, 0), (2, 8), (14, 8)]:
        tile_pixel(6, pos[0], pos[1], LIGHT_GREEN)

    # Tile 8-11: Water animation (4 frames)
    for frame in range(4):
        tid = 8 + frame
        fill_rect(img, W, H, (tid % COLS) * TS, (tid // COLS) * TS, TS, TS, WATER)
        # Lighter top
        tile_rect(tid, 0, 0, 16, 3, WATER_LIGHT)
        # Wave pattern (shifted per frame)
        import math
        for x in range(16):
            wave_y = int(1.5 + 1.5 * math.sin((x + frame * 4) * 0.6))
            tile_pixel(tid, x, wave_y, WATER_SURFACE)
            if wave_y + 1 < TS:
                tile_pixel(tid, x, wave_y + 1, WATER_LIGHT)
        # Depth gradient
        for y in range(10, 16):
            for x in range(16):
                if (x + y + frame) % 5 == 0:
                    tile_pixel(tid, x, y, WATER_DEEP)

    # Tile 12: Bridge plank
    fill_rect(img, W, H, 12 % COLS * TS, 12 // COLS * TS, TS, TS, LIGHT_BROWN)
    tile_rect(12, 0, 0, 16, 1, BROWN)
    tile_rect(12, 0, 15, 16, 1, DARK_BROWN)
    tile_rect(12, 7, 0, 2, 16, BROWN)  # center plank line
    # Wood grain
    for y in [3, 6, 10, 13]:
        tile_pixel(12, 3, y, BROWN)
        tile_pixel(12, 11, y, BROWN)
    # Nails
    tile_pixel(12, 2, 2, GRAY)
    tile_pixel(12, 13, 2, GRAY)
    tile_pixel(12, 2, 13, GRAY)
    tile_pixel(12, 13, 13, GRAY)

    # Tile 14: Thorn
    fill_rect(img, W, H, 14 % COLS * TS, 14 // COLS * TS, TS, TS, T)
    # Spiky thorns
    spine_color = (80, 30, 50, 255)
    tip_color = (160, 40, 60, 255)
    for bx in [2, 7, 12]:
        for y in range(4, 16):
            tile_pixel(14, bx, y, spine_color)
            tile_pixel(14, bx + 1, y, spine_color)
        # Tips
        tile_pixel(14, bx, 3, tip_color)
        tile_pixel(14, bx + 1, 2, tip_color)
        tile_pixel(14, bx, 1, tip_color)
        # Side thorns
        tile_pixel(14, bx - 1, 6, tip_color)
        tile_pixel(14, bx + 2, 9, tip_color)
        tile_pixel(14, bx - 1, 12, tip_color)

    # Tile 16: Red flower
    ox = (16 % COLS) * TS
    oy = (16 // COLS) * TS
    # Stem
    for y in range(8, 16):
        set_pixel(img, W, H, ox + 7, oy + y, GREEN)
        set_pixel(img, W, H, ox + 8, oy + y, GREEN)
    # Leaves
    set_pixel(img, W, H, ox + 5, oy + 11, LIGHT_GREEN)
    set_pixel(img, W, H, ox + 6, oy + 10, LIGHT_GREEN)
    set_pixel(img, W, H, ox + 10, oy + 12, LIGHT_GREEN)
    set_pixel(img, W, H, ox + 9, oy + 11, LIGHT_GREEN)
    # Petals
    for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, -1), (-1, 1), (1, 1)]:
        set_pixel(img, W, H, ox + 7 + dx, oy + 5 + dy, RED)
    set_pixel(img, W, H, ox + 7, oy + 5, YELLOW)  # center
    set_pixel(img, W, H, ox + 8, oy + 5, YELLOW)

    # Tile 17: Blue flower
    ox = (17 % COLS) * TS
    oy = (17 // COLS) * TS
    for y in range(9, 16):
        set_pixel(img, W, H, ox + 8, oy + y, GREEN)
    for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, -1), (-1, 1), (1, 1)]:
        set_pixel(img, W, H, ox + 8 + dx, oy + 6 + dy, LIGHT_BLUE)
    set_pixel(img, W, H, ox + 8, oy + 6, WHITE)

    # Tile 18: Mushroom
    ox = (18 % COLS) * TS
    oy = (18 // COLS) * TS
    # Stem
    fill_rect(img, W, H, ox + 6, oy + 8, 4, 8, WHITE)
    fill_rect(img, W, H, ox + 7, oy + 8, 2, 8, (220, 220, 225, 255))
    # Cap
    for x in range(4, 12):
        for y in range(3, 8):
            dx = x - 8
            dy = y - 6
            if dx * dx + dy * dy <= 18:
                set_pixel(img, W, H, ox + x, oy + y, RED)
    # Spots
    set_pixel(img, W, H, ox + 6, oy + 4, WHITE)
    set_pixel(img, W, H, ox + 9, oy + 5, WHITE)
    set_pixel(img, W, H, ox + 7, oy + 6, WHITE)

    # Tile 19: Crystal
    ox = (19 % COLS) * TS
    oy = (19 // COLS) * TS
    crystal_body = (100, 180, 240, 255)
    crystal_light = (180, 220, 255, 255)
    crystal_dark = (50, 100, 180, 255)
    # Main crystal shape
    for y in range(2, 14):
        w = max(1, 4 - abs(y - 8) // 2)
        for x in range(8 - w, 8 + w):
            set_pixel(img, W, H, ox + x, oy + y, crystal_body)
    # Highlight edge
    for y in range(3, 12):
        set_pixel(img, W, H, ox + 6, oy + y, crystal_light)
    # Dark edge
    for y in range(4, 13):
        set_pixel(img, W, H, ox + 9, oy + y, crystal_dark)
    # Tip
    set_pixel(img, W, H, ox + 7, oy + 2, crystal_light)
    set_pixel(img, W, H, ox + 8, oy + 2, crystal_light)
    # Sparkle
    set_pixel(img, W, H, ox + 6, oy + 4, WHITE)

    # Tile 20-21: Torch (2 animation frames)
    for frame in range(2):
        tid = 20 + frame
        ox = (tid % COLS) * TS
        oy = (tid // COLS) * TS
        # Stick
        fill_rect(img, W, H, ox + 7, oy + 6, 2, 10, DARK_BROWN)
        # Bracket
        fill_rect(img, W, H, ox + 5, oy + 6, 6, 2, GRAY)
        # Flame
        flame_orange = (255, 160, 40, 255)
        flame_yellow = (255, 230, 80, 255)
        flame_red = (220, 80, 30, 255)
        if frame == 0:
            for y in range(1, 6):
                w = max(1, 3 - abs(y - 3))
                for x in range(8 - w, 8 + w):
                    c = flame_yellow if y < 3 else flame_orange
                    set_pixel(img, W, H, ox + x, oy + y, c)
            set_pixel(img, W, H, ox + 7, oy + 1, flame_red)
            set_pixel(img, W, H, ox + 8, oy + 0, flame_yellow)
        else:
            for y in range(1, 6):
                w = max(1, 3 - abs(y - 3))
                for x in range(7 - w, 7 + w + 1):
                    c = flame_yellow if y < 3 else flame_orange
                    set_pixel(img, W, H, ox + x, oy + y, c)
            set_pixel(img, W, H, ox + 8, oy + 1, flame_red)
            set_pixel(img, W, H, ox + 7, oy + 0, flame_yellow)

    # Tile 22: Grass blade (decoration overlay)
    ox = (22 % COLS) * TS
    oy = (22 // COLS) * TS
    for bx, h in [(3, 7), (6, 9), (10, 8), (13, 6)]:
        for y in range(16 - h, 16):
            c = LIGHT_GREEN if y < 16 - h + 2 else GREEN
            set_pixel(img, W, H, ox + bx, oy + y, c)
        set_pixel(img, W, H, ox + bx, oy + 16 - h - 1, BRIGHT_GREEN)

    # Tile 23: Bush
    ox = (23 % COLS) * TS
    oy = (23 // COLS) * TS
    for y in range(6, 15):
        for x in range(2, 14):
            dx = x - 8
            dy = y - 10
            if dx * dx / 36 + dy * dy / 16 < 1:
                c = GREEN if (x + y) % 3 != 0 else DARK_GREEN
                set_pixel(img, W, H, ox + x, oy + y, c)
    # Highlights
    for pos in [(5, 7), (8, 6), (11, 8)]:
        set_pixel(img, W, H, ox + pos[0], oy + pos[1], LIGHT_GREEN)

    # Tiles 24-27: Tree trunk sections
    # 24: trunk base
    fill_rect(img, W, H, (24 % COLS) * TS, (24 // COLS) * TS, TS, TS, T)
    ox = (24 % COLS) * TS
    oy = (24 // COLS) * TS
    fill_rect(img, W, H, ox + 5, oy, 6, 16, BROWN)
    fill_rect(img, W, H, ox + 6, oy, 4, 16, LIGHT_BROWN)
    # Bark texture
    for pos in [(6, 3), (8, 7), (7, 11), (9, 14)]:
        set_pixel(img, W, H, ox + pos[0], oy + pos[1], DARK_BROWN)
    # Roots
    fill_rect(img, W, H, ox + 3, oy + 13, 2, 3, BROWN)
    fill_rect(img, W, H, ox + 11, oy + 14, 2, 2, BROWN)

    # 25: trunk middle
    fill_rect(img, W, H, (25 % COLS) * TS, (25 // COLS) * TS, TS, TS, T)
    ox = (25 % COLS) * TS
    oy = (25 // COLS) * TS
    fill_rect(img, W, H, ox + 5, oy, 6, 16, BROWN)
    fill_rect(img, W, H, ox + 6, oy, 4, 16, LIGHT_BROWN)
    for pos in [(7, 2), (9, 6), (6, 10), (8, 14)]:
        set_pixel(img, W, H, ox + pos[0], oy + pos[1], DARK_BROWN)
    # Branch stubs
    fill_rect(img, W, H, ox + 3, oy + 4, 2, 2, BROWN)
    fill_rect(img, W, H, ox + 11, oy + 9, 2, 2, BROWN)

    # 26: Canopy (dense leaves)
    fill_rect(img, W, H, (26 % COLS) * TS, (26 // COLS) * TS, TS, TS, T)
    ox = (26 % COLS) * TS
    oy = (26 // COLS) * TS
    for y in range(16):
        for x in range(16):
            dx = x - 8
            dy = y - 10
            if dx * dx / 64 + dy * dy / 36 < 1:
                c = GREEN if (x * 3 + y * 7) % 5 != 0 else DARK_GREEN
                if (x + y) % 7 == 0:
                    c = LIGHT_GREEN
                set_pixel(img, W, H, ox + x, oy + y, c)

    # 27: Canopy top
    fill_rect(img, W, H, (27 % COLS) * TS, (27 // COLS) * TS, TS, TS, T)
    ox = (27 % COLS) * TS
    oy = (27 // COLS) * TS
    for y in range(16):
        for x in range(16):
            dx = x - 8
            dy = y - 6
            if dx * dx / 64 + dy * dy / 36 < 1:
                c = GREEN if (x * 3 + y * 7) % 5 != 0 else DARK_GREEN
                if (x + y) % 7 == 0:
                    c = LIGHT_GREEN
                if y < 4 and (x + y) % 3 == 0:
                    c = BRIGHT_GREEN
                set_pixel(img, W, H, ox + x, oy + y, c)

    write_png("tileset.png", W, H, img)


# ──────────────────────────────────────────────
#  Background layers (256 wide x 200 tall each)
# ──────────────────────────────────────────────
def generate_bg_far():
    """Far background: sky gradient with clouds and stars."""
    import math
    W, H = 256, 200
    img = make_image(W, H)

    # Sky gradient
    for y in range(H):
        t = y / H
        r = int(30 + t * 80)
        g = int(20 + t * 100)
        b = int(80 + t * 100)
        for x in range(W):
            set_pixel(img, W, H, x, y, (r, g, b, 255))

    # Stars
    import random
    random.seed(42)
    for _ in range(60):
        sx = random.randint(0, W - 1)
        sy = random.randint(0, H // 2)
        b = random.randint(180, 255)
        set_pixel(img, W, H, sx, sy, (b, b, b + 20 if b + 20 < 256 else 255, 255))

    # Moon
    cx, cy, r = 200, 30, 14
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                # Exclude inner circle for crescent
                if (dx - 4) ** 2 + dy * dy > (r - 2) ** 2:
                    b = 220 + min(35, abs(dx) * 3)
                    set_pixel(img, W, H, cx + dx, cy + dy, (b, b, min(255, b + 15), 255))
    # Moon glow
    for dy in range(-r - 4, r + 5):
        for dx in range(-r - 4, r + 5):
            d = math.sqrt(dx * dx + dy * dy)
            if r < d < r + 5:
                a = int(60 * (1 - (d - r) / 5))
                px, py = cx + dx, cy + dy
                if 0 <= px < W and 0 <= py < H:
                    er, eg, eb, ea = img[py * W + px]
                    nr = min(255, er + a)
                    ng = min(255, eg + a)
                    nb = min(255, eb + a)
                    set_pixel(img, W, H, px, py, (nr, ng, nb, 255))

    # Clouds
    def draw_cloud(cx, cy, scale):
        for dy in range(-3 * scale, 3 * scale + 1):
            for dx in range(-6 * scale, 6 * scale + 1):
                # Multi-blob cloud shape
                d1 = (dx + 2 * scale) ** 2 / (3 * scale) ** 2 + dy ** 2 / (2 * scale) ** 2
                d2 = (dx - 2 * scale) ** 2 / (3 * scale) ** 2 + dy ** 2 / (2 * scale) ** 2
                d3 = dx ** 2 / (4 * scale) ** 2 + (dy + scale) ** 2 / (2 * scale) ** 2
                if d1 < 1 or d2 < 1 or d3 < 1:
                    px, py = cx + dx, cy + dy
                    if 0 <= px < W and 0 <= py < H:
                        a = 60
                        set_pixel(img, W, H, px, py, (200, 200, 220, a))

    draw_cloud(60, 40, 2)
    draw_cloud(160, 55, 3)
    draw_cloud(40, 80, 2)

    write_png("bg_far.png", W, H, img)


def generate_bg_mid():
    """Mid background: mountain/hill silhouettes."""
    import math
    W, H = 256, 200
    img = make_image(W, H)

    # Mountain silhouettes
    for x in range(W):
        # Layer 1: far mountains (darker)
        h1 = int(80 + 30 * math.sin(x * 0.02) + 15 * math.sin(x * 0.05 + 1.2) +
                  8 * math.sin(x * 0.11 + 0.5))
        for y in range(H - h1, H):
            t = (y - (H - h1)) / max(1, h1)
            r = int(25 + t * 10)
            g = int(30 + t * 15)
            b = int(50 + t * 20)
            set_pixel(img, W, H, x, y, (r, g, b, 255))

        # Layer 2: nearer hills (slightly lighter)
        h2 = int(50 + 20 * math.sin(x * 0.035 + 2.0) + 10 * math.sin(x * 0.08 + 0.8))
        for y in range(H - h2, H):
            t = (y - (H - h2)) / max(1, h2)
            r = int(35 + t * 15)
            g = int(50 + t * 20)
            b = int(40 + t * 15)
            set_pixel(img, W, H, x, y, (r, g, b, 255))

    # Tree silhouettes on hills
    import random
    random.seed(123)
    for _ in range(20):
        tx = random.randint(0, W - 1)
        h2 = int(50 + 20 * math.sin(tx * 0.035 + 2.0) + 10 * math.sin(tx * 0.08 + 0.8))
        ty = H - h2
        tree_h = random.randint(8, 16)
        tree_c = (20 + random.randint(0, 15), 35 + random.randint(0, 20),
                  25 + random.randint(0, 15), 255)
        # Trunk
        for y in range(ty - tree_h, ty):
            set_pixel(img, W, H, tx, y, tree_c)
        # Canopy
        canopy_r = random.randint(3, 6)
        for dy in range(-canopy_r, 1):
            for dx in range(-canopy_r, canopy_r + 1):
                if dx * dx + dy * dy <= canopy_r * canopy_r:
                    px, py = tx + dx, ty - tree_h + dy
                    if 0 <= px < W and 0 <= py < H:
                        set_pixel(img, W, H, px, py, tree_c)

    write_png("bg_mid.png", W, H, img)


def generate_bg_near():
    """Near background: detailed trees and foliage."""
    import math
    import random
    random.seed(456)
    W, H = 256, 200
    img = make_image(W, H)

    # Ground
    for x in range(W):
        ground_y = int(160 + 5 * math.sin(x * 0.04) + 3 * math.sin(x * 0.1))
        for y in range(ground_y, H):
            t = (y - ground_y) / max(1, H - ground_y)
            r = int(40 + t * 20)
            g = int(70 + t * 10)
            b = int(35 + t * 10)
            set_pixel(img, W, H, x, y, (r, g, b, 255))
        # Grass blades on top
        if x % 3 == 0:
            for dy in range(0, random.randint(2, 5)):
                c = (60 + random.randint(0, 40), 120 + random.randint(0, 60),
                     40 + random.randint(0, 20), 255)
                set_pixel(img, W, H, x, ground_y - dy, c)

    # Trees with detail
    tree_positions = [20, 55, 90, 130, 170, 210, 240]
    for tx in tree_positions:
        ground_y = int(160 + 5 * math.sin(tx * 0.04))
        trunk_h = random.randint(30, 50)
        trunk_w = random.randint(3, 5)

        # Trunk
        for y in range(ground_y - trunk_h, ground_y):
            for dx in range(-(trunk_w // 2), trunk_w // 2 + 1):
                bark = (90 + random.randint(-10, 10), 60 + random.randint(-10, 10),
                        35 + random.randint(-5, 5), 255)
                set_pixel(img, W, H, tx + dx, y, bark)

        # Canopy (multiple overlapping circles)
        canopy_y = ground_y - trunk_h
        for _ in range(random.randint(4, 7)):
            cx = tx + random.randint(-8, 8)
            cy = canopy_y + random.randint(-10, 5)
            cr = random.randint(6, 12)
            for dy in range(-cr, cr + 1):
                for dx in range(-cr, cr + 1):
                    if dx * dx + dy * dy <= cr * cr:
                        px, py = cx + dx, cy + dy
                        if 0 <= px < W and 0 <= py < H:
                            g = 80 + random.randint(0, 60)
                            leaf = (30 + random.randint(0, 20), g,
                                    25 + random.randint(0, 15), 220)
                            set_pixel(img, W, H, px, py, leaf)

    # Bushes
    for _ in range(12):
        bx = random.randint(0, W - 1)
        ground_y = int(160 + 5 * math.sin(bx * 0.04))
        by = ground_y - random.randint(2, 5)
        br = random.randint(4, 8)
        for dy in range(-br, br // 2 + 1):
            for dx in range(-br, br + 1):
                if dx * dx / (br * br) + dy * dy / ((br // 2 + 1) ** 2) < 1:
                    px, py = bx + dx, by + dy
                    if 0 <= px < W and 0 <= py < H:
                        g = 70 + random.randint(0, 50)
                        set_pixel(img, W, H, px, py,
                                  (25 + random.randint(0, 15), g,
                                   20 + random.randint(0, 10), 200))

    write_png("bg_near.png", W, H, img)


# ──────────────────────────────────────────────
#  Items: 12x12 per frame, 4 frames (gem spin)
# ──────────────────────────────────────────────
def generate_items():
    FW, FH = 12, 12
    COLS = 4
    W, H = FW * COLS, FH
    img = make_image(W, H)

    gem_colors = [
        ((50, 200, 80, 255), (100, 240, 120, 255), (30, 140, 50, 255)),    # green
        ((50, 200, 80, 255), (100, 240, 120, 255), (30, 140, 50, 255)),    # green
        ((50, 200, 80, 255), (100, 240, 120, 255), (30, 140, 50, 255)),    # green
        ((50, 200, 80, 255), (100, 240, 120, 255), (30, 140, 50, 255)),    # green
    ]

    widths = [5, 4, 3, 4]  # gem width per frame (spin effect)
    for frame in range(4):
        ox = frame * FW
        mid, light, dark = gem_colors[frame]
        hw = widths[frame]

        # Diamond shape
        for y in range(1, 11):
            if y <= 5:
                w = min(hw, y)
            else:
                w = min(hw, 11 - y)
            for dx in range(-w, w + 1):
                x = 6 + dx
                c = mid
                if dx < 0:
                    c = dark
                elif dx > 0:
                    c = light if y < 6 else mid
                if y <= 2 or y >= 9:
                    c = light
                set_pixel(img, W, H, ox + x, y, c)

        # Sparkle highlight
        set_pixel(img, W, H, ox + 5, 2, (255, 255, 255, 255))
        set_pixel(img, W, H, ox + 4, 3, (200, 255, 200, 200))

    write_png("items.png", W, H, img)


# ──────────────────────────────────────────────
#  Enemies: 16x16 per frame, 4 frames (slime)
# ──────────────────────────────────────────────
def generate_enemies():
    FW, FH = 16, 16
    COLS = 4
    W, H = FW * COLS, FH
    img = make_image(W, H)

    slime_body = (80, 180, 60, 255)
    slime_dark = (50, 120, 40, 255)
    slime_light = (120, 220, 100, 255)
    slime_eye_w = (240, 240, 250, 255)
    slime_pupil = (30, 30, 50, 255)

    squish_heights = [10, 8, 10, 12]  # animation: normal, squished, normal, stretched
    squish_widths = [12, 14, 12, 10]

    for frame in range(4):
        ox = frame * FW
        sh = squish_heights[frame]
        sw = squish_widths[frame]
        base_y = 15  # bottom of slime

        # Body (ellipse)
        for y in range(base_y - sh, base_y + 1):
            t = (y - (base_y - sh)) / max(1, sh)
            w = int(sw / 2 * (1 - (1 - t) ** 2) ** 0.5) if t < 0.7 else int(sw / 2 * ((1 - t) / 0.3) ** 0.5)
            if t > 0.9:
                w = int(sw / 2 * 0.8)
            for dx in range(-w, w + 1):
                x = 8 + dx
                if dx < -w // 3:
                    c = slime_dark
                elif dx > w // 3:
                    c = slime_light
                else:
                    c = slime_body
                set_pixel(img, W, H, ox + x, y, c)

        # Eyes
        eye_y = base_y - int(sh * 0.6)
        # Left eye
        set_pixel(img, W, H, ox + 5, eye_y, slime_eye_w)
        set_pixel(img, W, H, ox + 6, eye_y, slime_eye_w)
        set_pixel(img, W, H, ox + 5, eye_y + 1, slime_eye_w)
        set_pixel(img, W, H, ox + 6, eye_y + 1, slime_pupil)
        # Right eye
        set_pixel(img, W, H, ox + 9, eye_y, slime_eye_w)
        set_pixel(img, W, H, ox + 10, eye_y, slime_eye_w)
        set_pixel(img, W, H, ox + 10, eye_y + 1, slime_pupil)
        set_pixel(img, W, H, ox + 9, eye_y + 1, slime_eye_w)

        # Shine highlight
        set_pixel(img, W, H, ox + 4, eye_y - 2, slime_light)
        set_pixel(img, W, H, ox + 5, eye_y - 2, slime_light)

    write_png("enemies.png", W, H, img)


# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("Generating pixel art assets...")
    generate_player()
    generate_tileset()
    generate_bg_far()
    generate_bg_mid()
    generate_bg_near()
    generate_items()
    generate_enemies()
    print("Done! Assets saved to:", SCRIPT_DIR)
