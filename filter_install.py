"""Install the reviewed pair of creative looks or custom .cube 3D LUTs through the local service tools."""
import copy
import json
import re
import shutil
import struct
import sys
import time
import uuid
import zipfile
from pathlib import Path
from filters.cube_converter import (
    CubeLUT3D,
    build_custom_manifest,
    encode_ap_lut_file,
    encode_cp_3dlut_unit,
    simulate_cp_create_3dlut,
)


def _compile_and_verify_custom_cp_workers(backend, research, build_dir, cp_component):
    """Compile custom cp_data_apply.so and cp_data_restore.so and verify both in Unicorn ARM64."""
    sys.path[:0] = [str(backend.WORK / 'research_libs'), str(backend.WORK / 'firmware_research')]
    from build_and_verify_maps_probe import audit
    from elftools.elf.elffile import ELFFile
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_INTR, UC_HOOK_CODE
    from unicorn.arm64_const import (
        UC_ARM64_REG_X0,
        UC_ARM64_REG_X1,
        UC_ARM64_REG_X2,
        UC_ARM64_REG_X3,
        UC_ARM64_REG_X8,
        UC_ARM64_REG_X30,
        UC_ARM64_REG_SP,
        UC_ARM64_REG_PC,
    )

    build_dir.mkdir(parents=True, exist_ok=True)
    cp_dir = research / 'cp_worker_v1'
    shutil.copy2(cp_dir / 'cp_data_worker.c', build_dir / 'cp_data_worker.c')

    edits_list = [
        (e['offset'], bytes.fromhex(e['before_hex']), bytes.fromhex(e['after_hex']))
        for e in cp_component['edits']
    ]
    if len(edits_list) != 12 or not all(len(a) == len(b) in (4, 516) for _, a, b in edits_list):
        raise ValueError('自定义 LUT 曲线窗口数量或长度异常')

    for restore in (False, True):
        mode = 'restore' if restore else 'apply'
        edits = [(at, new, old) for at, old, new in reversed(edits_list)] if restore else edits_list
        text = [
            f'#define WORKER_MODE {int(restore)}',
            f'#define RESULT_PATH "/tmp/jiritsu/zve10m2.insh{mode}.result"',
        ]
        entries = []
        for i, (offset, before, after) in enumerate(edits):
            for label, raw in (('before', before), ('after', after)):
                text.append(f'static const u8 {label}_{i}[]={{' + ','.join(map(str, raw)) + '};')
            entries.append(f'{{{offset}UL,{len(before)},before_{i},after_{i}}}')
        text.append('static const struct Window windows[]={' + ','.join(entries) + '};')
        (build_dir / f'cp_data_{mode}.h').write_text('\n'.join(text) + '\n', encoding='ascii')

        cmd = [
            str(backend.CFG['zig']),
            'cc',
            '-target', 'aarch64-linux-gnu',
            '-shared', '-fPIC', '-O2',
            '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
            '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
            '-nostdlib', '-g0',
            '-Wl,--strip-debug', '-Wl,--no-undefined', '-Wl,-Bsymbolic', '-Wl,-z,noexecstack',
            f'-DCP_DATA_MANIFEST="cp_data_{mode}.h"',
            '-o', str(build_dir / f'cp_data_{mode}.so'),
            str(build_dir / 'cp_data_worker.c'),
        ]
        backend.run(cmd, timeout=120)
        audit(build_dir / f'cp_data_{mode}.so', allow_relative=True)

    cp_parser = backend.module('filter_cp_parser_custom', cp_dir / 'build_test_cp_worker.py').parse

    def _emulate_worker(kind='success', fault_index=None, restore=False):
        mode = 'restore' if restore else 'apply'
        edits = [(at, new, old) for at, old, new in reversed(edits_list)] if restore else edits_list
        worker = build_dir / f'cp_data_{mode}.so'
        entry, segments = audit(worker, allow_relative=True)
        cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        base, stack, stop = 0x10000000, 0x20000000, 0x30000000
        for address, size, data in segments:
            start = (base + address) & ~4095
            end = (base + address + size + 4095) & ~4095
            cpu.mem_map(start, end - start)
            cpu.mem_write(base + address, data)
        with worker.open('rb') as f:
            for section in ELFFile(f).iter_sections():
                if section['sh_type'] == 'SHT_RELA':
                    for rel in section.iter_relocations():
                        cpu.mem_write(base + rel['r_offset'], struct.pack('<Q', base + rel['r_addend']))
        cpu.mem_map(stack, 0x20000)
        cpu.mem_map(stop, 4096)
        cpu.reg_write(UC_ARM64_REG_SP, stack + 0x1F000)
        cpu.reg_write(UC_ARM64_REG_X30, stop)
        parts = [bytearray(old) for _, old, _ in edits]
        originals = [bytes(x) for x in parts]
        if kind == 'wrong_source':
            parts[0][0] ^= 1
            originals = [bytes(x) for x in parts]
        opened = {}
        out = bytearray()
        pos = 0
        mode_zero = kind == 'already_zero'
        cp_writes = []
        triggered = False
        partial = False
        rollback_phase = False
        result_path = f'/tmp/jiritsu/zve10m2.insh{mode}.result'

        def _read_cstr(address):
            raw = bytearray()
            for i in range(512):
                b = cpu.mem_read(address + i, 1)[0]
                if not b:
                    return raw.decode('ascii')
                raw.append(b)
            raise AssertionError('Unterminated path')

        def _locate(offset, count):
            i = next(i for i, (at, old, _) in enumerate(edits) if at <= offset < at + len(old))
            relative = offset - edits[i][0]
            assert relative + count <= len(parts[i])
            return i, relative

        def _intr(uc, number, user):
            nonlocal pos, mode_zero, triggered, partial, rollback_phase
            no = cpu.reg_read(UC_ARM64_REG_X8)
            a, b, c, d = (
                cpu.reg_read(r)
                for r in (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3)
            )
            value = 0
            if no == 56:
                path = _read_cstr(b)
                value = len(opened) + 10
                opened[value] = [path, 0, c]
            elif no == 175:
                value = 0
            elif no == 63:
                path, p, _ = opened[a]
                src = b'*wbi4\n' if path.endswith('image_dev') else (b'0\n' if mode_zero else b'2\n')
                data = src[p:p + min(c, 64)]
                if data:
                    cpu.mem_write(b, data)
                opened[a][1] += len(data)
                value = len(data)
            elif no == 67:
                path, p, _ = opened[a]
                if path == '/dev/nflasha5':
                    data = bytes(512)[d:d + c]
                    cpu.mem_write(b, data)
                    value = len(data)
                else:
                    idx, rel = _locate(d, c)
                    data = bytes(parts[idx][rel:rel + c])
                    cpu.mem_write(b, data)
                    value = len(data)
            elif no == 68:
                idx, rel = _locate(d, c)
                payload = bytes(cpu.mem_read(b, c))
                cp_writes.append((idx, rel, c, rollback_phase))
                if idx == fault_index and kind == 'partial_write' and not triggered:
                    if not partial:
                        value = min(c, 2)
                        parts[idx][rel:rel + value] = payload[:value]
                        partial = True
                    else:
                        triggered = True
                        rollback_phase = True
                        value = -5
                else:
                    value = c
                    parts[idx][rel:rel + value] = payload[:value]
            elif no == 64:
                path, _, _ = opened[a]
                payload = bytes(cpu.mem_read(b, c))
                if path == result_path:
                    value = min(c, 37)
                    end = pos + value
                    if len(out) < end:
                        out.extend(bytes(end - len(out)))
                    out[pos:end] = payload[:value]
                    pos = end
                else:
                    mode_zero = True
                    value = 1
            elif no == 80:
                st = bytearray(128)
                struct.pack_into('<QQI', st, 0, 100, 201, 0o100755)
                struct.pack_into('<Q', st, 48, 17387368)
                cpu.mem_write(b, bytes(st))
            elif no == 62:
                pos = 0
            elif no in (82, 57):
                value = 0
            else:
                raise AssertionError(f'Unexpected syscall {no}')
            cpu.reg_write(UC_ARM64_REG_X0, value & ((1 << 64) - 1))

        def _stop_hook(uc, address, size, user):
            if address == stop:
                cpu.emu_stop()

        cpu.hook_add(UC_HOOK_INTR, _intr)
        cpu.hook_add(UC_HOOK_CODE, _stop_hook)
        cpu.emu_start(base + entry, stop, count=8000000)
        assert cpu.reg_read(UC_ARM64_REG_PC) == stop
        parsed = cp_parser(out)
        if kind in ('success', 'already_zero'):
            assert parsed['complete'] and all(bytes(v) == edits[i][2] for i, v in enumerate(parts))
        else:
            assert not parsed['complete'] and all(bytes(v) == originals[i] for i, v in enumerate(parts))

    for restore in (False, True):
        for case in ('success', 'already_zero', 'wrong_source'):
            _emulate_worker(case, restore=restore)
        for fault_idx in (0, 5, 11):
            _emulate_worker('partial_write', fault_index=fault_idx, restore=restore)

    cp_apply = (build_dir / 'cp_data_apply.so').read_bytes()
    cp_restore = (build_dir / 'cp_data_restore.so').read_bytes()
    return cp_apply, cp_restore


