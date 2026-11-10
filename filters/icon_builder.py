"""Dynamic Creative Look icon (.uxc) and menu title string (.uxc) builder and ARM64 worker compiler."""
from __future__ import annotations

from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys


LDEC_LEN = (3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 32, 64)
LEN_TO_CODE = {length: idx for idx, length in enumerate(LDEC_LEN)}

DIGITS: dict[str, tuple[str, ...]] = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00110", "01000", "10000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
}

# Built-in icon label presets:
# (preset_key, display_label, top_in, top_sh, bot_in, bot_sh, title_in, title_sh)
ICON_PRESETS: list[tuple[str, str, str, str, str, str, str, str]] = [
    (
        "top_stock_bot_fl",
        "上方保持原厂 (3 IN / 4 SH) · 下方显示 FL2 / FL3（推荐·上下不重复）",
        "IN",
        "SH",
        "FL2",
        "FL3",
        "FL2",
        "FL3",
    ),
    (
        "top_l12_bot_fl",
        "上方改为 3 L1 / 4 L2 · 下方显示 FL2 / FL3（上下区分）",
        "L1",
        "L2",
        "FL2",
        "FL3",
        "FL2",
        "FL3",
    ),
    (
        "top_fl_bot_l12",
        "上方显示 3 FL2 / 4 FL3 · 下方改为 L1 / L2（上下区分）",
        "FL2",
        "FL3",
        "L1",
        "L2",
        "L1",
        "L2",
    ),
    (
        "top_fl_bot_stock",
        "上方显示 3 FL2 / 4 FL3 · 下方保持原厂 IN / SH（上下区分）",
        "FL2",
        "FL3",
        "IN",
        "SH",
        "FL2",
        "FL3",
    ),
    (
        "all_l12",
        "上下统一改为 L1 / L2（LUT 1 / LUT 2 代号，含屏幕大字）",
        "L1",
        "L2",
        "L1",
        "L2",
        "L1",
        "L2",
    ),
    (
        "all_fl",
        "上下统一显示 FL2 / FL3（默认上下相同）",
        "FL2",
        "FL3",
        "FL2",
        "FL3",
        "FL2",
        "FL3",
    ),
    (
        "all_stock",
        "全部恢复原厂 IN / SH（恢复原厂图标与文字）",
        "IN",
        "SH",
        "IN",
        "SH",
        "IN",
        "SH",
    ),
]

EXTRA_TARGETS = (
    (0x020023B6, 0x020023B3, 7),
    (0x020023B0, 0x020023B3, 8),
    (0x020043D5, 0x020043D2, 7),
    (0x020043CD, 0x020043D2, 8),
    (0x020043BB, 0x020043B8, 7),
    (0x020043B4, 0x020043B8, 8),
    (0x020043C3, 0x020043C0, 7),
    (0x020043BC, 0x020043C0, 8),
)


