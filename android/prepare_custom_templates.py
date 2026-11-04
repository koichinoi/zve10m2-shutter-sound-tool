"""Build local Android templates using the reviewed desktop sources and compiler."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory


def marker(name, length):
    return hashlib.shake_256(name.encode("ascii")).digest(length)


def data_source(path, fields):
    path.write_text("\n".join(
        f'__attribute__((visibility("hidden"))) const unsigned char {name}[] = '
        + "{" + ",".join(map(str, content)) + "};"
        for name, content in fields.items()), encoding="ascii")


def offsets(blob, fields):
    result = {}
    for name, content in fields.items():
        if blob.count(content) != 1:
            raise ValueError(f"Template marker not unique: {name} ({blob.count(content)})")
        result[name] = blob.index(content)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("desktop", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.desktop.resolve()))
    backend = importlib.import_module("backend")
    research = backend.RESEARCH
    off = backend.OFF
    base = ["-target", "aarch64-linux-gnu", "-O2", "-fno-lto", "-fPIC", "-ffreestanding",
            "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables",
            "-fno-asynchronous-unwind-tables", "-nostdlib", "-g0", "-Wl,--no-undefined"]
    audio_path = "/cp/zvs_" + "0" * 16 + ".bin"
    result_path = "/tmp/jiritsu/zvs_mobile_" + "0" * 16 + ".result"
    sizes = [0xb00, 16, 4]
    with TemporaryDirectory(prefix="zve-custom-") as work:
        work = Path(work)
        guard_fields = {"mobile_path": marker("guard-path", len(audio_path)+1),
                        "mobile_crc": marker("guard-crc", 16)}
        guard_c = (research/"permanent_boot_guard.c").read_text(encoding="utf-8").replace(
            'static const char path[]="/cp/zve10m2_project11_full.bin";',
            f'__attribute__((visibility("hidden"))) extern const char mobile_path[{len(audio_path)+1}];\n'
            '__attribute__((visibility("hidden"))) extern const u8 mobile_crc[16];\n#define path mobile_path').replace("0x0051ac92U", "((u32)mobile_crc[0]|(u32)mobile_crc[1]<<8|(u32)mobile_crc[2]<<16|(u32)mobile_crc[3]<<24)")
        (work/"guard.c").write_text(guard_c, encoding="ascii")
        data_source(work/"guard_data.c", guard_fields)
        backend.run([backend.CFG["zig"], "cc", *base, "-fvisibility=hidden", "-static", "-no-pie",
                     "-Wl,--build-id=none", "-Wl,-T,"+str(research/"permanent_boot_guard.ld"),
                     "-o", work/"guard.elf", research/"permanent_boot_guard.S",
                     work/"guard.c", work/"guard_data.c"], timeout=120)
        from elftools.elf.elffile import ELFFile
        with (work/"guard.elf").open("rb") as stream:
            elf = ELFFile(stream)
            section = elf.get_section_by_name(".guard")
            guard = section.data()
            if section["sh_addr"] != off or not 0 < len(guard) <= sizes[0]:
                raise ValueError("Guard exceeded approved window")
            if any(s["sh_type"] in ("SHT_REL", "SHT_RELA", "SHT_DYNAMIC") for s in elf.iter_sections()):
                raise ValueError("Guard requires relocations")
        guard_offsets = offsets(guard, guard_fields)

        fields = {"mobile_audio_path": marker("audio-path", len(audio_path)+1),
                  "mobile_result": marker("result-path", len(result_path)+1),
                  "audio_payload": marker("audio", 15360)}
        for side in ("old", "new"):
            fields.update({f"{side}_{i}": marker(f"{side}_{i}", size) for i, size in enumerate(sizes)})
        header = "\n".join(f'extern const u8 {name}[{len(value)}];' for name, value in fields.items())
        windows = ",\n".join(f'{{{position}UL,{size},old_{i},new_{i}}}'
                            for i, (position, size) in enumerate(zip([off, 0x60, 0x2d5039c], sizes)))
        header += "\nstatic const struct Window windows[] = {\n"+windows+"\n};\n"
        (work/"permanent_program_manifest.h").write_text(header, encoding="ascii")
        installer = (research/"permanent_program_installer.c").read_text(encoding="utf-8").replace(
            '"/cp/zve10m2_project11_full.bin"', "(const char*)mobile_audio_path").replace(
            '"/tmp/jiritsu/zve10m2.bootinstall.result"', "(const char*)mobile_result")
        (work/"worker.c").write_text(installer, encoding="ascii")
        data_source(work/"worker_data.c", fields)
        backend.run([backend.CFG["zig"], "cc", *base, "-shared", "-I", research,
                     "-Wl,--strip-debug", "-Wl,-Bsymbolic", "-Wl,-z,noexecstack",
                     "-o", work/"worker.so", work/"worker.c", work/"worker_data.c"], timeout=120)
        worker = (work/"worker.so").read_bytes()
        if not 0 < len(worker) <= 65536:
            raise ValueError("Worker exceeded mobile transfer limit")
        worker_offsets = offsets(worker, fields)

        states = [backend.current_state(), backend.load(backend.ROOT/"previous.json")]
        if any(state.get("factory") for state in states) or backend.bank_hash(states[0]) != backend.bank_hash(states[1]):
            raise ValueError("Expected two known custom states with the same bank")
        for state in states:
            backend.materialize(state)
        before = [{"app": state["app_sha256"], "audio": state["audio_path"], "hash": state["audio_sha256"]}
                  for state in states]
        pins = {path: [size, digest] for path, (size, digest) in backend.state_pins(states[0]).items()}
        manifest = {"guard_offsets": guard_offsets, "worker_offsets": worker_offsets,
                    "known": before, "pins": pins, "guard_base": off,
                    "guard_hash": hashlib.sha256(guard).hexdigest(),
                    "worker_hash": hashlib.sha256(worker).hexdigest()}
        args.output.mkdir()
        (args.output/"manifest.json").write_text(json.dumps(manifest), encoding="ascii")
        (args.output/"guard.bin").write_bytes(guard)
        (args.output/"worker.so").write_bytes(worker)


if __name__ == "__main__":
    main()