def load_resources(
    backend,
    in_cube_path=None,
    sh_cube_path=None,
    build_dir=None,
    live_cp_bytes=None,
):
    research = backend.WORK / 'fl23_research'
    sys.path[:0] = [str(research), str(backend.TOOLKIT / 'Sony-PMCA-RE')]
    import write_in_sh_replacement as host
    import offset_colour_transaction as offsets
    from complete_in_sh_offset_colour import TRANSPORT_PINS

    base_bundle = backend.load(backend.ROOT / 'filters/FL2-FL3.json')
    folder = research / 'in_sh_replacement_candidate_v1'
    reviewed = copy.deepcopy(backend.load(folder / 'report.json'))

    in_lut = CubeLUT3D.from_file(in_cube_path) if in_cube_path else None
    sh_lut = CubeLUT3D.from_file(sh_cube_path) if sh_cube_path else None
    custom_mode = in_lut is not None or sh_lut is not None

    bundle = (
        build_custom_manifest(base_bundle, in_cube=in_lut, sh_cube=sh_lut)
        if custom_mode
        else base_bundle
    )

    source_files = (
        research / 'live_colour_20261027_225506_564406/cp_cpapp-b.bin',
        folder / 'unit-02a40001.candidate.bin',
        folder / 'unit-02a4000d.candidate.bin',
    )

    targets = {}
    for index, component in enumerate(reviewed['components']):
        public = [bundle[look]['components'][index] for look in ('FL2', 'FL3')]
        if not custom_mode and live_cp_bytes is None:
            selected = [
                {k: edit[k] for k in ('offset', 'length', 'purpose', 'after_hex')}
                for edit in component['edits']
            ]
            if any(
                p['source_sha256'] != component['source_sha256']
                or p['both_looks_sha256'] != component['candidate_sha256']
                for p in public
            ):
                raise ValueError('外观数据和本地研究版本不一致')
            if sorted(selected, key=lambda e: e['offset']) != sorted(
                public[0]['edits'] + public[1]['edits'], key=lambda e: e['offset']
            ):
                raise ValueError('外观写入范围与已核对的数据不一致')
            data = (folder / component['file']).read_bytes()
            if len(data) != component['bytes'] or backend.sha(data) != component['candidate_sha256']:
                raise ValueError('本地外观文件校验失败')
        else:
            pub_by_off = {
                e['offset']: e['after_hex']
                for p in public
                for e in p['edits']
            }
            if index == 0:
                if live_cp_bytes is not None:
                    # Verify that outside the 12 curve windows, live_cp_bytes is identical to original CP
                    orig_cp = bytearray(source_files[0].read_bytes())
                    check_cp = bytearray(live_cp_bytes)
                    for edit in component['edits']:
                        at = edit['offset']
                        n = edit['length']
                        edit['before_hex'] = bytes(live_cp_bytes[at:at + n]).hex()
                        check_cp[at:at + n] = orig_cp[at:at + n]
                    if bytes(check_cp) != bytes(orig_cp):
                        raise ValueError('相机外观程序在 12 个曲线窗口之外存在未知修改，停止导入')
                    base_bytes = bytearray(live_cp_bytes)
                    component['source_sha256'] = backend.sha(live_cp_bytes)
                else:
                    base_bytes = bytearray(source_files[0].read_bytes())
            else:
                base_bytes = bytearray((folder / component['file']).read_bytes())
                for edit in component['edits']:
                    at = edit['offset']
                    n = edit['length']
                    base_bytes[at:at + n] = bytes.fromhex(edit['before_hex'])
            if backend.sha(bytes(base_bytes)) != component['source_sha256']:
                raise ValueError('原始基线文件校验失败')
            for edit in component['edits']:
                at = edit['offset']
                n = edit['length']
                after_hex = pub_by_off[at]
                after_raw = bytes.fromhex(after_hex)
                if len(after_raw) != n:
                    raise ValueError('自定义 LUT 替换块长度不一致')
                edit['after_hex'] = after_hex
                base_bytes[at:at + n] = after_raw
            data = bytes(base_bytes)
            component['candidate_sha256'] = backend.sha(data)
            if build_dir is not None:
                build_dir.mkdir(parents=True, exist_ok=True)
                (build_dir / component['file']).write_bytes(data)

        if index:
            targets[host.settings_plan.KEYS[index - 1]] = data

    cp_dir = research / 'cp_worker_v1'
    wbi_dir = research / 'offset_colour_wbi_v1'
    cp_report = backend.load(cp_dir / 'build_test_report.json')
    wbi_report = backend.load(wbi_dir / 'build_test_report.json')
    if not cp_report['all_passed'] or not wbi_report['all_passed']:
        raise ValueError('缺少写入程序的离线验证')
    wbi = (wbi_dir / 'in_sh_wbi_worker.so').read_bytes()
    if backend.sha(wbi) != wbi_report['worker_sha256']:
        raise ValueError('WBI 辅助程序校验失败')

    if not custom_mode and live_cp_bytes is None:
        cp = (cp_dir / 'cp_data_apply.so').read_bytes()
        inverse = (cp_dir / 'cp_data_restore.so').read_bytes()
        if (
            backend.sha(cp) != cp_report['worker_files']['apply']['sha256']
            or backend.sha(inverse) != cp_report['worker_files']['restore']['sha256']
        ):
            raise ValueError('写入或恢复程序校验失败')
    else:
        backend.say('正在编译针对当前相机基线的写入与回退程序，并执行指令级离线仿真…')
        work_dir = build_dir or (backend.ROOT / 'operations' / ('lut_build_' + uuid.uuid4().hex[:12]))
        cp, inverse = _compile_and_verify_custom_cp_workers(
            backend, research, work_dir, reviewed['components'][0]
        )
        for slot_label, unit_name, ap_name, lut in (
            ('IN_FL2', 'unit-02a40006.bin', 'LUT001_IN.LUT', in_lut),
            ('SH_FL3', 'unit-02a40007.bin', 'LUT002_SH.LUT', sh_lut),
        ):
            if lut is not None:
                u_bytes = encode_cp_3dlut_unit(lut)
                simulate_cp_create_3dlut(u_bytes)
                (work_dir / unit_name).write_bytes(u_bytes)
                (work_dir / ap_name).write_bytes(encode_ap_lut_file(lut))

    parsers = (
        backend.module('filter_wbi_parser', research / 'in_sh_wbi_v1/build_test_in_sh_wbi.py').parse,
        backend.module('filter_cp_parser', cp_dir / 'build_test_cp_worker.py').parse,
    )
    blobs = {
        'wbi': (wbi_report['stage_path'], wbi_report['result_path'], wbi),
        'cp': (
            '/tmp/jiritsu/zve10m2.inshapply.staged.so',
            '/tmp/jiritsu/zve10m2.inshapply.result',
            cp,
        ),
    }
    return host, offsets, TRANSPORT_PINS, reviewed, targets, blobs, parsers, inverse


