"""End-to-end offline Unicorn verification for custom .cube LUT conversion & SOOC pipeline.
No camera USB access.
"""
import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent
_CFG = json.loads((TOOL_ROOT / "config.json").read_text(encoding="utf-8"))
WORK_ROOT = Path(_CFG["research"]).parent
FL23_RESEARCH = WORK_ROOT / "fl23_research"
LUT_RESEARCH = TOOL_ROOT.parent / "lut_research"

sys.path[:0] = [
    str(TOOL_ROOT),
    str(WORK_ROOT / "research_libs"),
    str(WORK_ROOT / "firmware_research"),
    str(FL23_RESEARCH),
]

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_R3,
    UC_ARM_REG_R5,
    UC_ARM_REG_R6,
    UC_ARM_REG_SP,
    UC_ARM_REG_LR,
)
from filters.cube_converter import (
    CubeLUT3D,
    build_custom_manifest,
    encode_ap_lut_file,
    encode_cp_3dlut_unit,
    ensure_sample_cube_files,
    simulate_cp_create_3dlut,
)
from filters.apply_offline import apply_profiles


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CustomLutOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cp_bin = (FL23_RESEARCH / "live_colour_20261027_225506_564406/cp_cpapp-b.bin").read_bytes()
        assert sha256(cls.cp_bin) == "99a1d5ac2f1c873cb560cdb8983c9f001fcdf3efbc1f0b68a323fbfb86f7331c"
        cls.base_manifest = json.loads((TOOL_ROOT / "filters/FL2-FL3.json").read_text(encoding="utf-8"))
        cls.luts_dir = TOOL_ROOT / "filters/luts"
        ensure_sample_cube_files(cls.luts_dir, cls.base_manifest)

    def test_01_unicorn_create3dlut_matches_python_reference(self):
        for cube_name in (
            "03_富士经典正片_纪实街拍.cube",
            "12_好莱坞电影青橙_冷暖对比.cube",
            "01_富士胶片2号_原厂移植.cube",
            "02_富士胶片3号_原厂移植.cube",
        ):
            with self.subTest(cube=cube_name):
                lut = CubeLUT3D.from_file(self.luts_dir / cube_name)
                unit = encode_cp_3dlut_unit(lut)
                self.assertEqual(len(unit), 1280)

                cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
                cpu.mem_map(0x225000, 0x2000)
                cpu.mem_write(0x225000, self.cp_bin[0x11D000:0x11F000])
                cpu.mem_map(0xE3B000, 0x1000)
                cpu.mem_write(0xE3B000, self.cp_bin[0xD33000:0xD34000])
                cpu.mem_map(0x01675000, 0x2000)
                lut_addr = 0x0167595B
                cpu.mem_write(lut_addr, unit)
                cpu.mem_map(0x18000000, 0x10000)
                cpu.reg_write(UC_ARM_REG_SP, 0x18008000)
                cpu.reg_write(UC_ARM_REG_LR, 0x226500 | 1)

                r0_addr, s0_addr, s0_4_addr = 0x18001000, 0x18001100, 0x18001200
                cpu.mem_write(r0_addr, struct.pack("<II", s0_addr, s0_4_addr))
                cpu.mem_write(s0_addr + 0x33, b"\x08")
                cpu.mem_write(s0_4_addr + 6, b"\x01")

                r1_addr, s1_8_addr, s1_c_addr, s1_10_addr = 0x18002000, 0x18002100, 0x18003000, 0x18002300
                cpu.mem_write(r1_addr + 8, struct.pack("<III", s1_8_addr, s1_c_addr, s1_10_addr))
                cpu.mem_write(s1_8_addr + 0x184, struct.pack("<IBB", lut_addr, 1, 2))

                cpu.reg_write(UC_ARM_REG_R0, r0_addr)
                cpu.reg_write(UC_ARM_REG_R1, r1_addr)
                cpu.emu_start(0x225BD0 | 1, 0x226500)

                out_bytes = cpu.mem_read(s1_c_addr + 0x5C, 405 * 4)
                emu_words = list(struct.unpack("<405I", out_bytes))
                py_words = simulate_cp_create_3dlut(unit)
                self.assertEqual(emu_words, py_words)

    def test_02_apply_profiles_and_bank_consumer_verification(self):
        in_cube = self.luts_dir / "03_富士经典正片_纪实街拍.cube"
        sh_cube = self.luts_dir / "12_好莱坞电影青橙_冷暖对比.cube"
        cand_dir = FL23_RESEARCH / "in_sh_replacement_candidate_v1"
        report_meta = json.loads((cand_dir / "report.json").read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as td:
            src_dir = Path(td) / "source"
            src_dir.mkdir()
            (src_dir / "cpapp-b.bin").write_bytes(self.cp_bin)
            for idx, name in ((1, "unit-02a40001.bin"), (2, "unit-02a4000d.bin")):
                comp = report_meta["components"][idx]
                raw = bytearray((cand_dir / comp["file"]).read_bytes())
                for e in comp["edits"]:
                    raw[e["offset"] : e["offset"] + e["length"]] = bytes.fromhex(e["before_hex"])
                assert sha256(bytes(raw)) == comp["source_sha256"]
                (src_dir / name).write_bytes(bytes(raw))

            out_dir = Path(td) / "patched_custom"
            apply_profiles(
                src_dir,
                out_dir,
                looks=("FL2", "FL3"),
                in_cube_path=in_cube,
                sh_cube_path=sh_cube,
            )
            self.assertTrue((out_dir / "custom_lut_report.json").is_file())
            self.assertEqual((out_dir / "unit-02a40006.bin").stat().st_size, 1280)
            self.assertEqual((out_dir / "unit-02a40007.bin").stat().st_size, 1280)
            self.assertEqual((out_dir / "LUT001_IN.LUT").stat().st_size, 48000)
            self.assertEqual((out_dir / "LUT002_SH.LUT").stat().st_size, 48000)

            u1 = (out_dir / "unit-02a40001.bin").read_bytes()
            ud = (out_dir / "unit-02a4000d.bin").read_bytes()

            # Verify native CP bank consumer selection on patched custom LUT units
            for parameter, bank in ((43, 23), (47, 23), (44, 25), (48, 25)):
                for matrix, slot in [(False, 0)] + [(True, i) for i in range(16)]:
                    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
                    cpu.mem_map(0x608000, 0x2000)
                    cpu.mem_write(0x608000, self.cp_bin[0x608000:0x60A000])
                    cpu.mem_map(0x136C000, 0xC000)
                    cpu.mem_write(0x136CF34, u1)
                    cpu.mem_write(0x136F434, ud)
                    cpu.mem_map(0x18000000, 0x10000)
                    cpu.reg_write(UC_ARM_REG_SP, 0x18008000)
                    stops = []
                    end = 0x6086F4 if matrix else 0x6088FE

                    def hook(machine, address, size, _, target_end=end, stop_list=stops):
                        if address == target_end:
                            stop_list.append(address)
                            machine.emu_stop()

                    cpu.hook_add(UC_HOOK_CODE, hook)
                    if matrix:
                        cpu.reg_write(UC_ARM_REG_R1, slot)
                        cpu.reg_write(UC_ARM_REG_R2, 0x18001000)
                        cpu.reg_write(UC_ARM_REG_R3, parameter)
                        cpu.emu_start(0x608640 | 1, 0x608800, count=150)
                        want = 0x136F434 + 0x1E0 + bank * 768 + slot * 12
                        got = cpu.reg_read(UC_ARM_REG_R1)
                        self.assertEqual(cpu.reg_read(UC_ARM_REG_R5), bank)
                    else:
                        cpu.reg_write(UC_ARM_REG_R6, parameter)
                        cpu.emu_start(0x6088B2 | 1, 0x608900, count=150)
                        want = 0x136CF34 + 0x1250 + bank * 64
                        got = cpu.reg_read(UC_ARM_REG_R0)
                    self.assertEqual(stops, [end])
                    self.assertEqual(got, want)

    def test_03_custom_cp_worker_compile_and_unicorn_arm64(self):
        import backend as b
        import filter_install

        in_cube = self.luts_dir / "03_富士经典正片_纪实街拍.cube"
        sh_cube = self.luts_dir / "12_好莱坞电影青橙_冷暖对比.cube"
        with tempfile.TemporaryDirectory() as td:
            res = filter_install.load_resources(
                b,
                in_cube_path=in_cube,
                sh_cube_path=sh_cube,
                build_dir=Path(td) / "worker_build",
            )
            _, _, _, reviewed, targets, blobs, _, inverse = res
            self.assertEqual(len(targets), 2)
            self.assertTrue(len(blobs["cp"][2]) > 1000)
            self.assertTrue(len(inverse) > 1000)
            self.assertNotEqual(
                reviewed["components"][0]["candidate_sha256"],
                "3e3d1f7db67f3831708ec4cab85ac4acc59229a26e6519be6dac3dc7ae72b636",
            )

    def test_04_icon_builder_and_unicorn_arm64(self):
        import backend as b
        from filters.icon_builder import (
            build_target_string_banks,
            build_target_uxc_banks,
            compile_and_simulate_uxc_batches,
            verify_live_uxc_against_stock,
        )

        fl_banks = build_target_uxc_banks(b.RESEARCH, "FL2", "FL3", "FL2", "FL3")
        diff_banks = build_target_uxc_banks(b.RESEARCH, "IN", "SH", "FL2", "FL3")
        for path, info in diff_banks.items():
            verify_live_uxc_against_stock(info, fl_banks[path]["target_bytes"])
            verify_live_uxc_against_stock(info, info["target_bytes"])

        str_banks = build_target_string_banks(b.RESEARCH, "L1", "L2")
        for path, sinfo in str_banks.items():
            verify_live_uxc_against_stock(sinfo, sinfo["target_bytes"])
            with tempfile.TemporaryDirectory() as td:
                steps = compile_and_simulate_uxc_batches(
                    b.RESEARCH,
                    Path(td),
                    path,
                    sinfo["stock_bytes"],
                    sinfo["target_bytes"],
                    sinfo["slots"],
                    "teststr",
                )
                self.assertEqual(len(steps), 1)
                self.assertEqual(steps[0]["windows"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
