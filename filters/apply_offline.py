"""Apply the published FL2/FL3 profile data to local copies of matching files."""
import argparse
import hashlib
import json
from pathlib import Path

PROFILES = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def apply_profiles(source, destination, looks):
    if destination.exists():
        raise ValueError("Output directory must not already exist.")

    profiles = [
        json.loads((PROFILES / f"{look}.json").read_text(encoding="utf-8"))
        for look in looks
    ]
    originals = profiles[0]["components"]
    output_files = {}
    for index, original in enumerate(originals):
        name = original["input_file"]
        data = (source / name).read_bytes()
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

        expected = original["both_looks_sha256" if len(profiles) == 2 else "single_look_sha256"]
        if digest(candidate) != expected:
            raise ValueError(f"{name}: output SHA-256 does not match.")
        output_files[name] = candidate

    destination.mkdir()
    for name, candidate in output_files.items():
        (destination / name).write_bytes(candidate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Directory containing original research files")
    parser.add_argument("destination", type=Path, help="New directory for patched copies")
    parser.add_argument("--look", choices=("FL2", "FL3", "both"), default="both")
    args = parser.parse_args()
    looks = ("FL2", "FL3") if args.look == "both" else (args.look,)
    try:
        apply_profiles(args.source, args.destination, looks)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
