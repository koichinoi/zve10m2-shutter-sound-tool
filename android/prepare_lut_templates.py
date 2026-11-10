"""Build and check native worker templates whose data windows can be filled on Android."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("desktop", type=Path)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.desktop.resolve()))
    import backend
    from filter_install import _compile_and_verify_custom_cp_workers
    from filters.cube_converter import ST_B13, ST_CC1, ST_SLOT6

    output = args.output
    output.mkdir()
    manifest = backend.load(args.prepared / "manifest.json")
    cp = copy.deepcopy(manifest["components"][0])
    for index, edit in enumerate(cp["edits"]):
        for side in ("before", "after"):
            seed = f"zve10m2 android lut template {index} {side}".encode()
            edit[side + "_hex"] = hashlib.shake_256(seed).hexdigest(edit["length"])
    apply, restore = _compile_and_verify_custom_cp_workers(
        backend, backend.WORK / "fl23_research", output / "verify", cp,
    )
    from elftools.elf.elffile import ELFFile
    meta = {}
    for name, blob in (("cp", apply), ("restore", restore)):
        path = output / (name + ".so")
        path.write_bytes(blob)
        with path.open("rb") as stream:
            rodata = ELFFile(stream).get_section_by_name(".rodata")
            start, size = rodata["sh_offset"], rodata["sh_size"]
        rows = []
        for edit in cp["edits"]:
            offsets = []
            for side in ("before", "after"):
                pattern = bytes.fromhex(edit[side + "_hex"])
                pos = blob.find(pattern)
                if pos < start or pos + len(pattern) > start + size or blob.count(pattern) != 1:
                    raise ValueError("Template data must occur once in read-only data")
                offsets.append(pos)
            rows.append({"offset": edit["offset"], "length": edit["length"], "positions": offsets})
        meta[name] = {"sha256": backend.sha(blob), "rows": rows}
    baseline = struct.pack("<129I", *ST_SLOT6)
    baseline += struct.pack("<288h", *(x for group in ST_B13 for row in group for x in row))
    baseline += struct.pack("<24h", *(x for row in ST_CC1 for x in row)) + bytes(16)
    (output / "baseline.bin").write_bytes(baseline)
    meta["baseline_hash"] = backend.sha(baseline)
    (output / "manifest.json").write_text(json.dumps(meta), encoding="utf-8")


if __name__ == "__main__":
    main()
