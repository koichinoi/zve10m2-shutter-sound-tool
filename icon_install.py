"""Windows service diagnostics and updates for the FL2/FL3 list icons."""
from pathlib import Path
import re
import struct
import sys
import time
import uuid
import zipfile


BANK_1 = '/usr/share/app/image_01_23_IPSX.uxc'
BANK_2 = '/usr/share/app/image_02_23_IPSX.uxc'
BANK_1_32 = '/usr/share/app/image_01_32_IPSX.uxc'
BANK_2_32 = '/usr/share/app/image_02_32_IPSX.uxc'
BANKS = {BANK_1: 9675260, BANK_2: 6838252, BANK_1_32: 9685748, BANK_2_32: 6929728}
LOADER = '/tmp/jiritsu/libJit.so'
PROTECTED = {
    '/usr/lib/appFw.so': 93620512,
    '/cp/cpapp-b.bin': 17387368,
    '/cp/SysSound.bin': 76992,
    '/usr/lib/libJiritsu.so': 237512,
}


def load_plans(backend, writing):
    research = backend.WORK / 'fl23_research'
    base = research / 'menu_icons_candidate_v1'
    extra = research / 'menu_icons_extra_v2'
    display32 = research / 'menu_icons_display32_v3'
    plans = []
    for folder, path, prefix, counts in (
        (base, BANK_1, 'zvicon', (18, 18, 18, 2)),
        (extra / 'bank1', BANK_1, 'zviconx1', (2,)),
        (extra / 'bank2', BANK_2, 'zviconx2', (6,)),
        (display32 / 'bank1', BANK_1_32, 'zvicon32b1', (18, 18, 18, 4)),
        (display32 / 'bank2', BANK_2_32, 'zvicon32b2', (6,)),
    ):
        resources = folder / 'workers'
        plan = backend.load(resources / 'manifest.json')
        steps = plan['steps']
        if (plan['path'] != path or plan['size'] != BANKS[path] or len(steps) != len(counts)
                or plan['simulated_cases'] != 30 * len(counts)):
            raise ValueError('本地图标清单与已验证批次不符')
        current = plan['before']
        for index, (step, count) in enumerate(zip(steps, counts), 1):
            if step['before'] != current or step['windows'] != count:
                raise ValueError('图标写入顺序不匹配')
            current = step['after']
            for mode in ('install', 'restore'):
                info = step[mode]
                filename = f'{mode}{index}.so'
                result = f'/tmp/jiritsu/{prefix}_{index}_{mode}.result'
                if info['file'] != filename or info['result'] != result:
                    raise ValueError('图标辅助文件名不匹配')
                if writing:
                    blob = (resources / filename).read_bytes()
                    if not 0 < len(blob) <= 65536 or backend.sha(blob) != info['sha256']:
                        raise ValueError('本地图标辅助程序校验失败')
                    info['blob'] = blob
            result = step['install']['result']
            step['stage'] = result.removesuffix('.result') + '.stage.so'
        if current != plan['after']:
            raise ValueError('图标目标校验不匹配')
        plans.append(plan)
    if plans[0]['after'] != plans[1]['before']:
        raise ValueError('旧版与新版图标资源无法衔接')
    return plans


def select_plans(plans, hashes):
    base, extra1, extra2, *display32 = plans
    first, second = hashes[BANK_1], hashes[BANK_2]
    selected = []
    if first == base['before']:
        selected.extend((base, extra1))
    elif first == extra1['before']:
        selected.append(extra1)
    elif first != extra1['after']:
        raise ValueError('第一组图标与已知版本不符')
    if second == extra2['before']:
        selected.append(extra2)
    elif second != extra2['after']:
        raise ValueError('第二组图标与已知版本不符')
    for plan in display32:
        path = plan['path']
        if hashes[path] == plan['before']:
            selected.append(plan)
        elif hashes[path] != plan['after']:
            raise ValueError('32_IPSX 图标资源与已知版本不符：' + Path(path).name)
    return selected