def install(backend, power, in_cube_path=None, sh_cube_path=None):
    if not power:
        raise ValueError('请先确认电量超过 50%')
    pending = backend.ROOT / 'pending.json'
    if pending.exists():
        raise ValueError('有未完成的相机操作，请保留报告和备份')
    sound = backend.current_state()
    backend.materialize(sound)
    folder = backend.ROOT / 'operations' / ('fl23_' + uuid.uuid4().hex[:16])
    folder.mkdir(parents=True)
    resources = load_resources(
        backend,
        in_cube_path=in_cube_path,
        sh_cube_path=sh_cube_path,
        build_dir=folder / 'custom_lut_build',
    )
    report = {
        'complete': False,
        'events': [],
        'phase': 'preflight',
        'in_cube': str(in_cube_path) if in_cube_path else None,
        'sh_cube': str(sh_cube_path) if sh_cube_path else None,
    }
    from pmca.commands.usb import senserShellCommand
    try:
        senserShellCommand(
            driverName='libusb',
            complete=lambda camera: transact(
                backend,
                camera,
                folder,
                report,
                pending,
                sound,
                resources,
                in_cube_path=in_cube_path,
                sh_cube_path=sh_cube_path,
            ),
        )
        if not report['complete']:
            raise ValueError('没有完成导入，请检查 USB 连接及报告')
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        backend.save(folder / 'report.json', report)
        backend.say('报告：' + str(folder / 'report.json'))


