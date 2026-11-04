"""Build a camera-specific, offline-tested shutter change for a local Android APK."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import uuid
import sys
from tempfile import TemporaryDirectory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("desktop", type=Path, help="Configured desktop tool directory")
    parser.add_argument("target", type=Path, help="Previously prepared desktop state.json")
    parser.add_argument("output", type=Path, help="New output directory")
    args = parser.parse_args()
    desktop = args.desktop.resolve()
    sys.path.insert(0, str(desktop))
    backend = importlib.import_module("backend")
    if (desktop / "pending.json").exists():
        raise ValueError("Resolve the pending desktop operation first")
    before = backend.current_state()
    after = backend.load(args.target.resolve())
    backend.materialize(before)
    backend.materialize(after)
    if before["app_sha256"] == after["app_sha256"] or before.get("factory") or after.get("factory"):
        raise ValueError("Select a different custom sound")
    if backend.bank_hash(before) != backend.bank_hash(after):
        raise ValueError("The prepared sound requires a different sound bank")
    audio = Path(after["audio_file"]).read_bytes()
    if hashlib.sha256(audio).hexdigest() != after["audio_sha256"]:
        raise ValueError("Audio payload does not match the prepared state")

    with TemporaryDirectory(prefix="zve-mobile-plan-") as directory:
        stage = Path(directory)
        forward = stage / ("mobile_" + uuid.uuid4().hex[:16])
        inverse = stage / "inverse"
        forward.mkdir()
        inverse.mkdir()
        worker, result, _ = backend.build_worker(forward, before, after)
        backend.build_worker(inverse, after, before)
        if not 0 < len(worker) <= 65536:
            raise ValueError("Worker exceeds the mobile transfer limit")
        pins = {path: [size, digest] for path, (size, digest) in backend.state_pins(before).items()}
        pins["/usr/lib/appFw.so"] = [93620512, before["app_sha256"]]
        manifest = {
            "name": after["name"], "pins": pins, "target_app": after["app_sha256"],
            "result": result, "old_audio": before["audio_path"], "old_audio_hash": before["audio_sha256"],
            "audio": after["audio_path"], "audio_hash": after["audio_sha256"],
            "worker_hash": hashlib.sha256(worker).hexdigest(),
        }
        args.output.mkdir()
        (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        (args.output / "worker.so").write_bytes(worker)
        (args.output / "audio.bin").write_bytes(audio)


if __name__ == "__main__":
    main()