def describe(plans, hashes):
    base, extra1, extra2, *display32 = plans
    states = {
        BANK_1: {base['before']: '原厂', base['after']: '已写入 0.2.3', extra1['after']: '已更新'},
        BANK_2: {extra2['before']: '原厂', extra2['after']: '已更新'},
    }
    for plan in display32:
        states[plan['path']] = {plan['before']: '原厂', plan['after']: '已更新'}
    labels = ('23-1', '23-2', '32-1', '32-2')
    return '，'.join(f'{label} {states[path].get(hashes[path], "未知版本")}'
                    for label, path in zip(labels, BANKS))


def verify_result(raw, windows):
    if len(raw) != 136:
        raise ValueError('图标写入报告长度异常')
    (magic, version, phase, status, rollback, remount, readonly, _, _, header_read, dev, ino,
     prepared, applied, restored, reserved, before, after) = struct.unpack('<8sII7q2Q4I16s16s', raw)
    if not (magic == b'ZVBINS01' and version == 1 and phase == 30
            and not any((status, rollback, remount, readonly, restored, reserved))
            and prepared == applied == windows and header_read == 512 and dev and ino
            and before.rstrip(b'\0') in (b'0\n', b'2\n') and after.rstrip(b'\0') == b'0\n'):
        raise ValueError('相机未确认图标批次写入完成，请保留报告')


def verify_looks(camera, backend, events):
    import filter_install
    host, _, _, reviewed, targets, _, _, _ = filter_install.load_resources(backend)
    settings = host.settings_plan
    components = dict(zip(settings.KEYS, reviewed['components'][1:]))
    reader = host.IO(camera, events, {}, components)
    direct = {key: reader.raw(settings.request_bytes('read', key), settings.SIZES[key]) for key in settings.KEYS}
    ram = settings.parse_snapshot(host.read_snapshot(camera.dev, True, events), 'icons', 2, time.monotonic_ns(), True)
    stored = settings.parse_snapshot(host.read_snapshot(camera.dev, False, events), 'icons', 3, time.monotonic_ns(), False)
    settings.fresh(settings.Observation(ram, stored, direct, 1), 'icons', time.monotonic_ns())
    if any(direct[key] != targets[key] or stored.properties[1, key].data != targets[key] for key in targets):
        raise ValueError('请先安装 FL2／FL3 成像数据，再更新图标')
    return reviewed['components'][0]['candidate_sha256']


