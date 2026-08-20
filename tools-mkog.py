#!/usr/bin/env python3
"""Render the 1200x630 Open Graph card with no third-party libraries.

Pillow, pip and ImageMagick are all unavailable on this machine, so this
does the two jobs itself: rasterise TrueType glyph outlines, and write a
PNG. Only what the card needs is implemented -- simple and composite
glyphs, cmap format 4, nonzero winding fill with 3x3 supersampling.
"""

import struct
import zlib

FONT_DIR = "/usr/share/fonts/truetype/dejavu/"


# ─────────────────────────────────────────────────────────── TrueType ──
class Font:
    def __init__(self, path):
        self.data = open(path, "rb").read()
        self.tables = {}
        num = struct.unpack(">H", self.data[4:6])[0]
        for i in range(num):
            off = 12 + i * 16
            tag = self.data[off:off + 4].decode("latin-1")
            start, length = struct.unpack(">II", self.data[off + 8:off + 16])
            self.tables[tag] = (start, length)

        head = self.tables["head"][0]
        self.units_per_em = struct.unpack(">H", self.data[head + 18:head + 20])[0]
        self.loca_long = struct.unpack(">h", self.data[head + 50:head + 52])[0]

        maxp = self.tables["maxp"][0]
        self.num_glyphs = struct.unpack(">H", self.data[maxp + 4:maxp + 6])[0]

        self._load_loca()
        self._load_cmap()
        self._load_hmtx()

    def _load_loca(self):
        start, _ = self.tables["loca"]
        self.loca = []
        if self.loca_long:
            for i in range(self.num_glyphs + 1):
                self.loca.append(struct.unpack(">I", self.data[start + i * 4:start + i * 4 + 4])[0])
        else:
            for i in range(self.num_glyphs + 1):
                self.loca.append(struct.unpack(">H", self.data[start + i * 2:start + i * 2 + 2])[0] * 2)

    def _load_cmap(self):
        start, _ = self.tables["cmap"]
        n = struct.unpack(">H", self.data[start + 2:start + 4])[0]
        sub = None
        for i in range(n):
            off = start + 4 + i * 8
            pid, eid, so = struct.unpack(">HHI", self.data[off:off + 8])
            if (pid, eid) in ((3, 1), (0, 3), (0, 4), (3, 10)):
                sub = start + so
                break
        fmt = struct.unpack(">H", self.data[sub:sub + 2])[0]
        assert fmt == 4, f"cmap format {fmt} not supported"
        segx2 = struct.unpack(">H", self.data[sub + 6:sub + 8])[0]
        seg = segx2 // 2
        base = sub + 14
        ends = struct.unpack(f">{seg}H", self.data[base:base + segx2])
        base += segx2 + 2
        starts = struct.unpack(f">{seg}H", self.data[base:base + segx2])
        base += segx2
        deltas = struct.unpack(f">{seg}h", self.data[base:base + segx2])
        base += segx2
        range_off_pos = base
        range_offs = struct.unpack(f">{seg}H", self.data[base:base + segx2])
        self._cmap = (ends, starts, deltas, range_offs, range_off_pos)

    def glyph_id(self, ch):
        ends, starts, deltas, range_offs, rop = self._cmap
        c = ord(ch)
        for i, e in enumerate(ends):
            if c <= e:
                if c < starts[i]:
                    return 0
                if range_offs[i] == 0:
                    return (c + deltas[i]) & 0xFFFF
                pos = rop + i * 2 + range_offs[i] + (c - starts[i]) * 2
                g = struct.unpack(">H", self.data[pos:pos + 2])[0]
                return (g + deltas[i]) & 0xFFFF if g else 0
        return 0

    def _load_hmtx(self):
        hhea = self.tables["hhea"][0]
        self.num_hmetrics = struct.unpack(">H", self.data[hhea + 34:hhea + 36])[0]
        self.hmtx = self.tables["hmtx"][0]

    def advance(self, gid):
        i = min(gid, self.num_hmetrics - 1)
        return struct.unpack(">H", self.data[self.hmtx + i * 4:self.hmtx + i * 4 + 2])[0]

    def contours(self, gid, depth=0):
        """Return contours as lists of (x, y, on_curve) in font units."""
        glyf = self.tables["glyf"][0]
        start, end = self.loca[gid], self.loca[gid + 1]
        if start == end:
            return []
        d = self.data
        off = glyf + start
        ncont = struct.unpack(">h", d[off:off + 2])[0]

        if ncont < 0:                                    # composite
            if depth > 4:
                return []
            out = []
            p = off + 10
            while True:
                flags, gi = struct.unpack(">HH", d[p:p + 4])
                p += 4
                if flags & 1:
                    a1, a2 = struct.unpack(">hh", d[p:p + 4]); p += 4
                else:
                    a1, a2 = struct.unpack(">bb", d[p:p + 2]); p += 2
                sx = sy = 1.0
                if flags & 8:
                    sx = sy = struct.unpack(">h", d[p:p + 2])[0] / 16384.0; p += 2
                elif flags & 0x40:
                    sx = struct.unpack(">h", d[p:p + 2])[0] / 16384.0
                    sy = struct.unpack(">h", d[p + 2:p + 4])[0] / 16384.0; p += 4
                elif flags & 0x80:
                    p += 8
                dx, dy = (a1, a2) if flags & 2 else (0, 0)
                for c in self.contours(gi, depth + 1):
                    out.append([(x * sx + dx, y * sy + dy, on) for x, y, on in c])
                if not flags & 0x20:
                    break
            return out

        p = off + 10
        end_pts = struct.unpack(f">{ncont}H", d[p:p + ncont * 2])
        p += ncont * 2
        npts = end_pts[-1] + 1
        ins = struct.unpack(">H", d[p:p + 2])[0]
        p += 2 + ins

        flags = []
        while len(flags) < npts:
            f = d[p]; p += 1
            flags.append(f)
            if f & 8:
                r = d[p]; p += 1
                flags.extend([f] * r)
        flags = flags[:npts]

        xs, v = [], 0
        for f in flags:
            if f & 2:
                dx = d[p]; p += 1
                v += dx if f & 16 else -dx
            elif not f & 16:
                v += struct.unpack(">h", d[p:p + 2])[0]; p += 2
            xs.append(v)
        ys, v = [], 0
        for f in flags:
            if f & 4:
                dy = d[p]; p += 1
                v += dy if f & 32 else -dy
            elif not f & 32:
                v += struct.unpack(">h", d[p:p + 2])[0]; p += 2
            ys.append(v)

        out, s = [], 0
        for e in end_pts:
            out.append([(xs[i], ys[i], bool(flags[i] & 1)) for i in range(s, e + 1)])
            s = e + 1
        return out


