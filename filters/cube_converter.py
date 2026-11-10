"""Convert standard .cube 3D LUT files into ZV-E10M2 Creative Look ("LUT 直出")
hardware tables (cpapp-b.bin 129-point tone curves, unit-02a4000d.bin 16-hue
white-preserving 3x3 matrices, unit-02a40001.bin cc1 chroma, unit-02a40007.bin
CP 9x9x5 3D YCbCr LUT, and AP 17^3 LUT001.LUT).
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path

ST_SLOT6 = [
    0, 1049, 2097, 3146, 4195, 5243, 6292, 7341, 8390, 9438, 10487, 11536,
    12584, 13633, 14674, 15690, 16682, 17651, 18600, 19530, 20443, 21339,
    22220, 23086, 23938, 24778, 25604, 26419, 27222, 28015, 28796, 29568,
    30329, 31081, 31824, 32557, 33282, 33998, 34706, 35406, 36098, 36782,
    37459, 38128, 38790, 39445, 40093, 40734, 41369, 41996, 42618, 43233,
    43842, 44445, 45042, 45633, 46218, 46797, 47371, 47939, 48502, 49059,
    49611, 50158, 50700, 52816, 54855, 56821, 58717, 60548, 62315, 64022,
    65672, 67267, 68809, 70302, 71746, 73144, 74498, 75810, 77081, 81791,
    85969, 89692, 93021, 96010, 98704, 101138, 103346, 105355, 107186,
    108861, 110397, 111808, 113107, 114306, 115414, 116441, 117394, 118279,
    119104, 119873, 120591, 121262, 121891, 123034, 124043, 124938, 125735,
    126448, 127087, 127661, 128180, 128649, 129074, 129461, 129813, 130135,
    130429, 130699, 130946, 130946, 130946, 130946, 130946, 130946, 130946,
    130946, 130946,
]

ST_CC1 = [
    [-207, -269, -196, -51, 405, 563, 563, 506],
    [12, 0, -156, -27, 2, -90, 0, -81],
    [-13, 54, 11, -1, 30, -217, 0, -131],
]

ST_B13 = [
    [
        [60, 26, -73, 8, -280, 129], [35, -50, -68, 15, -124, 119],
        [-5, -113, -42, -4, -2, 62], [66, -134, 63, -185, 47, -22],
        [59, -160, 44, -186, -76, 18], [52, -177, 35, -136, -43, 98],
        [157, -135, 71, -106, -69, 97], [141, -96, 33, -135, -1, 149],
        [215, -257, -35, -29, 44, 195], [200, -286, -76, -129, 23, 128],
        [225, -251, -130, -75, -79, 225], [225, -234, -144, -61, -102, 225],
        [206, -220, -151, -52, -144, 142], [169, -209, -147, -52, -140, 144],
        [172, -111, -80, -68, -236, 184], [160, 70, -159, 108, -236, 134],
    ],
    [
        [113, -21, -270, 154, -151, 8], [42, -17, -97, 154, 50, -71],
        [13, -42, -60, 152, 155, -22], [34, -134, -79, 108, 171, -87],
        [-56, -82, 72, 84, 20, 27], [57, -136, 39, 150, -34, 206],
        [168, -100, 55, 67, -77, 183], [149, -132, -37, 146, -5, 146],
        [225, -300, -29, 130, 33, 187], [225, -268, -34, -23, -110, 204],
        [205, -233, -39, 28, -56, 225], [211, -205, -86, 93, -69, 155],
        [181, -144, -179, 128, -130, 162], [163, -161, -132, 154, -235, 154],
        [153, -50, -162, 154, -260, 161], [96, 95, -307, 143, -100, 76],
    ],
    [
        [51, 39, -48, 149, 80, -126], [225, -103, 30, 95, -11, -171],
        [225, -45, -36, 36, 76, -196], [167, 14, -20, 100, 144, -137],
        [187, -82, 24, 6, 7, 124], [192, -163, -34, 116, 34, 225],
        [198, -40, 83, 73, 13, 168], [199, -5, 130, 38, 56, 131],
        [224, -167, -3, 135, 97, 217], [225, -126, -12, 27, 27, 217],
        [225, -201, 88, 15, 51, 225], [100, -203, 121, 41, 61, 96],
        [139, -176, -25, 70, 137, 105], [143, 48, -71, 136, 101, 73],
        [118, 96, 75, 16, 11, 105], [5, 78, 57, 62, 27, 140],
    ],
]

CP_3DLUT_Y_GRID = (0, 64, 128, 192, 256)
CP_3DLUT_C_GRID = (-128, -96, -64, -32, 0, 32, 64, 96, 128)
CP_3DLUT_GAMMA_TAB = (
    0, 2, 3, 4, 6, 7, 9, 10, 12, 13, 15, 16, 18, 19, 21, 23, 24, 26, 28, 29, 31, 33, 35, 37, 39, 41, 43,
    44, 47, 49, 51, 53, 55, 57, 59, 61, 64, 66, 68, 71, 73, 76, 78, 81, 83, 86, 88, 91, 94, 96, 99, 102,
    105, 108, 111, 114, 117, 120, 123, 126, 129, 133, 136, 140, 143, 146, 150, 154, 157, 161, 165, 169,
    172, 176, 180, 184, 189, 193, 197, 201, 206, 210, 215, 219, 224, 228, 233, 238, 243, 248, 253, 258,
    263, 269, 274, 280, 285, 291, 297, 302, 308, 314, 320, 326, 333, 339, 346, 352, 359, 365, 372, 379,
    386, 393, 401, 408, 416, 423, 431, 439, 447, 455, 463, 471, 480, 488, 497, 506, 512,
)
CP_3DLUT_INDEX_MAP = (
    0, 75, 1, 76, 2, 77, 3, 78, 4, 135, 195, 136, 196, 137, 197, 138, 198, 139, 5, 79, 6, 80, 7, 81, 8,
    82, 9, 140, 199, 141, 200, 142, 201, 143, 202, 144, 10, 83, 11, 84, 12, 85, 13, 86, 14, 145, 203,
    146, 204, 147, 205, 148, 206, 149, 15, 87, 16, 88, 17, 89, 18, 90, 19, 150, 207, 151, 208, 152, 209,
    153, 210, 154, 20, 91, 21, 92, 22, 93, 23, 94, 24, 243, 293, 244, 294, 245, 295, 246, 296, 247, 333,
    373, 334, 374, 335, 375, 336, 376, 337, 248, 297, 249, 298, 250, 299, 251, 300, 252, 338, 377, 339,
    378, 340, 379, 341, 380, 342, 253, 301, 254, 302, 255, 303, 256, 304, 257, 343, 381, 344, 382, 345,
    383, 346, 384, 347, 258, 305, 259, 306, 260, 307, 261, 308, 262, 348, 385, 349, 386, 350, 387, 351,
    388, 352, 263, 309, 264, 310, 265, 311, 266, 312, 267, 25, 95, 26, 96, 27, 97, 28, 98, 29, 155, 211,
    156, 212, 157, 213, 158, 214, 159, 30, 99, 31, 100, 32, 101, 33, 102, 34, 160, 215, 161, 216, 162,
    217, 163, 218, 164, 35, 103, 36, 104, 37, 105, 38, 106, 39, 165, 219, 166, 220, 167, 221, 168, 222,
    169, 40, 107, 41, 108, 42, 109, 43, 110, 44, 170, 223, 171, 224, 172, 225, 173, 226, 174, 45, 111,
    46, 112, 47, 113, 48, 114, 49, 268, 313, 269, 314, 270, 315, 271, 316, 272, 353, 389, 354, 390, 355,
    391, 356, 392, 357, 273, 317, 274, 318, 275, 319, 276, 320, 277, 358, 393, 359, 394, 360, 395, 361,
    396, 362, 278, 321, 279, 322, 280, 323, 281, 324, 282, 363, 397, 364, 398, 365, 399, 366, 400, 367,
    283, 325, 284, 326, 285, 327, 286, 328, 287, 368, 401, 369, 402, 370, 403, 371, 404, 372, 288, 329,
    289, 330, 290, 331, 291, 332, 292, 50, 115, 51, 116, 52, 117, 53, 118, 54, 175, 227, 176, 228, 177,
    229, 178, 230, 179, 55, 119, 56, 120, 57, 121, 58, 122, 59, 180, 231, 181, 232, 182, 233, 183, 234,
    184, 60, 123, 61, 124, 62, 125, 63, 126, 64, 185, 235, 186, 236, 187, 237, 188, 238, 189, 65, 127,
    66, 128, 67, 129, 68, 130, 69, 190, 239, 191, 240, 192, 241, 193, 242, 194, 70, 131, 71, 132, 72,
    133, 73, 134, 74,
)


def _clamp(val: float, lo: float, hi: float) -> float:
    return lo if val < lo else (hi if val > hi else val)


def _clamp_int(val: int, lo: int, hi: int) -> int:
    return lo if val < lo else (hi if val > hi else val)


def rgb_to_ycbcr_bt709(r: float, g: float, b: float) -> tuple[float, float, float]:
    """Convert normalized RGB in [0, 1] to BT.709 (Y in [0, 1], Cb in [-0.5, 0.5], Cr in [-0.5, 0.5])."""
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    cb = (b - y) / 1.8556
    cr = (r - y) / 1.5748
    return y, cb, cr


def ycbcr_to_rgb_bt709(y: float, cb: float, cr: float) -> tuple[float, float, float]:
    """Convert BT.709 (Y in [0, 1], Cb, Cr in [-0.5, 0.5]) to RGB in [0, 1]."""
    r = _clamp(y + 1.5748 * cr, 0.0, 1.0)
    g = _clamp(y - 0.187324 * cb - 0.468124 * cr, 0.0, 1.0)
    b = _clamp(y + 1.8556 * cb, 0.0, 1.0)
    return r, g, b


class CubeLUT3D:
    """Represents a parsed .cube 3D (or 1D+3D) LUT with trilinear interpolation."""

    def __init__(
        self,
        size: int,
        table: list[tuple[float, float, float]],
        title: str = "",
        domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0),
        domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0),
    ):
        if size < 2 or len(table) != size * size * size:
            raise ValueError(f"无效的 .cube 3D LUT 尺寸: size={size}, count={len(table)}")
        self.size = size
        self.table = table
        self.title = title
        self.domain_min = domain_min
        self.domain_max = domain_max

    @classmethod
    def from_file(cls, path: str | Path) -> "CubeLUT3D":
        raw_text = Path(path).read_text(encoding="utf-8", errors="replace")
        return cls.from_text(raw_text, default_title=Path(path).stem)

    @classmethod
    def from_text(cls, text: str, default_title: str = "") -> "CubeLUT3D":
        title = default_title
        size_3d = None
        size_1d = None
        domain_min = (0.0, 0.0, 0.0)
        domain_max = (1.0, 1.0, 1.0)
        rows: list[tuple[float, float, float]] = []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            upper = line.upper()
            if upper.startswith("TITLE"):
                parts = line.split(None, 1)
                if len(parts) > 1:
                    title = parts[1].strip().strip('"')
                continue
            if upper.startswith("LUT_3D_SIZE"):
                size_3d = int(line.split()[1])
                continue
            if upper.startswith("LUT_1D_SIZE"):
                size_1d = int(line.split()[1])
                continue
            if upper.startswith("DOMAIN_MIN"):
                vals = [float(x) for x in line.split()[1:4]]
                domain_min = (vals[0], vals[1], vals[2])
                continue
            if upper.startswith("DOMAIN_MAX"):
                vals = [float(x) for x in line.split()[1:4]]
                domain_max = (vals[0], vals[1], vals[2])
                continue
            if upper.startswith("LUT_") or upper.startswith("DOMAIN_"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
                except ValueError:
                    continue

        if size_3d is not None:
            expected = size_3d * size_3d * size_3d
            if size_1d is not None and len(rows) == size_1d + expected:
                shaper = rows[:size_1d]
                rows = rows[size_1d:]
                # Apply 1D shaper into 3D table
                rows = cls._apply_1d_shaper_to_3d(size_3d, shaper, rows)
            if len(rows) != expected:
                raise ValueError(f".cube 数据点数量不匹配: 期望 {expected} ({size_3d}^3), 实际 {len(rows)}")
            return cls(size_3d, rows, title=title, domain_min=domain_min, domain_max=domain_max)

        if size_1d is not None and len(rows) == size_1d:
            # Convert 1D LUT into equivalent 17^3 3D LUT
            grid = 17
            table_3d: list[tuple[float, float, float]] = []
            for bi in range(grid):
                b = bi / (grid - 1)
                for gi in range(grid):
                    g = gi / (grid - 1)
                    for ri in range(grid):
                        r = ri / (grid - 1)
                        table_3d.append((
                            cls._interp_1d(shaper=rows, ch=0, x=r),
                            cls._interp_1d(shaper=rows, ch=1, x=g),
                            cls._interp_1d(shaper=rows, ch=2, x=b),
                        ))
            return cls(grid, table_3d, title=title, domain_min=domain_min, domain_max=domain_max)

        # Infer cube root if LUT_3D_SIZE was omitted
        n = round(len(rows) ** (1.0 / 3.0))
        if n >= 2 and n * n * n == len(rows):
            return cls(n, rows, title=title, domain_min=domain_min, domain_max=domain_max)
        raise ValueError("无法识别的 .cube 文件格式（缺少有效的 LUT_3D_SIZE）")

    @staticmethod
    def _interp_1d(shaper: list[tuple[float, float, float]], ch: int, x: float) -> float:
        n = len(shaper)
        pos = _clamp(x, 0.0, 1.0) * (n - 1)
        idx = int(math.floor(pos))
        if idx >= n - 1:
            return shaper[-1][ch]
        frac = pos - idx
        return shaper[idx][ch] * (1.0 - frac) + shaper[idx + 1][ch] * frac

    @classmethod
    def _apply_1d_shaper_to_3d(
        cls,
        size_3d: int,
        shaper: list[tuple[float, float, float]],
        table_3d: list[tuple[float, float, float]],
    ) -> list[tuple[float, float, float]]:
        temp = cls(size_3d, table_3d)
        out: list[tuple[float, float, float]] = []
        for bi in range(size_3d):
            b = cls._interp_1d(shaper, 2, bi / (size_3d - 1))
            for gi in range(size_3d):
                g = cls._interp_1d(shaper, 1, gi / (size_3d - 1))
                for ri in range(size_3d):
                    r = cls._interp_1d(shaper, 0, ri / (size_3d - 1))
                    out.append(temp.eval_rgb(r, g, b))
        return out

    def eval_rgb(self, r: float, g: float, b: float) -> tuple[float, float, float]:
        """Trilinear interpolation in standard .cube ordering (R fastest, G middle, B slowest)."""
        n = self.size
        scale = n - 1
        dmin = self.domain_min
        dmax = self.domain_max

        rn = (r - dmin[0]) / (dmax[0] - dmin[0]) if dmax[0] > dmin[0] else r
        gn = (g - dmin[1]) / (dmax[1] - dmin[1]) if dmax[1] > dmin[1] else g
        bn = (b - dmin[2]) / (dmax[2] - dmin[2]) if dmax[2] > dmin[2] else b

        rf = _clamp(rn, 0.0, 1.0) * scale
        gf = _clamp(gn, 0.0, 1.0) * scale
        bf = _clamp(bn, 0.0, 1.0) * scale

        r0 = min(int(math.floor(rf)), n - 2)
        g0 = min(int(math.floor(gf)), n - 2)
        b0 = min(int(math.floor(bf)), n - 2)
        r1, g1, b1 = r0 + 1, g0 + 1, b0 + 1

        dr = rf - r0
        dg = gf - g0
        db = bf - b0

        n2 = n * n
        tbl = self.table
        c000 = tbl[b0 * n2 + g0 * n + r0]
        c100 = tbl[b0 * n2 + g0 * n + r1]
        c010 = tbl[b0 * n2 + g1 * n + r0]
        c110 = tbl[b0 * n2 + g1 * n + r1]
        c001 = tbl[b1 * n2 + g0 * n + r0]
        c101 = tbl[b1 * n2 + g0 * n + r1]
        c011 = tbl[b1 * n2 + g1 * n + r0]
        c111 = tbl[b1 * n2 + g1 * n + r1]

        w000 = (1.0 - dr) * (1.0 - dg) * (1.0 - db)
        w100 = dr * (1.0 - dg) * (1.0 - db)
        w010 = (1.0 - dr) * dg * (1.0 - db)
        w110 = dr * dg * (1.0 - db)
        w001 = (1.0 - dr) * (1.0 - dg) * db
        w101 = dr * (1.0 - dg) * db
        w011 = (1.0 - dr) * dg * db
        w111 = dr * dg * db

        ro = _clamp(
            c000[0] * w000 + c100[0] * w100 + c010[0] * w010 + c110[0] * w110
            + c001[0] * w001 + c101[0] * w101 + c011[0] * w011 + c111[0] * w111,
            0.0, 1.0,
        )
        go = _clamp(
            c000[1] * w000 + c100[1] * w100 + c010[1] * w010 + c110[1] * w110
            + c001[1] * w001 + c101[1] * w101 + c011[1] * w011 + c111[1] * w111,
            0.0, 1.0,
        )
        bo = _clamp(
            c000[2] * w000 + c100[2] * w100 + c010[2] * w010 + c110[2] * w110
            + c001[2] * w001 + c101[2] * w101 + c011[2] * w011 + c111[2] * w111,
            0.0, 1.0,
        )
        return ro, go, bo

    def to_cube_text(self, size: int | None = None) -> str:
        n = size or self.size
        lines = [
            f'TITLE "{self.title or "ZV-E10M2 Custom Look"}"',
            f"LUT_3D_SIZE {n}",
            "DOMAIN_MIN 0.0 0.0 0.0",
            "DOMAIN_MAX 1.0 1.0 1.0",
        ]
        for bi in range(n):
            b = bi / (n - 1)
            for gi in range(n):
                g = gi / (n - 1)
                for ri in range(n):
                    r = ri / (n - 1)
                    ro, go, bo = self.eval_rgb(r, g, b)
                    lines.append(f"{ro:.6f} {go:.6f} {bo:.6f}")
        return "\n".join(lines) + "\n"


def _shared_index_to_slot6_index(i: int) -> float:
    """Exact native ZV-E10M2 gen=5 (still_shared) -> gen=6 (still_slot6) piecewise domain map."""
    if i <= 64:
        return 0.5 * i
    if i <= 88:
        return 32.0 + 2.0 * (i - 64)
    if i <= 104:
        return 80.0 + 0.5 * (i - 88)
    if i <= 120:
        return 88.0 + 2.0 * (i - 104)
    return 120.0 + 1.0 * (i - 120)


def fit_cp_tone_curves(
    cube: CubeLUT3D,
    base_slot6: list[int] | None = None,
    still_shared_max: int = 130944,
    still_slot6_max: int = 130944,
    movie_slot6_max: int = 122844,
) -> dict[str, tuple[bytes, bytes, list[int]]]:
    """Fit 129-point monotonic uint32 CP tone curves (still_shared, still_slot6, movie_slot6)
    from a .cube 3D LUT's neutral axis response.
    Returns dict mapping kind -> (samples_516_bytes, max_4_bytes, points_list).
    """
    ref_slot6 = base_slot6 if base_slot6 is not None else ST_SLOT6
    ref_max = float(ref_slot6[-1])

    # Evaluate neutral axis luma at 0.0 and 1.0
    r0, g0, b0 = cube.eval_rgb(0.0, 0.0, 0.0)
    r1, g1, b1 = cube.eval_rgb(1.0, 1.0, 1.0)
    y0, _, _ = rgb_to_ycbcr_bt709(r0, g0, b0)
    y1, _, _ = rgb_to_ycbcr_bt709(r1, g1, b1)

    norm_slot6: list[float] = [0.0] * 129
    for i in range(1, 128):
        v = _clamp(ref_slot6[i] / ref_max, 0.0, 1.0)
        rn, gn, bn = cube.eval_rgb(v, v, v)
        yn, _, _ = rgb_to_ycbcr_bt709(rn, gn, bn)
        # Preserve 92% of the raw LUT luma response (including lifted blacks & soft highlights)
        # while smoothly ramping the first/last 4 samples to hardware endpoints 0.0 and 1.0
        if y1 > y0 + 1e-4:
            yn_anchored = (yn - y0) / (y1 - y0)
        else:
            yn_anchored = v
        if i <= 4:
            w_raw = (i / 4.0) * 0.92
        elif i >= 124:
            w_raw = ((128 - i) / 4.0) * 0.92
        else:
            w_raw = 0.92
        yn_eff = _clamp(yn * w_raw + yn_anchored * (1.0 - w_raw), 0.0, 1.0)
        norm_slot6[i] = max(norm_slot6[i - 1], yn_eff)
    norm_slot6[128] = 1.0

    def _quantize_monotonic(norm_vals: list[float], max_int: int) -> list[int]:
        pts = [0] * 129
        for idx in range(1, 128):
            val = int(round(_clamp(norm_vals[idx], 0.0, 1.0) * max_int))
            pts[idx] = max(pts[idx - 1], min(val, max_int))
        pts[128] = max_int
        return pts

    still_s6_pts = _quantize_monotonic(norm_slot6, still_slot6_max)
    movie_s6_pts = _quantize_monotonic(norm_slot6, movie_slot6_max)

    norm_shared: list[float] = [0.0] * 129
    for i in range(1, 128):
        x = _shared_index_to_slot6_index(i)
        x0 = min(int(math.floor(x)), 127)
        frac = x - x0
        val = norm_slot6[x0] * (1.0 - frac) + norm_slot6[x0 + 1] * frac
        norm_shared[i] = max(norm_shared[i - 1], val)
    norm_shared[128] = 1.0
    still_sh_pts = _quantize_monotonic(norm_shared, still_shared_max)

    return {
        "still_shared": (struct.pack("<129I", *still_sh_pts), struct.pack("<I", still_shared_max), still_sh_pts),
        "still_slot6": (struct.pack("<129I", *still_s6_pts), struct.pack("<I", still_slot6_max), still_s6_pts),
        "movie_slot6": (struct.pack("<129I", *movie_s6_pts), struct.pack("<I", movie_slot6_max), movie_s6_pts),
    }


def _coeffs_to_matrix(m: list[int] | tuple[int, ...]) -> list[list[float]]:
    m0, m1, m2, m3, m4, m5 = m
    return [
        [(1024.0 + m0 + m1) / 1024.0, -m0 / 1024.0, -m1 / 1024.0],
        [-m2 / 1024.0, (1024.0 + m2 + m3) / 1024.0, -m3 / 1024.0],
        [-m4 / 1024.0, -m5 / 1024.0, (1024.0 + m4 + m5) / 1024.0],
    ]


def _matmul3(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [
        [sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
        for i in range(3)
    ]


def _solve_2x2_reg(
    pairs: list[tuple[float, float, float, float]],
    reg_lambda: float = 0.02,
) -> tuple[float, float]:
    """Solve weighted 2-variable linear least squares:
    min_{a, b} sum_k w_k * (a * x1_k + b * x2_k - y_k)^2 + reg_lambda * (a^2 + b^2)
    """
    a11 = reg_lambda
    a12 = 0.0
    a22 = reg_lambda
    b1 = 0.0
    b2 = 0.0
    for x1, x2, y, w in pairs:
        a11 += w * x1 * x1
        a12 += w * x1 * x2
        a22 += w * x2 * x2
        b1 += w * x1 * y
        b2 += w * x2 * y
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-12:
        return 0.0, 0.0
    return (b1 * a22 - b2 * a12) / det, (a11 * b2 - a12 * b1) / det


def fit_16hue_matrix_and_cc1(
    cube: CubeLUT3D,
    base_b13: list[list[list[int]]] | None = None,
    base_cc1: list[list[int]] | None = None,
) -> tuple[bytes, bytes, list[list[list[int]]], list[list[int]]]:
    """Fit the 16-hue white-preserving 3x3 RGB matrix bank (unit-02a4000d.bin, 576 bytes)
    and cc1 chroma bank (unit-02a40001.bin, 64 bytes) from a .cube 3D LUT.
    """
    ref_b13 = base_b13 if base_b13 is not None else ST_B13
    ref_cc1 = base_cc1 if base_cc1 is not None else ST_CC1

    # Fit differential 6-parameter white-preserving matrix dm[s] for each of the 16 hue slots (s = 0..15)
    delta_slots: list[tuple[float, float, float, float, float, float]] = []
    quad_sat_ratios: list[list[float]] = [[], [], [], []]

    for s in range(16):
        center_deg = s * 22.5
        rows_r: list[tuple[float, float, float, float]] = []
        rows_g: list[tuple[float, float, float, float]] = []
        rows_b: list[tuple[float, float, float, float]] = []

        for d_deg in (-18.0, -12.0, -6.0, 0.0, 6.0, 12.0, 18.0):
            ang_w = max(0.1, 1.0 - abs(d_deg) / 22.5)
            theta = math.radians((center_deg + d_deg) % 360.0)
            cos_t = math.cos(theta)
            sin_t = math.sin(theta)
            for y0 in (0.25, 0.40, 0.55, 0.70):
                rn0, gn0, bn0 = cube.eval_rgb(y0, y0, y0)
                yn0, _, _ = rgb_to_ycbcr_bt709(rn0, gn0, bn0)
                dy0 = yn0 - y0
                for chroma in (0.06, 0.12, 0.18, 0.24):
                    cb = chroma * cos_t
                    cr = chroma * sin_t
                    r, g, b = ycbcr_to_rgb_bt709(y0, cb, cr)
                    rl, gl, bl = cube.eval_rgb(r, g, b)
                    # Remove 1D luma tone curve shift dy0 so the 16-hue 3x3 matrix captures
                    # both chromatic hue/saturation transforms and split-tone color casts
                    rt = _clamp(rl - dy0, 0.0, 1.0)
                    gt = _clamp(gl - dy0, 0.0, 1.0)
                    bt = _clamp(bl - dy0, 0.0, 1.0)

                    w = ang_w * (chroma / 0.18)
                    rows_r.append((r - g, r - b, 1024.0 * (rt - r), w))
                    rows_g.append((g - r, g - b, 1024.0 * (gt - g), w))
                    rows_b.append((b - r, b - g, 1024.0 * (bt - b), w))

                    if d_deg == 0.0:
                        _, cb_out, cr_out = rgb_to_ycbcr_bt709(rt, gt, bt)
                        c_in = math.hypot(cb, cr)
                        c_out = math.hypot(cb_out, cr_out)
                        if c_in > 1e-4:
                            quad_sat_ratios[(s // 4) % 4].append(c_out / c_in)

        dm0, dm1 = _solve_2x2_reg(rows_r, reg_lambda=0.015)
        dm2, dm3 = _solve_2x2_reg(rows_g, reg_lambda=0.015)
        dm4, dm5 = _solve_2x2_reg(rows_b, reg_lambda=0.015)
        delta_slots.append((dm0, dm1, dm2, dm3, dm4, dm5))

    # Circularly smooth delta_slots (0.15, 0.70, 0.15) to avoid sector boundary seams
    smoothed_delta: list[tuple[float, float, float, float, float, float]] = []
    for s in range(16):
        prev_d = delta_slots[(s - 1) % 16]
        curr_d = delta_slots[s]
        next_d = delta_slots[(s + 1) % 16]
        smoothed_delta.append(tuple(
            0.15 * prev_d[k] + 0.70 * curr_d[k] + 0.15 * next_d[k]
            for k in range(6)
        ))

    # Compose delta matrix with baseline matrix for all 3 illuminant groups (B, A1, A2)
    out_b13: list[list[list[int]]] = []
    for g_idx in range(3):
        group_slots: list[list[int]] = []
        for s in range(16):
            m_base = _coeffs_to_matrix(ref_b13[g_idx][s])
            m_delta = _coeffs_to_matrix(smoothed_delta[s])
            m_comp = _matmul3(m_delta, m_base)
            m0 = _clamp_int(int(round(-1024.0 * m_comp[0][1])), -512, 768)
            m1 = _clamp_int(int(round(-1024.0 * m_comp[0][2])), -512, 768)
            m2 = _clamp_int(int(round(-1024.0 * m_comp[1][0])), -512, 768)
            m3 = _clamp_int(int(round(-1024.0 * m_comp[1][2])), -512, 768)
            m4 = _clamp_int(int(round(-1024.0 * m_comp[2][0])), -512, 768)
            m5 = _clamp_int(int(round(-1024.0 * m_comp[2][1])), -512, 768)
            group_slots.append([m0, m1, m2, m3, m4, m5])
        out_b13.append(group_slots)

    # Fit cc1 chroma parameters (3 groups x 8 int16 + 16 zero bytes = 64 bytes)
    out_cc1 = [list(row) for row in ref_cc1]
    all_ratios = [r for q_list in quad_sat_ratios for r in q_list]
    overall_sat = sum(all_ratios) / len(all_ratios) if all_ratios else 1.0
    if overall_sat < 0.05:
        # Monochrome / B&W LUT: zero out hardware chroma gains across all illuminant groups
        out_cc1[0][4:8] = [0, 0, 0, 0]
        out_cc1[1][4:8] = [0, 0, 0, 0]
        out_cc1[2][4:8] = [0, 0, 0, 0]
    else:
        for q in range(4):
            ratios = quad_sat_ratios[q]
            avg_ratio = sum(ratios) / len(ratios) if ratios else 1.0
            cc1_scale = _clamp(avg_ratio ** 0.85, 0.25, 1.65)
            out_cc1[0][4 + q] = _clamp_int(int(round(ref_cc1[0][4 + q] * cc1_scale)), 64, 960)
            # Also adjust shadow/highlight chroma roll-off (indices 0..3)
            roll_shift = int(round((1.0 - avg_ratio) * 180.0))
            out_cc1[0][q] = _clamp_int(ref_cc1[0][q] - roll_shift, -512, 256)

    b13_bytes = b"".join(
        struct.pack("<6h", *slot)
        for group in out_b13
        for slot in group
    )
    cc1_bytes = b"".join(struct.pack("<8h", *row) for row in out_cc1) + bytes(16)
    assert len(b13_bytes) == 576 and len(cc1_bytes) == 64
    return b13_bytes, cc1_bytes, out_b13, out_cc1


def encode_cp_3dlut_unit(cube: CubeLUT3D, preserve_neutral: bool = True) -> bytes:
    """Encode a .cube 3D LUT into ZV-E10M2 CP 9x9x5 = 405-point 3D YCbCr LUT format
    (units 0x02a40004..0x02a40007: 1215 bytes = 3 x 405 planes + 65 zero bytes = 1280 bytes).
    Exact match for Create3DLUT (0x11dbd0 in cpapp-b.bin).
    """
    plane0 = bytearray(405)  # dY (signed 7-bit, 1 LSB = 1.0 on [0, 256])
    plane1 = bytearray(405)  # dCb (signed 7-bit, 1 LSB = 0.75 on [-128, +128])
    plane2 = bytearray(405)  # dCr (signed 7-bit, 1 LSB = 0.75 on [-128, +128])

    for y_idx, y_val in enumerate(CP_3DLUT_Y_GRID):
        y_norm = y_val / 256.0
        rn0, gn0, bn0 = cube.eval_rgb(y_norm, y_norm, y_norm)
        yn0, _, _ = rgb_to_ycbcr_bt709(rn0, gn0, bn0)

        for cb_idx, cb_val in enumerate(CP_3DLUT_C_GRID):
            cb_norm = cb_val / 256.0
            for cr_idx, cr_val in enumerate(CP_3DLUT_C_GRID):
                idx = cb_idx * 9 + cr_idx + y_idx * 81
                if preserve_neutral and cb_idx == 4 and cr_idx == 4:
                    plane0[idx] = 0
                    plane1[idx] = 0
                    plane2[idx] = 0
                    continue
                cr_norm = cr_val / 256.0
                r, g, b = ycbcr_to_rgb_bt709(y_norm, cb_norm, cr_norm)
                rl, gl, bl = cube.eval_rgb(r, g, b)
                yl, cbl, crl = rgb_to_ycbcr_bt709(rl, gl, bl)

                if preserve_neutral:
                    dy_256 = (yl - yn0) * 256.0
                else:
                    dy_256 = yl * 256.0 - y_val
                dcb_256 = cbl * 256.0 - cb_val
                dcr_256 = crl * 256.0 - cr_val

                dy_q = _clamp_int(int(round(dy_256)), -64, 63)
                if y_idx == 0 and dy_q < 0:
                    dy_q = 0
                elif y_idx == 4 and dy_q > 0:
                    dy_q = 0
                dcb_q = _clamp_int(int(round(dcb_256 * 4.0 / 3.0)), -64, 63)
                dcr_q = _clamp_int(int(round(dcr_256 * 4.0 / 3.0)), -64, 63)

                plane0[idx] = dy_q & 0xFF
                plane1[idx] = dcb_q & 0xFF
                plane2[idx] = dcr_q & 0xFF

    return bytes(plane0) + bytes(plane1) + bytes(plane2) + bytes(65)


def simulate_cp_create_3dlut(unit_1280: bytes) -> list[int]:
    """Exact Python reference implementation of CP Create3DLUT (0x11dbd0 in cpapp-b.bin,
    with s0[0x3a]=0, s0[0x33]=8, s1_8[0x188]=1, s1_8[0x189]=2).
    Takes a 1280-byte unit (0x02a40004..0x02a40007) and returns 405 uint32 hardware words
    scattered by CP_3DLUT_INDEX_MAP (0xe3b7e4).
    """
    if len(unit_1280) < 1215:
        raise ValueError("CP 3D LUT unit 长度不足 1215 字节")

    def _s8(b: int) -> int:
        return b - 256 if b >= 128 else b

    words = [0] * 405
    for cb_idx in range(9):
        for cr_idx in range(9):
            for y_idx in range(5):
                idx = y_idx * 81 + cb_idx * 9 + cr_idx
                b0 = _s8(unit_1280[idx])
                b1 = _s8(unit_1280[idx + 405])
                b2 = _s8(unit_1280[idx + 810])

                # Y clamping at 0x11dec8..0x11df00:
                dy = _clamp_int(b0, -64, 63)
                if y_idx == 4 and dy > 0:
                    dy = 0
                if y_idx == 0 and dy < 0:
                    dy = 0

                f0 = dy & 0x7F
                f1 = b1 & 0x7F
                f2 = b2 & 0x7F

                word = (f0 << 22) | (f1 << 12) | (f2 << 2)
                hw_slot = CP_3DLUT_INDEX_MAP[cb_idx * 9 + cr_idx + y_idx * 81]
                words[hw_slot] = word
    return words


def encode_ap_lut_file(cube: CubeLUT3D) -> bytes:
    """Encode a .cube 3D LUT into Sony AP 17x17x17 hardware .LUT format (48,000 bytes,
    exact match for 0x2d15130 in /usr/lib/appFw.so).
    """
    buf = bytearray(48000)
    out_ptr = 0
    for b_idx in range(17):
        b = b_idx / 16.0
        for g_idx in range(17):
            g = g_idx / 16.0
            for r_step in range(0, 16, 2):
                r0 = r_step / 16.0
                r1 = (r_step + 1) / 16.0
                ro0, go0, bo0 = cube.eval_rgb(r0, g, b)
                ro1, go1, bo1 = cube.eval_rgb(r1, g, b)
                for c0, c1 in ((ro0, ro1), (go0, go1), (bo0, bo1)):
                    v0 = _clamp_int(int(math.floor(c0 * 4096.0 + 0.5)), 0, 4095)
                    v1 = _clamp_int(int(math.floor(c1 * 4096.0 + 0.5)), 0, 4095)
                    struct.pack_into("<I", buf, out_ptr, v0 | (v1 << 16))
                    out_ptr += 4
            # 17th R point (r_idx = 16)
            ro16, go16, bo16 = cube.eval_rgb(1.0, g, b)
            for c16 in (ro16, go16, bo16):
                v16 = _clamp_int(int(math.floor(c16 * 4096.0 + 0.5)), 0, 4095)
                struct.pack_into("<I", buf, out_ptr, v16)
                out_ptr += 4
            # 16 bytes row padding (108 + 16 = 124 bytes per (B, G) row)
            out_ptr += 16
        # After each B plane except B=8 and B=16, add 592 bytes plane padding
        if b_idx not in (8, 16):
            out_ptr += 592
    assert out_ptr == 44716
    return bytes(buf)


def _comp_edits_by_offset(look_entry: dict, input_file: str) -> dict[int, dict]:
    comp = next(c for c in look_entry["components"] if c["input_file"] == input_file)
    return {e["offset"]: e for e in comp["edits"]}


def build_custom_manifest(
    base_manifest: dict,
    in_cube: CubeLUT3D | None = None,
    sh_cube: CubeLUT3D | None = None,
    base_mode: str = "ST",
) -> dict:
    """Build a FL2-FL3.json-compatible manifest where FL2 (IN slot, bank 23) and/or
    FL3 (SH slot, bank 25) are replaced by converted .cube 3D LUTs.
    Preserves all exact window offsets, byte lengths, parameter mappings, and source hashes.
    """
    manifest = json.loads(json.dumps(base_manifest))

    slot_specs = [
        ("IN", "FL2", in_cube, 23, (0xC78C90, 0xC78ED4, 0xC79A28)),
        ("SH", "FL3", sh_cube, 25, (0xC79118, 0xC7935C, 0xC79C6C)),
    ]

    for menu_label, donor_label, cube, bank, curve_offsets in slot_specs:
        if cube is None:
            continue
        # If user selected the built-in Sony FL2 / FL3 donor .cube in its matching slot, keep exact donor tables
        if cube.title == f"Sony_{donor_label}_Look":
            continue

        look_entry = manifest[donor_label]
        cp_by_off = _comp_edits_by_offset(look_entry, "cpapp-b.bin")
        u1_by_off = _comp_edits_by_offset(look_entry, "unit-02a40001.bin")
        ud_by_off = _comp_edits_by_offset(look_entry, "unit-02a4000d.bin")

        u1_bank_off = 0x1250 + bank * 64
        ud_bank_off = 0x1E0 + bank * 768

        if base_mode == "ST":
            ref_s6 = ST_SLOT6
            ref_cc1 = ST_CC1
            ref_b13 = ST_B13
        else:
            s6_raw = bytes.fromhex(cp_by_off[curve_offsets[1]]["after_hex"])
            ref_s6 = list(struct.unpack("<129I", s6_raw))
            cc1_raw = bytes.fromhex(u1_by_off[u1_bank_off]["after_hex"])
            ref_cc1 = [list(struct.unpack_from("<8h", cc1_raw, g * 16)) for g in range(3)]
            b13_raw = bytes.fromhex(ud_by_off[ud_bank_off]["after_hex"])
            ref_b13 = [
                [list(struct.unpack_from("<6h", b13_raw, g * 192 + s * 12)) for s in range(16)]
                for g in range(3)
            ]

        sh_max = struct.unpack("<I", bytes.fromhex(cp_by_off[curve_offsets[0] + 0x220]["after_hex"]))[0]
        s6_max = struct.unpack("<I", bytes.fromhex(cp_by_off[curve_offsets[1] + 0x220]["after_hex"]))[0]
        m6_max = struct.unpack("<I", bytes.fromhex(cp_by_off[curve_offsets[2] + 0x220]["after_hex"]))[0]

        curves = fit_cp_tone_curves(
            cube,
            base_slot6=ref_s6,
            still_shared_max=sh_max,
            still_slot6_max=s6_max,
            movie_slot6_max=m6_max,
        )
        for kind, off in zip(("still_shared", "still_slot6", "movie_slot6"), curve_offsets):
            samples_bytes, max_bytes, _ = curves[kind]
            cp_by_off[off]["after_hex"] = samples_bytes.hex()
            cp_by_off[off + 0x220]["after_hex"] = max_bytes.hex()

        b13_bytes, cc1_bytes, _, _ = fit_16hue_matrix_and_cc1(
            cube,
            base_b13=ref_b13,
            base_cc1=ref_cc1,
        )
        u1_by_off[u1_bank_off]["after_hex"] = cc1_bytes.hex()
        ud_by_off[ud_bank_off]["after_hex"] = b13_bytes.hex()

    return manifest


def build_Preset_Cube(preset_name: str, fl23_manifest: dict | None = None, size: int = 17) -> CubeLUT3D:
    """Construct built-in preset .cube 3D LUTs (relative to ST Standard look) for testing and direct use."""
    n = size
    table: list[tuple[float, float, float]] = []

    if preset_name in ("FL2", "FL3") and fl23_manifest is not None:
        look_entry = fl23_manifest[preset_name]
        cp_by_off = _comp_edits_by_offset(look_entry, "cpapp-b.bin")
        ud_by_off = _comp_edits_by_offset(look_entry, "unit-02a4000d.bin")
        s6_off = 0xC78ED4 if preset_name == "FL2" else 0xC7935C
        bank = 23 if preset_name == "FL2" else 25
        ud_off = 0x1E0 + bank * 768

        fl_s6 = list(struct.unpack("<129I", bytes.fromhex(cp_by_off[s6_off]["after_hex"])))
        b13_raw = bytes.fromhex(ud_by_off[ud_off]["after_hex"])
        fl_b13 = [list(struct.unpack_from("<6h", b13_raw, s * 12)) for s in range(16)]

        # Precompute relative 3x3 matrix for each of the 16 hue slots (group 0)
        rel_mats: list[list[list[float]]] = []
        for s in range(16):
            st_m = ST_B13[0][s]
            fl_m = fl_b13[s]
            diff = [fl_m[k] - st_m[k] for k in range(6)]
            rel_mats.append(_coeffs_to_matrix(diff))

        def _tone_map(v: float) -> float:
            # Map v through (FL_slot6 / ST_slot6) curve ratio
            idx_f = _clamp(v, 0.0, 1.0) * 120.0
            i0 = min(int(math.floor(idx_f)), 119)
            frac = idx_f - i0
            st_v = (ST_SLOT6[i0] * (1.0 - frac) + ST_SLOT6[i0 + 1] * frac) / ST_SLOT6[-1]
            fl_v = (fl_s6[i0] * (1.0 - frac) + fl_s6[i0 + 1] * frac) / fl_s6[-1]
            if st_v < 1e-4:
                return fl_v
            return _clamp(v * (fl_v / st_v), 0.0, 1.0)

        for bi in range(n):
            b = bi / (n - 1)
            for gi in range(n):
                g = gi / (n - 1)
                for ri in range(n):
                    r = ri / (n - 1)
                    y, cb, cr = rgb_to_ycbcr_bt709(r, g, b)
                    theta = (math.degrees(math.atan2(cr, cb)) + 360.0) % 360.0
                    slot_f = (theta / 22.5) % 16.0
                    s0 = int(math.floor(slot_f)) % 16
                    s1 = (s0 + 1) % 16
                    w1 = slot_f - math.floor(slot_f)
                    m0 = rel_mats[s0]
                    m1 = rel_mats[s1]
                    m = [[m0[r_i][c_i] * (1.0 - w1) + m1[r_i][c_i] * w1 for c_i in range(3)] for r_i in range(3)]
                    rm = m[0][0] * r + m[0][1] * g + m[0][2] * b
                    gm = m[1][0] * r + m[1][1] * g + m[1][2] * b
                    bm = m[2][0] * r + m[2][1] * g + m[2][2] * b
                    yt = _tone_map(y)
                    dy = yt - y
                    table.append((_clamp(rm + dy, 0.0, 1.0), _clamp(gm + dy, 0.0, 1.0), _clamp(bm + dy, 0.0, 1.0)))
        return CubeLUT3D(n, table, title=f"Sony_{preset_name}_Look")

    for bi in range(n):
        b = bi / (n - 1)
        for gi in range(n):
            g = gi / (n - 1)
            for ri in range(n):
                r = ri / (n - 1)
                if preset_name == "Classic_Chrome":
                    # Classic Chrome: deep shadow S-curve, muted documentary saturation, cyan-shifted skies
                    y, cb, cr = rgb_to_ycbcr_bt709(r, g, b)
                    y_s = _clamp(y - 0.110 * math.sin(2.0 * math.pi * y), 0.0, 1.0)
                    cb_s = cb * 0.64 - 0.055 * max(0.0, cr) - 0.018
                    cr_s = cr * 0.72 + 0.045 * max(0.0, -cb) + 0.012
                    ro, go, bo = ycbcr_to_rgb_bt709(y_s, cb_s, cr_s)
                    table.append((ro, go, bo))
                elif preset_name == "Teal_Orange":
                    # Cinematic Teal & Orange: bold shadow/cyan push to teal, warm skin/amber push to orange
                    y, cb, cr = rgb_to_ycbcr_bt709(r, g, b)
                    y_s = _clamp(y - 0.095 * math.sin(2.0 * math.pi * y), 0.0, 1.0)
                    warmth = max(0.0, cr)
                    coolness = max(0.0, cb)
                    cb_s = cb * 0.85 - 0.14 * warmth + 0.11 * coolness + 0.025 * (0.5 - y)
                    cr_s = cr * 1.22 + 0.10 * warmth - 0.12 * coolness + 0.020 * y
                    ro, go, bo = ycbcr_to_rgb_bt709(y_s, cb_s, cr_s)
                    table.append((ro, go, bo))
                elif preset_name == "Classic_Neg":
                    # Fujifilm Classic Neg (NC): lifted matte green-cyan shadows, high midtone contrast, amber-red highlights
                    y, cb, cr = rgb_to_ycbcr_bt709(r, g, b)
                    y_s = _clamp(0.065 + 0.895 * (y ** 1.12) - 0.095 * math.sin(2.0 * math.pi * y), 0.0, 1.0)
                    warmth = max(0.0, cr)
                    coolness = max(0.0, cb)
                    cb_s = cb * 0.68 - 0.11 * warmth - 0.035 * y + 0.025 * (1.0 - y)
                    cr_s = cr * 1.18 + 0.08 * warmth - 0.09 * coolness + 0.030 * (y - 0.4)
                    ro, go, bo = ycbcr_to_rgb_bt709(y_s, cb_s, cr_s)
                    table.append((ro, go, bo))
                elif preset_name == "Nostalgic_Neg":
                    # Fujifilm Nostalgic Neg: rich amber-gold highlights & midtones, warm vintage film wash
                    y, cb, cr = rgb_to_ycbcr_bt709(r, g, b)
                    y_s = _clamp(0.055 + 0.915 * (y ** 0.88) - 0.055 * math.sin(2.0 * math.pi * y), 0.0, 1.0)
                    cb_s = cb * 0.72 - 0.085 * (0.3 + 0.7 * y) - 0.07 * max(0.0, cr)
                    cr_s = cr * 1.16 + 0.065 * (0.3 + 0.7 * y) + 0.05 * max(0.0, -cb)
                    ro, go, bo = ycbcr_to_rgb_bt709(y_s, cb_s, cr_s)
                    table.append((ro, go, bo))
                elif preset_name == "Astia_Soft":
                    # Fujifilm Astia Soft: bright luminous midtones, rosy-peach translucent skin, vivid skies
                    y, cb, cr = rgb_to_ycbcr_bt709(r, g, b)
                    y_s = _clamp(0.025 + 0.975 * (y ** 0.80), 0.0, 1.0)
                    cb_s = cb * 1.18 + 0.020 * max(0.0, cb)
                    cr_s = cr * 1.08 - 0.035 * max(0.0, -cb)
                    ro, go, bo = ycbcr_to_rgb_bt709(y_s, cb_s, cr_s)
                    table.append((ro, go, bo))
                elif preset_name == "Velvia_Vivid":
                    # Fujifilm Velvia Vivid: deep blacks, strong S-curve contrast, ultra-rich landscape saturation
                    y, cb, cr = rgb_to_ycbcr_bt709(r, g, b)
                    y_s = _clamp(y - 0.125 * math.sin(2.0 * math.pi * y), 0.0, 1.0)
                    cb_s = cb * 1.48 + 0.04 * max(0.0, cb)
                    cr_s = cr * 1.45 + 0.04 * max(0.0, cr)
                    ro, go, bo = ycbcr_to_rgb_bt709(y_s, cb_s, cr_s)
                    table.append((ro, go, bo))
                elif preset_name == "Eterna_Cinema":
                    # Fujifilm Eterna Cinema: lifted matte black point, soft highlight rolloff, low-saturation cinema look
                    y, cb, cr = rgb_to_ycbcr_bt709(r, g, b)
                    y_s = _clamp(0.085 + 0.825 * (y ** 0.86) + 0.045 * math.sin(math.pi * y), 0.0, 1.0)
                    cb_s = cb * 0.58 + 0.025 * (1.0 - y)
                    cr_s = cr * 0.62 - 0.015 * (1.0 - y)
                    ro, go, bo = ycbcr_to_rgb_bt709(y_s, cb_s, cr_s)
                    table.append((ro, go, bo))
                elif preset_name == "Kodak_Portra_400":
                    # Kodak Portra 400: lifted creamy midtones, golden-warm skin, pastel cyan skies
                    y, cb, cr = rgb_to_ycbcr_bt709(r, g, b)
                    y_s = _clamp(0.045 + 0.935 * (y ** 0.84) - 0.040 * math.sin(2.0 * math.pi * y), 0.0, 1.0)
                    cb_s = cb * 0.82 - 0.055 * y - 0.05 * max(0.0, cr)
                    cr_s = cr * 1.12 + 0.045 * y + 0.04 * max(0.0, cr)
                    ro, go, bo = ycbcr_to_rgb_bt709(y_s, cb_s, cr_s)
                    table.append((ro, go, bo))
                elif preset_name == "Kodak_Gold_200":
                    # Kodak Gold 200: strong vintage golden sunshine, warm yellow-amber cast, punchy contrast
                    y, cb, cr = rgb_to_ycbcr_bt709(r, g, b)
                    y_s = _clamp(0.030 + 0.955 * y - 0.085 * math.sin(2.0 * math.pi * y), 0.0, 1.0)
                    cb_s = cb * 0.78 - 0.095 * (0.35 + 0.65 * y) - 0.08 * max(0.0, cr)
                    cr_s = cr * 1.24 + 0.065 * (0.35 + 0.65 * y) + 0.06 * max(0.0, cr)
                    ro, go, bo = ycbcr_to_rgb_bt709(y_s, cb_s, cr_s)
                    table.append((ro, go, bo))
                elif preset_name == "Kamakura_Fresh_Blue":
                    # Japanese Airy Cyan-Blue (日系清新镰仓蓝): high-key airy brightness (+18% midtones), cool cyan-blue shift
                    y, cb, cr = rgb_to_ycbcr_bt709(r, g, b)
                    y_s = _clamp(0.070 + 0.930 * (y ** 0.68), 0.0, 1.0)
                    cool = max(0.0, cb)
                    warm = max(0.0, cr)
                    cb_s = cb * 1.26 + 0.055 * (0.3 + 0.7 * y) + 0.08 * warm
                    cr_s = cr * 0.72 - 0.045 * (0.3 + 0.7 * y) - 0.09 * cool
                    ro, go, bo = ycbcr_to_rgb_bt709(y_s, cb_s, cr_s)
                    table.append((ro, go, bo))
                elif preset_name == "Leica_Monochrom_BW":
                    # High-contrast silver halide B&W (徕卡高反差黑白)
                    y, _, _ = rgb_to_ycbcr_bt709(r, g, b)
                    y_s = _clamp(y - 0.135 * math.sin(2.0 * math.pi * y), 0.0, 1.0)
                    table.append((y_s, y_s, y_s))
                else:
                    table.append((r, g, b))
    return CubeLUT3D(n, table, title=preset_name)


BUILTIN_LUT_LABELS: dict[str, str] = {
    "01_富士胶片2号_原厂移植.cube": "富士胶片 2 号（原厂移植）",
    "02_富士胶片3号_原厂移植.cube": "富士胶片 3 号（原厂移植）",
    "03_富士经典正片_纪实街拍.cube": "富士经典正片（低饱和纪实街拍）",
    "04_富士经典负片_复古冷暖.cube": "富士经典负片（冷绿暗部暖高光）",
    "05_富士怀旧负片_琥珀暖金.cube": "富士怀旧负片（琥珀暖金夕阳）",
    "06_富士柔和人像_肤色通透.cube": "富士柔和人像（白皙通透肤色）",
    "07_富士鲜艳风光_浓郁山水.cube": "富士鲜艳风光（高饱和蓝天翠绿）",
    "08_富士电影胶片_柔和高光.cube": "富士电影胶片（低反差柔高光）",
    "09_柯达暖调人像_奶油肤色.cube": "柯达暖调人像（奶油暖调胶片）",
    "10_柯达复古金_晴天暖阳.cube": "柯达复古金（浓郁复古暖阳）",
    "11_日系清新镰仓蓝_通透青蓝.cube": "日系清新镰仓蓝（明亮通透青蓝）",
    "12_好莱坞电影青橙_冷暖对比.cube": "好莱坞电影青橙（冷青暗部暖肤色）",
    "13_徕卡高反差黑白_银盐质感.cube": "徕卡高反差黑白（纯净银盐质感）",
    "14_标准中性原色_无偏色基准.cube": "标准中性原色（无偏色基准）",
}


def ensure_sample_cube_files(luts_dir: Path, fl23_manifest: dict | None = None) -> list[Path]:
    """Ensure sample .cube LUT files exist in luts_dir for out-of-the-box selection."""
    luts_dir.mkdir(parents=True, exist_ok=True)
    presets = [
        ("01_富士胶片2号_原厂移植.cube", "FL2"),
        ("02_富士胶片3号_原厂移植.cube", "FL3"),
        ("03_富士经典正片_纪实街拍.cube", "Classic_Chrome"),
        ("04_富士经典负片_复古冷暖.cube", "Classic_Neg"),
        ("05_富士怀旧负片_琥珀暖金.cube", "Nostalgic_Neg"),
        ("06_富士柔和人像_肤色通透.cube", "Astia_Soft"),
        ("07_富士鲜艳风光_浓郁山水.cube", "Velvia_Vivid"),
        ("08_富士电影胶片_柔和高光.cube", "Eterna_Cinema"),
        ("09_柯达暖调人像_奶油肤色.cube", "Kodak_Portra_400"),
        ("10_柯达复古金_晴天暖阳.cube", "Kodak_Gold_200"),
        ("11_日系清新镰仓蓝_通透青蓝.cube", "Kamakura_Fresh_Blue"),
        ("12_好莱坞电影青橙_冷暖对比.cube", "Teal_Orange"),
        ("13_徕卡高反差黑白_银盐质感.cube", "Leica_Monochrom_BW"),
        ("14_标准中性原色_无偏色基准.cube", "Identity_Neutral"),
    ]
    paths: list[Path] = []
    for filename, preset_key in presets:
        target = luts_dir / filename
        if not target.exists():
            lut = build_Preset_Cube(preset_key, fl23_manifest=fl23_manifest, size=17)
            target.write_text(lut.to_cube_text(17), encoding="utf-8")
        paths.append(target)
    return paths
