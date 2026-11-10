"""Apply the published FL2/FL3 profile data or custom .cube 3D LUTs to local copies of matching files."""
import argparse
import hashlib
import json
from pathlib import Path
from filters.cube_converter import (
    CubeLUT3D,
    build_custom_manifest,
    encode_ap_lut_file,
    encode_cp_3dlut_unit,
    simulate_cp_create_3dlut,
)

PROFILES = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def apply_profiles(
    source,
    destination,
    looks=("FL2", "FL3"),
    in_cube_path=None,
    sh_cube_path=None,
):
    source = Path(source)
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Output directory must not already exist.")

    base_bundle = json.loads((PROFILES / "FL2-FL3.json").read_text(encoding="utf-8"))
    in_lut = CubeLUT3D.from_file(in_cube_path) if in_cube_path else None
    sh_lut = CubeLUT3D.from_file(sh_cube_path) if sh_cube_path else None
    custom_mode = in_lut is not None or sh_lut is not None

    bundle = (
        build_custom_manifest(base_bundle, in_cube=in_lut, sh_cube=sh_lut)
        if custom_mode
        else base_bundle
    )
    profiles = [bundle[look] for look in looks]
    originals = profiles[0]["components"]
    output_files = {}
    component_sha256 = {}

    for index, original in enumerate(originals):
        name = original["input_file"]
        src_path = source / name
        if not src_path.is_file() and name == "cpapp-b.bin" and (source / "cp_cpapp-b.bin").is_file():
            src_path = source / "cp_cpapp-b.bin"
        data = src_path.read_bytes()
        if len(data) != original["bytes"] or digest(data) != original["source_sha256"]:
            raise ValueError(f"{name}: source size or SHA-256 does not match.")

        candidate = bytearray(data)
        occupied = set()
        for profile in profiles:
            component = profile["components"][index]
            if component["input_file"] != name or component["source_sha256"] != original["source_sha256"]:
                raise ValueError(f"{name}: profiles reference different sources.")
            for edit in component["edits"]:
                start = edit["offset"]
                end = start + edit["length"]
                replacement = bytes.fromhex(edit["after_hex"])
                offsets = set(range(start, end))
                if not 0 <= start < end <= len(data) or len(replacement) != end - start or occupied & offsets:
                    raise ValueError(f"{name}: invalid or overlapping edit.")
                candidate[start:end] = replacement
                occupied.update(offsets)

        cand_sha = digest(candidate)
        if not custom_mode:
            expected = original["both_looks_sha256" if len(profiles) == 2 else "single_look_sha256"]
            if cand_sha != expected:
                raise ValueError(f"{name}: output SHA-256 does not match.")
        output_files[name] = candidate
        component_sha256[name] = cand_sha

    destination.mkdir(parents=True)
    for name, candidate in output_files.items():
        (destination / name).write_bytes(candidate)

    if custom_mode:
        lut_exports = {}
        for slot_label, unit_name, ap_name, lut in (
            ("IN_FL2", "unit-02a40006.bin", "LUT001_IN.LUT", in_lut),
            ("SH_FL3", "unit-02a40007.bin", "LUT002_SH.LUT", sh_lut),
        ):
            if lut is None:
                continue
            unit_bytes = encode_cp_3dlut_unit(lut)
            ap_bytes = encode_ap_lut_file(lut)
            hw_words = simulate_cp_create_3dlut(unit_bytes)
            (destination / unit_name).write_bytes(unit_bytes)
            (destination / ap_name).write_bytes(ap_bytes)
            lut_exports[slot_label] = {
                "title": lut.title,
                "size": lut.size,
                "cp_3dlut_unit": unit_name,
                "cp_3dlut_sha256": digest(unit_bytes),
                "cp_3dlut_nonzero_hw_words": sum(1 for w in hw_words if w != 0),
                "ap_lut_file": ap_name,
                "ap_lut_sha256": digest(ap_bytes),
            }
        summary = {
            "mode": "CUSTOM_CUBE_LUT_SOOC",
            "looks": list(looks),
            "in_cube": str(in_cube_path) if in_cube_path else None,
            "sh_cube": str(sh_cube_path) if sh_cube_path else None,
            "component_sha256": component_sha256,
            "lut_exports": lut_exports,
        }
        (destination / "custom_lut_report.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return output_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Directory containing original research files")
    parser.add_argument("destination", type=Path, help="New directory for patched copies")
    parser.add_argument("--look", choices=("FL2", "FL3", "both"), default="both")
    parser.add_argument("--in-cube", type=Path, default=None, help="Optional .cube 3D LUT for IN (FL2) slot")
    parser.add_argument("--sh-cube", type=Path, default=None, help="Optional .cube 3D LUT for SH (FL3) slot")
    args = parser.parse_args()
    looks = ("FL2", "FL3") if args.look == "both" else (args.look,)
    try:
        apply_profiles(
            args.source,
            args.destination,
            looks,
            in_cube_path=args.in_cube,
            sh_cube_path=args.sh_cube,
        )
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
