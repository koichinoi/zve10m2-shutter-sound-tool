"""Collect the verified desktop FL2/FL3 resources for a local Android build."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("desktop", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.desktop.resolve()))
    backend = importlib.import_module("backend")
    _, _, pins, reviewed, _, workers, _, inverse = importlib.import_module("filter_install").load_resources(backend)
    args.output.mkdir()
    manifest = {"components": reviewed["components"], "transport": pins, "workers": {}}
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