def transact(
    backend,
    camera,
    folder,
    report,
    pending,
    sound,
    resources,
    io_factory=None,
    in_cube_path=None,
    sh_cube_path=None,
):
    host, offsets, transport_pins, reviewed, targets, blobs, parsers, inverse = resources
    settings = host.settings_plan
    cp_plan = reviewed['components'][0]
    components = dict(zip(settings.KEYS, reviewed['components'][1:]))
    pins = {'/usr/lib/appFw.so': (93620512, sound['app_sha256']), **backend.state_pins(sound)}
    pins.pop('/cp/cpapp-b.bin')
    pins.update({path: (size, digest) for path, size, digest in transport_pins})
    if sound.get('audio_path'):
        path = sound['audio_path']
        pins[path] = (Path(sound['audio_file']).stat().st_size, sound['audio_sha256'])

    class _TargetIO(host.IO):
        def __init__(self, cam, ev, bl, comp):
            self.dev = cam.dev
            self.events = ev
            self.blobs = bl
            self.selected = None
            self.paths = {p for p, _, _ in host.BASELINES} | {
                '/version.txt',
                '/cp/cpapp-b.bin',
                '/etc/ld.so.preload',
                host.LIB,
            }
            for stage, result, _ in bl.values():
                self.paths.update((stage, result))
            self.stages = {p: v[2] for v in bl.values() for p in (v[0], v[1])}
            self.adjust = {
                settings.request_bytes('read', k) for k in settings.KEYS
            } | {settings.request_bytes('save')}
            self.adjust.update(struct.pack('<HHB', 0x603, 5, v) for v in (0, 1))
            for k, c in comp.items():
                value = targets[k]
                if backend.sha(value) != c['candidate_sha256']:
                    raise ValueError('Candidate settings differ')
                self.adjust.add(settings.request_bytes('write', k, value))

    io = (io_factory or _TargetIO)(camera, report['events'], blobs, components)
    io.paths.update(pins)
    io.adjust = {request for request in io.adjust if request[:4] != b'\x03\x06\x41\x00'}
    for key, offset, size, data in offsets.fragments(components, targets):
        io.adjust.update(
            (offsets.request(0, key, offset, size), offsets.request(1, key, offset, size, data))
        )

    def journal(phase, **fields):
        report.update(phase=phase, **fields)
        backend.save(folder / 'report.json', report)

    ordinal = 0

    def observe(label):
        nonlocal ordinal
        direct = {
            key: io.raw(settings.request_bytes('read', key), settings.SIZES[key])
            for key in settings.KEYS
        }
        ordinal += 1
        direct_sequence = ordinal
        snapshots = []
        for memory, suffix in ((True, 'ram'), (False, 'stored')):
            data = host.read_snapshot(camera.dev, memory, report['events'])
            host.persist(folder / f'{label}-{suffix}.private.bin', data)
            ordinal += 1
            snapshots.append(
                settings.parse_snapshot(data, folder.name, ordinal, time.monotonic_ns(), memory)
            )
        observation = settings.Observation(*snapshots, direct, direct_sequence)
        settings.fresh(observation, folder.name, time.monotonic_ns())
        if any(
            chip == 0 and key >> 16 == settings.GROUP
            for chip, key in observation.ram.properties
        ):
            raise ValueError('色彩设置保存范围与已验证版本不一致')
        return observation

    if io.read('/version.txt', 256) != host.wire.EXPECTED_VERSION:
        raise ValueError('只支持 ZV-E10M2 固件 1.02')
    protected = {}
    for path, (size, digest) in list(pins.items()):
        data = io.read(path, size)
        if len(data) != size:
            raise ValueError('受保护文件读取长度不符：' + path)
        actual_sha = backend.sha(data)
        if actual_sha != digest:
            # Handle camera with another verified shutter sound guard or stock SysSound
            if path == '/usr/lib/appFw.so' and io_factory is None:
                import factory_sound
                baseline_app = bytearray((backend.RESEARCH / 'appFw.permanent_candidate.so').read_bytes())
                check_app = bytearray(data)
                check_app[backend.OFF:backend.OFF + 0xB00] = baseline_app[backend.OFF:backend.OFF + 0xB00]
                check_app[0x60:0x70] = baseline_app[0x60:0x70]
                check_app[0x2D5039C:0x2D503A0] = baseline_app[0x2D5039C:0x2D503A0]
                if backend.sha(bytes(check_app)) not in (backend.INITIAL_SHA, factory_sound.STOCK_APP_SHA):
                    raise ValueError('受保护文件与本地记录不符：' + path)
                matches = set(
                    re.findall(
                        rb'/cp/(?:zvs_[0-9a-f]{16}|zve10m2_project11_full)\.bin\0',
                        data[backend.OFF:backend.OFF + 0xB00],
                    )
                )
                if len(matches) > 1:
                    raise ValueError('无法识别唯一的快门音文件')
                pins[path] = (size, actual_sha)
                if matches:
                    live_audio_path = matches.pop()[:-1].decode('ascii')
                    io.paths.add(live_audio_path)
                    live_audio = io.read(live_audio_path, 16384)
                    if not 0 < len(live_audio) <= 15360 or len(live_audio) % 128:
                        raise ValueError('相机当前快门音文件异常')
                    protected[live_audio_path] = live_audio
            elif path == '/cp/SysSound.bin' and io_factory is None:
                import factory_sound
                if actual_sha not in (factory_sound.CUSTOM_BANK_SHA, factory_sound.STOCK_BANK_SHA):
                    raise ValueError('受保护文件与本地记录不符：' + path)
                pins[path] = (size, actual_sha)
            elif path.startswith('/cp/zvs_') or path == '/cp/zve10m2_project11_full.bin':
                # Handled dynamically by appFw.so guard match above
                continue
            else:
                raise ValueError('受保护文件与本地记录不符：' + path)
        protected[path] = data

    if io_factory is None:
        _orig_telemetry = host.telemetry_allowed
        def _telemetry_allowed(chip, key, a, b):
            if _orig_telemetry(chip, key, a, b):
                return True
            if chip == 0 and a.attr == b.attr and a.reset_data == b.reset_data:
                if key == 0x02770015 and len(a.data) == len(b.data) == 4:
                    return 0 <= int.from_bytes(b.data, 'little') - int.from_bytes(a.data, 'little') <= 1000000
            return False
        host.telemetry_allowed = _telemetry_allowed

    cp = io.read('/cp/cpapp-b.bin', cp_plan['bytes'])
    cp_sha = backend.sha(cp)

    # If the camera already has FL2/FL3 or a previous custom LUT installed on cpapp-b.bin,
    # dynamically adapt before_hex and re-verify in Unicorn BEFORE taking the initial RAM snapshot!
    if cp_sha not in (cp_plan['source_sha256'], cp_plan['candidate_sha256']) and io_factory is None:
        backend.say('检测到相机已安装过外观数据，正在核对并从当前相机状态无缝切换…')
        resources = load_resources(
            backend,
            in_cube_path=in_cube_path,
            sh_cube_path=sh_cube_path,
            build_dir=folder / 'custom_lut_build_live',
            live_cp_bytes=cp,
        )
        host, offsets, transport_pins, reviewed, targets, blobs, parsers, inverse = resources
        cp_plan = reviewed['components'][0]
        components = dict(zip(settings.KEYS, reviewed['components'][1:]))
        io.blobs = blobs
        io.stages = {p: v[2] for v in blobs.values() for p in (v[0], v[1])}

    first = observe('initial')
    if cp_sha == cp_plan['candidate_sha256'] and all(
        first.direct_units[key] == first.stored.properties[1, key].data == targets[key]
        for key in settings.KEYS
    ):
        journal('already_installed', complete=True)
        backend.say('相机已安装所选外观／LUT，无需重复导入。')
        return

    if cp_sha != cp_plan['source_sha256'] and io_factory is None:
        backend.say('检测到相机已安装过外观数据，正在核对并从当前相机状态无缝切换…')
        resources = load_resources(
            backend,
            in_cube_path=in_cube_path,
            sh_cube_path=sh_cube_path,
            build_dir=folder / 'custom_lut_build_live',
            live_cp_bytes=cp,
        )
        host, offsets, transport_pins, reviewed, targets, blobs, parsers, inverse = resources
        cp_plan = reviewed['components'][0]
        components = dict(zip(settings.KEYS, reviewed['components'][1:]))
        io.blobs = blobs
        io.stages = {p: v[2] for v in blobs.values() for p in (v[0], v[1])}

    if cp_sha != cp_plan['source_sha256']:
        raise ValueError('相机外观程序不是匹配的原始状态，停止导入')

    # Also allow seamless switching when units 0x02a40001 / 0x02a4000d already hold previous FL2/FL3/LUT data
    if io_factory is None:
        for idx, key in enumerate(settings.KEYS, 1):
            live_unit = first.direct_units[key]
            comp = components[key]
            if backend.sha(live_unit) != comp['source_sha256']:
                orig_unit = bytearray((backend.ROOT / 'filter_originals' / f'unit-{key:08x}.bin').read_bytes())
                check_unit = bytearray(live_unit)
                for edit in comp['edits']:
                    at, n = edit['offset'], edit['length']
                    edit['before_hex'] = bytes(live_unit[at:at + n]).hex()
                    check_unit[at:at + n] = orig_unit[at:at + n]
                if bytes(check_unit) != bytes(orig_unit):
                    raise ValueError(f'相机色彩单元 {key:#x} 在允许范围外存在未知修改，停止导入')
                comp['source_sha256'] = backend.sha(live_unit)
                io.adjust = {request for request in io.adjust if request[:4] != b'\x03\x06\x41\x00'}
                for k2, off2, sz2, d2 in offsets.fragments(components, targets):
                    io.adjust.update(
                        (offsets.request(0, k2, off2, sz2), offsets.request(1, k2, off2, sz2, d2))
                    )

    settings.preflight(first, folder.name, time.monotonic_ns(), components)
    stable = observe('stable')
    settings.preflight(stable, folder.name, time.monotonic_ns(), components)
    host.compare_properties(first.ram.properties, stable.ram.properties)
    if first.stored.properties != stable.stored.properties:
        raise ValueError('已保存的相机设置发生变化')
    if io.read('/etc/ld.so.preload', 4096, True):
        raise ValueError('发现其他启动修改，停止导入')
    for name, (stage, result, _) in blobs.items():
        if io.read(stage, 65536, True) is not None:
            raise ValueError('存在未清理的写入辅助文件，停止导入')
        old_res = io.read(result, 65536, True)
        if old_res is not None:
            parser_fn = parsers[0] if name == 'wbi' else parsers[1]
            if io_factory is None and parser_fn(old_res).get('complete'):
                io.jiritsu(io.direct(result))
                io.jiritsu(struct.pack('<HH', 0x1001, 18) + b'\0\xff')
                if io.read(result, 65536, True) is not None:
                    raise ValueError('清理上次已完成的日志记录失败')
            else:
                raise ValueError('存在未清理的写入辅助文件，停止导入')
    if io.read(host.LIB, 65536, True) is not None:
        raise ValueError('存在未清理的写入辅助文件，停止导入')
    archive = folder / 'before.zip'
    items = {path.lstrip('/'): data for path, data in protected.items()}
    items['cp/cpapp-b.bin'] = cp
    items['cp_data_restore.so'] = inverse
    items['candidate_plan.json'] = json.dumps(reviewed, indent=2).encode()
    for file in folder.glob('*.private.bin'):
        items[file.name] = file.read_bytes()
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED, compresslevel=1) as backup:
        for name, data in items.items():
            backup.writestr(name, data)
    with zipfile.ZipFile(archive) as backup:
        if any(backup.read(name) != data for name, data in items.items()):
            raise ValueError('本地备份校验失败')
    journal('backup_verified', backup=str(archive))
    backend.save(pending, {'operation': 'FL2/FL3', 'report': str(folder / 'report.json')})

    def invoke(name, parser):
        stage, result, blob = blobs[name]
        io.put(stage, blob)
        if io.read(stage, 65536) != blob:
            raise ValueError('辅助程序回读失败')
        journal('invoking_' + name)
        io.put(host.LIB, blob)
        raw = io.read(result, 65536)
        host.persist(folder / (name + '-result.bin'), raw)
        if not parser(raw)['complete']:
            raise ValueError('相机写入未完成，请保留报告')
        io.clean(stage, blob)
        io.clean(host.LIB, blob)
        if io_factory is None:
            io.jiritsu(io.direct(result))
            io.jiritsu(struct.pack('<HH', 0x1001, 18) + b'\0\xff')

    cp_already_matches = cp_sha == cp_plan['candidate_sha256']
    invoke('wbi', parsers[0])
    before = observe('after-wbi')
    settings.preflight(before, folder.name, time.monotonic_ns(), components)
    host.compare_properties(stable.ram.properties, before.ram.properties)
    if stable.stored.properties != before.stored.properties:
        raise ValueError('保存状态在写入前发生变化')
    if not cp_already_matches:
        invoke('cp', parsers[1])
        if backend.sha(io.read('/cp/cpapp-b.bin', cp_plan['bytes'])) != cp_plan['candidate_sha256']:
            raise ValueError('外观程序回读不符')
        before_colour = observe('before-colour')
        plan = settings.preflight(before_colour, folder.name, time.monotonic_ns(), components)
        host.compare_properties(before.ram.properties, before_colour.ram.properties)
        if before.stored.properties != before_colour.stored.properties:
            raise ValueError('保存状态在色彩写入前发生变化')
    else:
        plan = settings.preflight(before, folder.name, time.monotonic_ns(), components)

    transaction = {}
    report['settings_transaction'] = transaction
    offsets.apply(io, plan, components, transaction, journal)
    host.verify_settings(plan, observe('before-save'), folder.name, time.monotonic_ns(), False)
    transaction.update(save_attempts=1, write_outcome_unknown=True)
    journal('saving_colour')
    if io.raw(settings.request_bytes('save'), 0):
        raise ValueError('色彩设置保存回复异常')
    host.verify_settings(plan, observe('after-save'), folder.name, time.monotonic_ns(), True)
    if backend.sha(io.read('/cp/cpapp-b.bin', cp_plan['bytes'])) != cp_plan['candidate_sha256']:
        raise ValueError('保存后外观程序校验失败')
    for path, data in protected.items():
        if io.read(path, len(data)) != data:
            raise ValueError('受保护文件回读不符：' + path)
    transaction.update(complete=True, write_outcome_unknown=False)
    journal('complete_readback_verified', complete=True)
    pending.unlink()
    backend.say('FL2／FL3（含所选 LUT 直出）已导入并回读成功。重启相机后，在创意外观中选择 IN／SH。')
