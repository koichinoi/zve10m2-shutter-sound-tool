"""Collect the verified desktop FL2/FL3 resources for a local Android build."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import zipfile


def previous_install(backend, operation):
    report = backend.load(operation / "report.json")
    if not report.get("complete") or report.get("phase") != "complete_readback_verified":
        raise ValueError("Use a Windows operation that completed writing and readback")
    with zipfile.ZipFile(operation / "before.zip") as backup:
        components = json.loads(backup.read("candidate_plan.json"))["components"]
        pins = {}
        required = ("usr/lib/appFw.so", "usr/lib/libJiritsu.so", "cp/SysSound.bin")
        for name in backup.namelist():
            if name in required or name == "cp/zve10m2_project11_full.bin" or (
                name.startswith("cp/zvs_") and name.endswith(".bin")
            ):
                data = backup.read(name)
                pins["/" + name] = [len(data), backend.sha(data)]
        if any("/" + name not in pins for name in required):
            raise ValueError("The Windows backup is missing a protected file")
    folder = operation / "custom_lut_build_live"
    if not folder.is_dir():
        folder = operation / "custom_lut_build"
    sources = [(folder / component["file"]).read_bytes() for component in components]
    for data, component in zip(sources, components):
        if backend.sha(data) != component["candidate_sha256"]:
            raise ValueError("Previous candidate differs from the verified plan")
    return sources, pins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("desktop", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--in-cube", type=Path)
    parser.add_argument("--sh-cube", type=Path)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--from-operation", type=Path, help="Completed Windows LUT installation on the target camera")
    source.add_argument("--from-prepared", type=Path, help="Use the target of an earlier local package as the source")
    args = parser.parse_args()
    sys.path.insert(0, str(args.desktop.resolve()))
    backend = importlib.import_module("backend")
    installer = importlib.import_module("filter_install")
    custom = bool(args.in_cube or args.sh_cube)
    if custom != bool(args.from_operation or args.from_prepared):
        parser.error("Preparing custom LUTs requires a source and at least one .cube")
    args.output.mkdir()
    sources, protected = None, None
    if args.from_operation:
        sources, protected = previous_install(backend, args.from_operation)
    elif args.from_prepared:
        prior = backend.load(args.from_prepared / "manifest.json")
        components = prior["components"]
        sources = [(args.from_prepared / "verified-build" / part["file"]).read_bytes()
                   for part in components]
        for data, part in zip(sources, components):
            if backend.sha(data) != part["candidate_sha256"]:
                raise ValueError("Prepared candidate differs from its manifest")
        protected = prior["protected"]
    host, _, pins, reviewed, _, workers, _, inverse = installer.load_resources(
        backend, in_cube_path=args.in_cube, sh_cube_path=args.sh_cube,
        live_cp_bytes=sources[0] if custom else None,
        build_dir=args.output / "verified-build" if custom else None,
    )
    manifest = {"components": reviewed["components"], "transport": pins, "workers": {}}
    if custom:
        settings = host.settings_plan
        stored = settings.parse_snapshot(
            (args.from_operation / "after-save-stored.private.bin").read_bytes(),
            args.from_operation.name, 1, 0, False,
        ) if args.from_operation else None
        for index, key in enumerate(settings.KEYS, 1):
            component = reviewed["components"][index]
            if stored is not None and stored.properties[1, key].data != sources[index]:
                raise ValueError("Previous color unit differs from camera readback")
            original = (backend.ROOT / "filter_originals" / f"unit-{key:08x}.bin").read_bytes()
            if backend.sha(original) != component["source_sha256"]:
                raise ValueError("Original color unit does not match the reviewed baseline")
            normalized = bytearray(sources[index])
            for edit in component["edits"]:
                offset = edit["offset"]
                end = offset + edit["length"]
                edit["before_hex"] = sources[index][offset:end].hex()
                normalized[offset:end] = original[offset:end]
            if bytes(normalized) != original:
                raise ValueError("Previous color unit has changes outside the supported windows")
            component["source_sha256"] = backend.sha(sources[index])
        manifest["protected"] = protected
        manifest["lut_labels"] = [path.stem if path else label for path, label in (
            (args.in_cube, "FL2"), (args.sh_cube, "FL3"),
        )]
    for name, (stage, result, data) in workers.items():
        if len(data) > 65536:
            raise ValueError("Worker exceeds Android transfer limit")
        (args.output / (name + ".so")).write_bytes(data)
        manifest["workers"][name] = {"stage": stage, "result": result, "sha256": hashlib.sha256(data).hexdigest()}
    (args.output / "restore.so").write_bytes(inverse)
    manifest["restore_hash"] = hashlib.sha256(inverse).hexdigest()
    (args.output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


if __name__ == "__main__":
    main()