def glyph_polys(font, gid, scale, ox, oy):
    """Flatten a glyph's quadratic contours into polylines in pixel space."""
    polys = []
    for c in font.contours(gid):
        if not c:
            continue
        pts = []
        # synthesise on-curve midpoints so every segment has a real start
        n = len(c)
        expanded = []
        for i, (x, y, on) in enumerate(c):
            if not on and not c[i - 1][2]:
                px, py, _ = c[i - 1]
                expanded.append(((x + px) / 2, (y + py) / 2, True))
            expanded.append((x, y, on))
        if not expanded[0][2]:
            expanded.insert(0, expanded[-1])

        i, m = 0, len(expanded)
        cur = (expanded[0][0], expanded[0][1])
        pts.append(cur)
        i = 1
        while i <= m:
            x, y, on = expanded[i % m]
            if on:
                cur = (x, y)
                pts.append(cur)
                i += 1
            else:
                nx, ny, _ = expanded[(i + 1) % m]
                x0, y0 = cur
                for t in range(1, 9):
                    tt = t / 8
                    u = 1 - tt
                    pts.append((u * u * x0 + 2 * u * tt * x + tt * tt * nx,
                                u * u * y0 + 2 * u * tt * y + tt * tt * ny))
                cur = (nx, ny)
                i += 2
        polys.append([(ox + px * scale, oy - py * scale) for px, py in pts])
    return polys