def transact(backend, io, plans, folder, report, pending, writing, check_looks):
    def journal(phase, **fields):
        report.update(phase=phase, **fields)
        backend.save(folder / 'report.json', report)

    if io.read('/version.txt', 256) != b'33002_03.2025101101':
        raise ValueError('只支持 ZV-E10M2 固件 1.02')
    bank_data = {path: io.read(path, size) for path, size in BANKS.items()}
    if any(len(bank_data[path]) != size for path, size in BANKS.items()):
        raise ValueError('图标资源读取不完整')
    hashes = {path: backend.sha(data) for path, data in bank_data.items()}
    status = describe(plans, hashes)
    journal('checked', hashes=hashes, summary=status)
    backend.say('图标资源：' + status)
    if not writing:
        journal('checked', complete=True)
        return
    selected = select_plans(plans, hashes)
    if not selected:
        journal('already_updated', complete=True)
        backend.say('相机图标资源已更新，无需重复写入。')
        return

    cp_hash = check_looks()
    protected = {}
    for path, size in PROTECTED.items():
        data = io.read(path, size)
        if len(data) != size:
            raise ValueError('相机保护文件读取不完整：' + path)
        protected[path] = backend.sha(data)
        if path == '/usr/lib/appFw.so':
            # Desktop and Android can each have prepared the active guard.
            matches = set(re.findall(rb'/cp/(?:zvs_[0-9a-f]{16}|zve10m2_project11_full)\.bin\0',
                                     data[backend.OFF:backend.OFF + 0xb00]))
            if len(matches) > 1:
                raise ValueError('无法识别唯一的快门音文件')
            for match in matches:
                audio_path = match[:-1].decode('ascii')
                io.allow_shutter_read(audio_path)
                audio = io.read(audio_path, 16384)
                if not 0 < len(audio) <= 15360 or len(audio) % 128:
                    raise ValueError('当前快门音文件长度异常')
                protected[audio_path] = backend.sha(audio)
    if protected['/cp/cpapp-b.bin'] != cp_hash or protected['/usr/lib/libJiritsu.so'] != backend.PINS['/usr/lib/libJiritsu.so'][1]:
        raise ValueError('外观程序或相机服务程序不匹配')
    if io.read('/etc/ld.so.preload', 4096, True):
        raise ValueError('检测到其他启动修改')
    steps = [(plan['path'], step) for plan in selected for step in plan['steps']]
    helper_paths = [LOADER, *(path for _, step in steps for path in (step['stage'], step['install']['result']))]
    if any(io.read(path, 65536, True) is not None for path in helper_paths):
        raise ValueError('存在未清理的辅助文件，请保留现场')

    backup = folder / 'before.zip'
    items = {Path(path).name: data for path, data in bank_data.items()}
    for index, (_, step) in enumerate(steps, 1):
        items[f'restore{index}.so'] = step['restore']['blob']
    with zipfile.ZipFile(backup, 'x', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name, data in items.items():
            archive.writestr(name, data)
    with zipfile.ZipFile(backup) as archive:
        if any(archive.read(name) != data for name, data in items.items()):
            raise ValueError('图标备份校验失败')
    journal('backup_verified', backup=str(backup), protected=protected)
    backend.save(pending, {'operation': 'camera-icons', 'report': str(folder / 'report.json')})

    for index, (path, step) in enumerate(steps, 1):
        if backend.sha(io.read(path, BANKS[path])) != step['before']:
            raise ValueError('图标资源在写入前发生变化')
        backend.say(f'正在更新并回读图标 {index}/{len(steps)}…')
        journal('staging', batch=index)
        blob = step['install']['blob']
        stage, result = step['stage'], step['install']['result']
        io.put(stage, blob, native=True)
        if io.read(stage, 65536) != blob:
            raise ValueError('图标辅助程序回读失败')
        journal('invoking', batch=index)
        io.put(LOADER, blob, native=True)
        raw = io.read(result, 136)
        (folder / f'result-{index}.bin').write_bytes(raw)
        verify_result(raw, step['windows'])
        if backend.sha(io.read(path, BANKS[path])) != step['after']:
            raise ValueError('图标资源回读失败')
        io.clean(stage, blob)
        io.clean(LOADER, blob)

    expected = {plan['path']: plan['after'] for plan in plans}
    expected.update(protected)
    sizes = {**BANKS, **PROTECTED}
    for path, digest in expected.items():
        if backend.sha(io.read(path, sizes.get(path, 16384))) != digest:
            raise ValueError('写后保护校验失败：' + path)
    journal('complete_readback_verified', complete=True)
    pending.unlink()
    backend.say('图标更新和回读通过。请重启相机查看左侧列表。')


def run(backend, writing, power=False):
    if writing and not power:
        raise ValueError('请先确认电量超过 50%')
    pending = backend.ROOT / 'pending.json'
    if writing and pending.exists():
        raise ValueError('有未完成的相机操作，请保留报告和备份')
    plans = load_plans(backend, writing)
    folder = backend.ROOT / 'operations' / ('icons_' + uuid.uuid4().hex[:16])
    folder.mkdir(parents=True)
    report = {'complete': False, 'events': [], 'read_only': not writing}
    paths = {'/version.txt', *BANKS, *PROTECTED, '/etc/ld.so.preload', LOADER}
    for plan in plans:
        for step in plan['steps']:
            paths.update((step['stage'], step['install']['result']))
    sys.path.insert(0, str(backend.TOOLKIT / 'Sony-PMCA-RE'))
    from pmca.commands.usb import senserShellCommand

    def connected(camera):
        io = backend.CameraIO(camera, paths, report['events'])
        transact(backend, io, plans, folder, report, pending, writing,
                 lambda: verify_looks(camera, backend, report['events']))

    try:
        senserShellCommand(driverName='libusb', complete=connected)
        if not report['complete']:
            raise ValueError('没有完成图标检查，请确认相机以 USB 海量存储器模式连接')
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        backend.save(folder / 'report.json', report)
        backend.say('报告：' + str(folder / 'report.json'))