def sha(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_icon_word(word: str, label_name: str = "图标代号") -> str:
    w = word.strip().upper()
    if not (1 <= len(w) <= 3):
        raise ValueError(f"{label_name} 长度必须为 1～3 个字符：{word!r}")
    for ch in w:
        if ch not in DIGITS:
            raise ValueError(f"{label_name} 仅支持大写英文字母 A-Z、数字 0-9 或 -/+：{word!r}")
    return w


def decode_ldec(data: bytes | bytearray, expected: int) -> bytes:
    cursor = 0
    result = bytearray()
    while len(result) < expected:
        if data[cursor] != 240:
            raise ValueError("Missing LDEC block marker")
        cursor += 1
        block = bytearray()
        ended = False
        while not ended:
            flags = data[cursor]
            cursor += 1
            for bit in range(8):
                if flags & (1 << bit):
                    token = struct.unpack_from(">H", data, cursor)[0]
                    cursor += 2
                    if not token:
                        ended = True
                        break
                    distance = token & 4095
                    if not 0 < distance <= len(block):
                        raise ValueError("Invalid LDEC distance")
                    for _ in range(LDEC_LEN[token >> 12]):
                        block.append(block[-distance])
                else:
                    block.append(data[cursor])
                    cursor += 1
                if len(block) > 4096:
                    raise ValueError("LDEC block overflow")
        if len(block) != min(4096, expected - len(result)):
            raise ValueError("LDEC size mismatch")
        result.extend(block)
    if any(data[cursor:]):
        raise ValueError("Unexpected bytes after LDEC stream")
    return bytes(result)


def _ldec_compress_block(block: bytes) -> bytes:
    n = len(block)
    inf = 10**18
    dp: list[tuple[int, int, tuple | None]] = [(inf, -1, None)] * (n + 1)
    dp[0] = (0, -1, None)

    for i in range(n):
        cur_cost = dp[i][0]
        if cur_cost == inf:
            continue
        if cur_cost + 9 < dp[i + 1][0]:
            dp[i + 1] = (cur_cost + 9, i, ("lit", block[i]))
        max_dist = min(i, 0xFFF)
        if max_dist >= 1:
            for length in LDEC_LEN:
                if i + length > n:
                    continue
                if cur_cost + 17 >= dp[i + length][0]:
                    continue
                target = block[i : i + length]
                pos = block.rfind(target, i - max_dist, i + length - 1)
                if pos != -1:
                    dist = i - pos
                    if 1 <= dist <= 0xFFF:
                        dp[i + length] = (cur_cost + 17, i, ("match", LEN_TO_CODE[length], dist))
                else:
                    for dist in (1, 2, 4):
                        if dist <= max_dist:
                            ok = True
                            for k in range(length):
                                if block[i + k] != block[i - dist + (k % dist)]:
                                    ok = False
                                    break
                            if ok:
                                dp[i + length] = (cur_cost + 17, i, ("match", LEN_TO_CODE[length], dist))
                                break

    tokens = []
    curr = n
    while curr > 0:
        _, prev, tok = dp[curr]
        tokens.append(tok)
        curr = prev
    tokens.reverse()
    tokens.append(("eos", 0, 0))

    out = bytearray([0xF0])
    for g in range(0, len(tokens), 8):
        chunk = tokens[g : g + 8]
        flags = 0
        payload = bytearray()
        for bit, tok in enumerate(chunk):
            if tok[0] == "lit":
                payload.append(tok[1])
            elif tok[0] == "match":
                flags |= 1 << bit
                _, lcode, dist = tok
                payload.append((lcode << 4) | ((dist >> 8) & 0x0F))
                payload.append(dist & 0xFF)
            elif tok[0] == "eos":
                flags |= 1 << bit
                payload.append(0x00)
                payload.append(0x00)
        out.append(flags)
        out.extend(payload)
    return bytes(out)


def ldec_compress(raw: bytes) -> bytes:
    out = bytearray()
    for off in range(0, len(raw), 4096):
        out.extend(_ldec_compress_block(raw[off : off + 4096]))
    return bytes(out)


def load_icon_from_banks(banks: list[bytes], rid: int) -> tuple[int, int, int, int, int, int, int, bytes]:
    bank = (rid & 0xFFFF) // 0x2000
    idx = (rid & 0xFFFF) % 0x2000
    d = banks[bank]
    n1, _ = struct.unpack_from("<HH", d, 12)
    u16s = struct.unpack_from(f"<{n1}H", d, 16)
    table_start = (16 + n1 * 2 + 3) & ~3
    v = u16s[idx]
    pos = table_start + v * 4
    _, flags, wh, size, d_off = struct.unpack_from("<5I", d, pos)
    w = wh & 0x7FFF
    h = (wh >> 16) & 0x7FFF
    real_off = (pos + 4) + d_off
    aligned_w = (w + 15) & ~15
    blob = d[real_off : real_off + size]
    raw = decode_ldec(blob, aligned_w * h * 2)
    return w, h, aligned_w, flags, size, pos, real_off, raw


def _render_table_icon(banks: list[bytes], rid: int, donor: int, col: int, row: int, word: str) -> tuple[int, int, bytes]:
    w, h, aw, _, size, _, at, _ = load_icon_from_banks(banks, rid)
    bank = (rid & 65535) // 8192
    # If requested word is the original stock label ("IN" for row 7, "SH" for row 8), return exact stock bytes!
    if (row == 7 and word == "IN") or (row == 8 and word == "SH"):
        return at, size, banks[bank][at : at + size]

    dw, dh, daw, _, _, _, _, base = load_icon_from_banks(banks, donor)
    assert (w, h, aw) == (dw, dh, daw)
    data = list(struct.unpack(f"<{aw * h}H", base))
    if w == 70:
        left, right, top, bottom = 24, 49, 11, 27
        label_y, height = 12, 14
    elif w == 58:
        left, right, top, bottom = 19, 41, 8, 24
        label_y, height = 9, 14
    else:
        raise ValueError(f"Unreviewed icon size: {w}x{h}")
    shift = (5 if w == 70 else 4) if col else 0
    left += shift
    right += shift
    fill = 0
    ink = Counter(
        pixel
        for y in range(top, bottom)
        for pixel in data[y * aw + left : y * aw + right]
        if pixel >> 12 >= 8 and pixel & 15 == 15
    ).most_common(1)[0][0]
    for glyph_width, scale_y, outline in [(5, 2, 1), (5, 2, 0), (4, 2, 0)]:
        out = data.copy()
        for y in range(top, bottom):
            for x in range(left, right):
                out[y * aw + x] = fill
        width = len(word) * glyph_width + 2 * (len(word) - 1)
        x0 = (left + right - width) // 2
        pixels = set()
        for index, glyph in enumerate(word):
            for y in range(height):
                for x in range(glyph_width):
                    if DIGITS[glyph][y // scale_y][x * 5 // glyph_width] == "1":
                        pixels.add((x0 + index * (glyph_width + 2) + x, label_y + y))
        if outline:
            for x, y in pixels:
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if left <= nx < right and top <= ny < bottom:
                        out[ny * aw + nx] = 0x000C
        for x, y in pixels:
            out[y * aw + x] = ink
        raw = struct.pack(f"<{len(out)}H", *out)
        encoded = ldec_compress(raw)
        if len(encoded) <= size:
            encoded = encoded.ljust(size, b"\0")
            assert decode_ldec(encoded, len(raw)) == raw
            return at, size, encoded
    raise ValueError(f"Icon {rid:#x} ({word}) exceeds slot of {size} bytes")


def _render_extra_icon(banks: list[bytes], rid: int, donor: int, row: int, label: str) -> tuple[int, int, bytes]:
    w, h, aw, _, size, _, at, _ = load_icon_from_banks(banks, rid)
    bank = (rid & 65535) // 8192
    if (row == 7 and label == "IN") or (row == 8 and label == "SH"):
        return at, size, banks[bank][at : at + size]

    dw, dh, daw, _, _, _, _, donor_data = load_icon_from_banks(banks, donor)
    assert (w, h, aw) == (dw, dh, daw)
    if h == 27:
        left, right, top, bottom = 24, 44, 8, 21
        center, height = 13, 9
    elif h == 40:
        left, right, top, bottom = 21, 47, 14, 30
        center, height = 21, 14
    else:
        raise ValueError(f"Unexpected extra icon dimensions: {w}x{h}")
    base = list(struct.unpack(f"<{aw * h}H", donor_data))
    ink = Counter(
        v for y in range(top, bottom) for v in base[y * aw + left : y * aw + right] if v & 15 == 15 and v >> 12
    ).most_common(1)[0][0]
    for width, outline in [(5, True), (5, False), (4, False)]:
        out = base.copy()
        for y in range(top, bottom):
            out[y * aw + left : y * aw + right] = [0] * (right - left)
        glyph_width = len(label) * width + 2 * (len(label) - 1)
        start = (left + right - glyph_width) // 2
        y0 = center - height // 2
        pixels = {
            (start + i * (width + 2) + x, y0 + y)
            for i, g in enumerate(label)
            for y in range(height)
            for x in range(width)
            if DIGITS[g][y * 7 // height][x * 5 // width] == "1"
        }
        if outline:
            for x, y in pixels:
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if left <= nx < right and top <= ny < bottom:
                        out[ny * aw + nx] = 0x000B
        for x, y in pixels:
            out[y * aw + x] = ink
        raw = struct.pack(f"<{len(out)}H", *out)
        compressed = ldec_compress(raw)
        if len(compressed) <= size:
            encoded = compressed.ljust(size, b"\0")
            assert decode_ldec(encoded, len(raw)) == raw
            return at, size, encoded
    raise ValueError(f"Extra icon {rid:#x} ({label}) exceeds slot of {size} bytes")


def build_target_uxc_banks(
    research_root: Path,
    top_in: str = "FL2",
    top_sh: str = "FL3",
    bot_in: str = "FL2",
    bot_sh: str = "FL3",
) -> dict[str, dict]:
    """
    Build target bytes and slot tables for all 4 icon .uxc files:
      /usr/share/app/image_01_23_IPSX.uxc
      /usr/share/app/image_02_23_IPSX.uxc
      /usr/share/app/image_01_32_IPSX.uxc
      /usr/share/app/image_02_32_IPSX.uxc
    Uses a local disk cache keyed by (suffix, top_in, top_sh, bot_in, bot_sh) for instant reuse.
    """
    top_in = validate_icon_word(top_in, "上方槽位1图标")
    top_sh = validate_icon_word(top_sh, "上方槽位2图标")
    bot_in = validate_icon_word(bot_in, "下方槽位1图标")
    bot_sh = validate_icon_word(bot_sh, "下方槽位2图标")

    fl23 = research_root.parent / "fl23_research"
    share_dir = fl23 / "menu_resource_research/extracted/nflasha15/share/app"
    tables = json.loads((fl23 / "menu_renderer_research/creative_look_resource_tables.json").read_text(encoding="utf-8"))

    cache_dir = Path(__file__).resolve().parent / ".icon_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / f"slots_{top_in}_{top_sh}_{bot_in}_{bot_sh}.json"
    cached_slots: dict[str, dict[str, str]] | None = None
    if cache_file.is_file():
        try:
            cached_slots = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            cached_slots = None

    new_cache: dict[str, dict[str, str]] = {}
    result: dict[str, dict] = {}

    for suffix in ("23", "32"):
        stock_banks = [(share_dir / f"image_0{k}_{suffix}_IPSX.uxc").read_bytes() for k in range(3)]
        slots_by_bank: dict[int, list[tuple[int, int, int, bytes, int]]] = {1: [], 2: []}
        cache_sub = (cached_slots or {}).get(suffix, {})
        out_sub: dict[str, str] = {}

        for table in tables:
            for row in (7, 8):
                for col, rid in enumerate(table["rows"][row]):
                    word = (top_in if row == 7 else top_sh) if col > 0 else (bot_in if row == 7 else bot_sh)
                    bank = (rid & 65535) // 8192
                    w, h, aw, _, size, _, at, _ = load_icon_from_banks(stock_banks, rid)
                    ckey = f"{rid:#010x}:{word}"
                    if ckey in cache_sub:
                        encoded = bytes.fromhex(cache_sub[ckey])
                        assert len(encoded) == size
                    else:
                        at2, size2, encoded = _render_table_icon(
                            stock_banks, rid, table["rows"][6][col], col, row, word
                        )
                        assert (at2, size2) == (at, size)
                    out_sub[ckey] = encoded.hex()
                    slots_by_bank[bank].append((at, size, rid, encoded, aw * h * 2))

        for rid, donor, row in EXTRA_TARGETS:
            word = bot_in if row == 7 else bot_sh
            bank = (rid & 65535) // 8192
            w, h, aw, _, size, _, at, _ = load_icon_from_banks(stock_banks, rid)
            ckey = f"{rid:#010x}:{word}"
            if ckey in cache_sub:
                encoded = bytes.fromhex(cache_sub[ckey])
                assert len(encoded) == size
            else:
                at2, size2, encoded = _render_extra_icon(stock_banks, rid, donor, row, word)
                assert (at2, size2) == (at, size)
            out_sub[ckey] = encoded.hex()
            slots_by_bank[bank].append((at, size, rid, encoded, aw * h * 2))

        new_cache[suffix] = out_sub

        for bank in (1, 2):
            name = f"image_0{bank}_{suffix}_IPSX.uxc"
            cam_path = f"/usr/share/app/{name}"
            stock = stock_banks[bank]
            target = bytearray(stock)
            sorted_slots = sorted(slots_by_bank[bank], key=lambda item: item[0])
            last = 0
            for at, size, rid, encoded, _ in sorted_slots:
                assert last <= at and at + size <= len(stock)
                target[at : at + size] = encoded
                last = at + size
            result[cam_path] = {
                "path": cam_path,
                "name": name,
                "size": len(stock),
                "stock_bytes": stock,
                "stock_sha256": sha(stock),
                "target_bytes": bytes(target),
                "target_sha256": sha(target),
                "slots": [
                    {
                        "offset": at,
                        "length": size,
                        "rid": rid,
                        "stock_bytes": stock[at : at + size],
                        "target_bytes": encoded,
                        "raw_size": raw_size,
                    }
                    for at, size, rid, encoded, raw_size in sorted_slots
                ],
            }

    if cached_slots is None:
        cache_file.write_text(json.dumps(new_cache), encoding="utf-8")
    return result


def build_target_string_banks(
    research_root: Path,
    title_in: str = "FL2",
    title_sh: str = "FL3",
) -> dict[str, dict]:
    """
    Build target bytes and 4-byte slot tables for:
      /usr/share/app/string_simplifiedchinese_horizontal.uxc
      /usr/share/app/string_simplifiedchinese_vertical.uxc
    """
    title_in = validate_icon_word(title_in, "中央橙色标题(槽位1)")
    title_sh = validate_icon_word(title_sh, "中央橙色标题(槽位2)")
    fl23 = research_root.parent / "fl23_research"
    share_dir = fl23 / "menu_resource_research/extracted/nflasha15/share/app"

    in_bytes = title_in.encode("ascii").ljust(4, b"\0")
    sh_bytes = title_sh.encode("ascii").ljust(4, b"\0")

    result: dict[str, dict] = {}
    for orientation in ("horizontal", "vertical"):
        name = f"string_simplifiedchinese_{orientation}.uxc"
        cam_path = f"/usr/share/app/{name}"
        stock = (share_dir / name).read_bytes()
        target = bytearray(stock)
        slots = []
        for rid, old, new in [(0xA30A, b"IN\0\0", in_bytes), (0xA2FE, b"SH\0\0", sh_bytes)]:
            pattern = struct.pack("<I", 0x1E000000 | rid) + old
            assert stock.count(pattern) == 1
            at = stock.index(pattern) + 4
            target[at : at + 4] = new
            slots.append(
                {
                    "offset": at,
                    "length": 4,
                    "rid": 0x1E000000 | rid,
                    "stock_bytes": old,
                    "target_bytes": new,
                    "raw_size": 0,
                }
            )
        slots.sort(key=lambda item: item["offset"])
        result[cam_path] = {
            "path": cam_path,
            "name": name,
            "size": len(stock),
            "stock_bytes": stock,
            "stock_sha256": sha(stock),
            "target_bytes": bytes(target),
            "target_sha256": sha(target),
            "slots": slots,
        }
    return result


def verify_live_uxc_against_stock(bank_info: dict, live_bytes: bytes) -> None:
    """
    Verify that `live_bytes` from the camera is 100% identical to `stock_bytes` outside
    the known icon/string slots, and that every slot in `live_bytes` is a valid LDEC stream
    (or 4-byte ASCII string).
    """
    stock = bank_info["stock_bytes"]
    if len(live_bytes) != len(stock):
        raise ValueError(f"资源文件长度异常：{bank_info['name']}")
    masked = bytearray(live_bytes)
    for slot in bank_info["slots"]:
        at, length = slot["offset"], slot["length"]
        live_slot = live_bytes[at : at + length]
        if slot["raw_size"] > 0:
            try:
                decode_ldec(live_slot, slot["raw_size"])
            except Exception as exc:
                raise ValueError(f"相机图标槽位 {slot['rid']:#x} 解码校验失败：{exc}") from exc
        else:
            if not live_slot.endswith(b"\0"):
                raise ValueError(f"相机文字槽位 {slot['rid']:#x} 结尾校验失败")
        masked[at : at + length] = slot["stock_bytes"]
    if bytes(masked) != stock:
        raise ValueError(f"资源文件存在未知修改，拒绝写入：{bank_info['name']}")


def compile_and_simulate_uxc_batches(
    research_root: Path,
    work_dir: Path,
    cam_path: str,
    live_bytes: bytes,
    target_bytes: bytes,
    slots: list[dict],
    prefix: str,
) -> list[dict]:
    """
    Given verified `live_bytes` on the camera and `target_bytes` to achieve,
    find all slots that differ, group into batches of up to 18 windows,
    compile ARM64 `install{k}.so` and `restore{k}.so` workers via Zig,
    and run the 30-case Unicorn ARM64 simulation (`test_worker.py`) for every batch.
    """
    changed_windows: list[tuple[int, bytes, bytes]] = []
    for slot in slots:
        at, length = slot["offset"], slot["length"]
        old = live_bytes[at : at + length]
        new = target_bytes[at : at + length]
        if old != new:
            changed_windows.append((at, old, new))

    if not changed_windows:
        return []

    work_root = research_root.parent
    sys_paths = [str(work_root / "research_libs"), str(research_root)]
    for sp in reversed(sys_paths):
        if sp not in sys.path:
            sys.path.insert(0, sp)

    source_tpl = (research_root / "permanent_program_installer.c").read_text(encoding="utf-8")
    test_tpl = (research_root / "build_test_permanent_installer.py").read_text(encoding="utf-8").split("def main():")[0]
    zig_exe = work_root / "compiler_libs/ziglang/zig.exe"

    interim = bytearray(live_bytes)
    steps: list[dict] = []

    for i in range(0, len(changed_windows), 18):
        number = i // 18 + 1
        batch_dir = work_dir / f"{prefix}_part{number}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        windows = changed_windows[i : i + 18]

        before_hash = sha(interim)
        for at, old, new in windows:
            assert interim[at : at + len(old)] == old
            interim[at : at + len(new)] = new
        after_hash = sha(interim)

        (batch_dir / "before.uxc").write_bytes(
            live_bytes if number == 1 else (work_dir / f"{prefix}_part{number - 1}/after.uxc").read_bytes()
        )
        (batch_dir / "after.uxc").write_bytes(bytes(interim))
        (batch_dir / "plan.json").write_text(
            json.dumps(
                {"edits": [{"offset": at, "before_hex": a.hex(), "after_hex": b.hex()} for at, a, b in windows]}
            ),
            encoding="utf-8",
        )

        count = len(windows)
        source = (
            source_tpl.replace("changed[3]", f"changed[{count}]")
            .replace("n=3;n", f"n={count};n")
            .replace("i<3&&", f"i<{count}&&")
            .replace("/usr/lib/appFw.so", cam_path)
            .replace("93620512UL", str(len(live_bytes)) + "UL")
        )
        (batch_dir / "worker.c").write_text(source, encoding="utf-8")

        step_info: dict = {
            "before": before_hash,
            "after": after_hash,
            "windows": count,
        }

        for reverse in (False, True):
            suffix = "restore" if reverse else "install"
            result_path = f"/tmp/jiritsu/{prefix}_{number}_{suffix}.result"
            values = [(at, b, a) for at, a, b in reversed(windows)] if reverse else windows
            declarations = [
                "#define RESTORE_ORIGINAL_PROGRAM 1",
                f'#define INSTALL_RESULT_PATH "{result_path}"',
            ]
            entries = []
            for k, (at, a, b) in enumerate(values):
                for label, data in [("old", a), ("new", b)]:
                    declarations.append(f"static const u8 {label}{k}[]={{" + ",".join(map(str, data)) + "};")
                entries.append(f"{{{at}UL,{len(a)},old{k},new{k}}}")
            declarations.append("static const struct Window windows[]={" + ",".join(entries) + "};")
            header = f"manifest_{suffix}.h"
            (batch_dir / header).write_text("\n".join(declarations), encoding="ascii")
            binary = batch_dir / ("permanent_program_restore.so" if reverse else "permanent_program_installer.so")
            subprocess.run(
                [
                    str(zig_exe),
                    "cc",
                    "-target",
                    "aarch64-linux-gnu",
                    "-shared",
                    "-fPIC",
                    "-O2",
                    "-ffreestanding",
                    "-fno-builtin",
                    "-fno-stack-protector",
                    "-fno-unwind-tables",
                    "-fno-asynchronous-unwind-tables",
                    "-nostdlib",
                    "-g0",
                    "-Wl,--strip-debug",
                    "-Wl,--no-undefined",
                    "-Wl,-Bsymbolic",
                    "-Wl,-z,noexecstack",
                    "-I",
                    str(research_root),
                    f'-DPROGRAM_MANIFEST="{header}"',
                    "-o",
                    str(binary),
                    str(batch_dir / "worker.c"),
                ],
                check=True,
                capture_output=True,
                timeout=120,
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            )
            blob = binary.read_bytes()
            if not (0 < len(blob) <= 65536):
                raise ValueError(f"辅助程序体积异常：{len(blob)}")
            step_info[suffix] = {
                "file": f"{prefix}_{suffix}{number}.so",
                "sha256": sha(blob),
                "result": result_path,
                "blob": blob,
            }

        step_info["stage"] = step_info["install"]["result"].removesuffix(".result") + ".stage.so"

        harness = (
            test_tpl.replace("str(ROOT.parent/'research_libs')", repr(str(work_root / "research_libs")))
            .replace("ROOT/'permanent_boot_plan.json'", "ROOT/'plan.json'")
            .replace("AUDIO=(ROOT.parent/'full_audio/project11_full_filter0.bin').read_bytes()", "AUDIO=b''")
            .replace("/usr/lib/appFw.so", cam_path)
            .replace("93620512", str(len(live_bytes)))
            .replace("==r['applied']==3", f"==r['applied']=={count}")
            .replace("==[0,1,2]", f"==list(range({count}))")
            .replace("/tmp/jiritsu/zve10m2.bootinstall.result", step_info["install"]["result"])
            .replace("/tmp/jiritsu/zve10m2.bootrestore.result", step_info["restore"]["result"])
        )
        harness_path = batch_dir / "test_worker.py"
        harness_path.write_text(harness, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(f"icon_worker_{prefix}_{number}", harness_path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        cases = (
            "success",
            "already_mode_zero",
            "existing_result",
            "valid_wbi",
            "wrong_device",
            "wrong_program",
            "mode_failure",
            "remount_failure",
            "changed_inode",
            "journal_sync_failure",
            "guard_partial",
            "header_partial",
            "program_sync_failure",
            "readonly_failure",
            "program_close_failure",
        )
        for reverse in (False, True):
            for case in cases:
                m.run(case, restore=reverse)
        steps.append(step_info)

    assert bytes(interim) == target_bytes
    return steps