# ──────────────────────────────────────────────────────────── canvas ──
class Canvas:
    def __init__(self, w, h, bg):
        self.w, self.h = w, h
        self.px = bytearray()
        for _ in range(h):
            self.px.extend(bytes(bg) * w)

    def rect(self, x0, y0, x1, y1, color):
        for y in range(max(0, int(y0)), min(self.h, int(y1))):
            row = y * self.w * 3
            for x in range(max(0, int(x0)), min(self.w, int(x1))):
                i = row + x * 3
                self.px[i:i + 3] = bytes(color)

    def fill_polys(self, polys, color, ss=3):
        """Nonzero-winding scanline fill, supersampled ss x ss for AA."""
        edges = []
        for poly in polys:
            for i in range(len(poly)):
                x0, y0 = poly[i]
                x1, y1 = poly[(i + 1) % len(poly)]
                if y0 != y1:
                    edges.append((x0, y0, x1, y1))
        if not edges:
            return
        miny = max(0, int(min(min(e[1], e[3]) for e in edges)) - 1)
        maxy = min(self.h, int(max(max(e[1], e[3]) for e in edges)) + 2)
        minx = max(0, int(min(min(e[0], e[2]) for e in edges)) - 1)
        maxx = min(self.w, int(max(max(e[0], e[2]) for e in edges)) + 2)
        if minx >= maxx or miny >= maxy:
            return

        width = maxx - minx
        cov = [[0] * width for _ in range(maxy - miny)]
        for sy in range((maxy - miny) * ss):
            yy = miny + (sy + 0.5) / ss
            xs = []
            for x0, y0, x1, y1 in edges:
                if (y0 <= yy < y1) or (y1 <= yy < y0):
                    t = (yy - y0) / (y1 - y0)
                    xs.append((x0 + t * (x1 - x0), 1 if y1 > y0 else -1))
            if not xs:
                continue
            xs.sort()
            wind = 0
            row = cov[sy // ss]
            for i in range(len(xs) - 1):
                wind += xs[i][1]
                if wind != 0:
                    xa, xb = xs[i][0], xs[i + 1][0]
                    for sx in range(int((xa - minx) * ss), int((xb - minx) * ss) + 1):
                        cx = sx / ss
                        if 0 <= cx < width and xa <= minx + cx + 0.5 / ss <= xb:
                            row[int(cx)] += 1

        full = ss * ss
        for j, row in enumerate(cov):
            y = miny + j
            base = y * self.w * 3
            for i, c in enumerate(row):
                if not c:
                    continue
                a = min(1.0, c / full)
                x = minx + i
                k = base + x * 3
                for ch in range(3):
                    self.px[k + ch] = int(self.px[k + ch] * (1 - a) + color[ch] * a)

    def text(self, font, s, size, x, y, color, tracking=0.0):
        scale = size / font.units_per_em
        pen = x
        for ch in s:
            gid = font.glyph_id(ch)
            if ch != " ":
                polys = glyph_polys(font, gid, scale, pen, y)
                if polys:
                    self.fill_polys(polys, color)
            pen += font.advance(gid) * scale + tracking
        return pen

    def width(self, font, s, size, tracking=0.0):
        scale = size / font.units_per_em
        return sum(font.advance(font.glyph_id(c)) * scale + tracking for c in s)

    def write_png(self, path):
        raw = bytearray()
        stride = self.w * 3
        for y in range(self.h):
            raw.append(0)
            raw.extend(self.px[y * stride:(y + 1) * stride])
        def chunk(tag, data):
            c = struct.pack(">I", len(data)) + tag + data
            return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
               + chunk(b"IEND", b""))
        open(path, "wb").write(png)
        return len(png)


# ────────────────────────────────────────────────────────────── card ──
INK        = (0x16, 0x1b, 0x2e)
PAPER      = (0xfb, 0xfc, 0xff)
ACCENT     = (0x4d, 0x86, 0xff)
ACCENT_DIM = (0xa7, 0x8b, 0xfa)
MUTED      = (0x9a, 0xa5, 0xbf)

W, H = 1200, 630
c = Canvas(W, H, INK)

serif = Font(FONT_DIR + "DejaVuSerif.ttf")
sans  = Font(FONT_DIR + "DejaVuSans.ttf")
mono  = Font(FONT_DIR + "DejaVuSansMono.ttf")

# accent rule down the left edge, echoing the site's position bars
c.rect(0, 0, 10, H, ACCENT)

# faint grid, matching the site's texture overlay
for gx in range(90, W, 48):
    c.rect(gx, 0, gx + 1, H, (0x1b, 0x21, 0x36))
for gy in range(0, H, 48):
    c.rect(90, gy, W, gy + 1, (0x1b, 0x21, 0x36))

M = 90
c.text(mono, "CARNEGIE MELLON UNIVERSITY  ·  TRAFFIQURE", 19, M, 132, ACCENT_DIM, tracking=2.4)
c.text(serif, "Bin Gui", 104, M - 6, 250, PAPER)
c.rect(M, 286, M + 64, 290, ACCENT)
c.text(sans, "Senior System Scientist", 40, M, 360, PAPER)
c.text(sans, "Chief Data Scientist, TraffiQure Technologies", 30, M, 412, MUTED)
c.text(mono, "TRANSPORTATION AI   ·   NETWORK MODELING   ·   COMPLEX SYSTEMS",
       17, M, 520, ACCENT_DIM, tracking=1.6)
c.text(mono, "binguidata.github.io", 20, M, 566, MUTED, tracking=1.0)

size = c.write_png("og-card.png")
print(f"og-card.png written: {W}x{H}, {size:,} bytes")
