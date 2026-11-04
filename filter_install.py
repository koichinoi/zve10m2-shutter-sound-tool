"""Install the reviewed pair of creative looks through the local service tools."""
import json
import sys
import time
import uuid
import zipfile
from pathlib import Path


def load_resources(backend):
    research = backend.WORK / 'fl23_research'
    sys.path[:0] = [str(research), str(backend.TOOLKIT / 'Sony-PMCA-RE')]
    import write_in_sh_replacement as host
    import offset_colour_transaction as offsets
    from complete_in_sh_offset_colour import TRANSPORT_PINS

    bundle = backend.load(backend.ROOT / 'filters/FL2-FL3.json')
    folder = research / 'in_sh_replacement_candidate_v1'
    reviewed = backend.load(folder / 'report.json')
    targets = {}
    for index, component in enumerate(reviewed['components']):
        public = [bundle[look]['components'][index] for look in ('FL2', 'FL3')]
        selected = [{k: edit[k] for k in ('offset', 'length', 'purpose', 'after_hex')}
                    for edit in component['edits']]
        if any(p['source_sha256'] != component['source_sha256'] or
               p['both_looks_sha256'] != component['candidate_sha256'] for p in public):
            raise ValueError('外观数据和本地研究版本不一致')
        if sorted(selected, key=lambda e: e['offset']) != sorted(
                public[0]['edits'] + public[1]['edits'], key=lambda e: e['offset']):
            raise ValueError('外观写入范围与已核对的数据不一致')
        data = (folder / component['file']).read_bytes()
        if len(data) != component['bytes'] or backend.sha(data) != component['candidate_sha256']:
            raise ValueError('本地外观文件校验失败')
        if index:
            targets[host.settings_plan.KEYS[index-1]] = data

    cp_dir = research / 'cp_worker_v1'
    wbi_dir = research / 'offset_colour_wbi_v1'
    cp_report = backend.load(cp_dir / 'build_test_report.json')
    wbi_report = backend.load(wbi_dir / 'build_test_report.json')
    if not cp_report['all_passed'] or not wbi_report['all_passed']:
        raise ValueError('缺少写入程序的离线验证')
    cp = (cp_dir / 'cp_data_apply.so').read_bytes()
    inverse = (cp_dir / 'cp_data_restore.so').read_bytes()
    wbi = (wbi_dir / 'in_sh_wbi_worker.so').read_bytes()
    if (backend.sha(cp) != cp_report['worker_files']['apply']['sha256']
            or backend.sha(inverse) != cp_report['worker_files']['restore']['sha256']
            or backend.sha(wbi) != wbi_report['worker_sha256']):
        raise ValueError('写入或恢复程序校验失败')
    parsers = (
        backend.module('filter_wbi_parser', research / 'in_sh_wbi_v1/build_test_in_sh_wbi.py').parse,
        backend.module('filter_cp_parser', cp_dir / 'build_test_cp_worker.py').parse,
    )
    blobs = {
        'wbi': (wbi_report['stage_path'], wbi_report['result_path'], wbi),
        'cp': ('/tmp/jiritsu/zve10m2.inshapply.staged.so',
               '/tmp/jiritsu/zve10m2.inshapply.result', cp),
    }
    return host, offsets, TRANSPORT_PINS, reviewed, targets, blobs, parsers, inverse


def install(backend, power):
    if not power:
        raise ValueError('请先确认电量超过 50%')
    pending = backend.ROOT / 'pending.json'
    if pending.exists():
        raise ValueError('有未完成的相机操作，请保留报告和备份')
    resources = load_resources(backend)
    sound = backend.current_state()
    backend.materialize(sound)
    folder = backend.ROOT / 'operations' / ('fl23_' + uuid.uuid4().hex[:16])
    folder.mkdir(parents=True)
    report = {'complete': False, 'events': [], 'phase': 'preflight'}
    from pmca.commands.usb import senserShellCommand
    try:
        senserShellCommand(driverName='libusb', complete=lambda camera: transact(
            backend, camera, folder, report, pending, sound, resources))
        if not report['complete']:
            raise ValueError('没有完成导入，请检查 USB 连接及报告')
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        backend.save(folder / 'report.json', report)
        backend.say('报告：' + str(folder / 'report.json'))


def transact(backend, camera, folder, report, pending, sound, resources, io_factory=None):
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

    io = (io_factory or host.IO)(camera, report['events'], blobs, components)
    io.paths.update(pins)
    io.adjust = {request for request in io.adjust if request[:4] != b'\x03\x06\x41\x00'}
    for key, offset, size, data in offsets.fragments(components, targets):
        io.adjust.update((offsets.request(0, key, offset, size), offsets.request(1, key, offset, size, data)))

    def journal(phase, **fields):
        report.update(phase=phase, **fields)
        backend.save(folder / 'report.json', report)

    ordinal = 0

    def observe(label):
        nonlocal ordinal
        direct = {key: io.raw(settings.request_bytes('read', key), settings.SIZES[key])
                  for key in settings.KEYS}
        ordinal += 1
        direct_sequence = ordinal
        snapshots = []
        for memory, suffix in ((True, 'ram'), (False, 'stored')):
            data = host.read_snapshot(camera.dev, memory, report['events'])
            host.persist(folder / f'{label}-{suffix}.private.bin', data)
            ordinal += 1
            snapshots.append(settings.parse_snapshot(data, folder.name, ordinal, time.monotonic_ns(), memory))
        observation = settings.Observation(*snapshots, direct, direct_sequence)
        settings.fresh(observation, folder.name, time.monotonic_ns())
        if any(chip == 0 and key >> 16 == settings.GROUP for chip, key in observation.ram.properties):
            raise ValueError('色彩设置保存范围与已验证版本不一致')
        return observation

    if io.read('/version.txt', 256) != host.wire.EXPECTED_VERSION:
        raise ValueError('只支持 ZV-E10M2 固件 1.02')
    protected = {}
    for path, (size, digest) in pins.items():
        data = io.read(path, size)
        if len(data) != size or backend.sha(data) != digest:
            raise ValueError('受保护文件与本地记录不符：' + path)
        protected[path] = data
    cp = io.read('/cp/cpapp-b.bin', cp_plan['bytes'])
    cp_sha = backend.sha(cp)
    first = observe('initial')
    if cp_sha == cp_plan['candidate_sha256'] and all(
            first.direct_units[key] == first.stored.properties[1, key].data == targets[key]
            for key in settings.KEYS):
        journal('already_installed', complete=True)
        backend.say('相机已安装 FL2／FL3，无需重复导入。')
        return
    if cp_sha != cp_plan['source_sha256']:
        raise ValueError('相机外观程序不是匹配的原始状态，停止导入')
    settings.preflight(first, folder.name, time.monotonic_ns(), components)
    stable = observe('stable')
    settings.preflight(stable, folder.name, time.monotonic_ns(), components)
    host.compare_properties(first.ram.properties, stable.ram.properties)
    if first.stored.properties != stable.stored.properties:
        raise ValueError('已保存的相机设置发生变化')
    if io.read('/etc/ld.so.preload', 4096, True):
        raise ValueError('发现其他启动修改，停止导入')
    helper_paths = {host.LIB, *(path for stage, result, _ in blobs.values() for path in (stage, result))}
    if any(io.read(path, 65536, True) is not None for path in helper_paths):
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

    invoke('wbi', parsers[0])
    before = observe('after-wbi')
    settings.preflight(before, folder.name, time.monotonic_ns(), components)
    host.compare_properties(stable.ram.properties, before.ram.properties)
    if stable.stored.properties != before.stored.properties:
        raise ValueError('保存状态在写入前发生变化')
    invoke('cp', parsers[1])
    if backend.sha(io.read('/cp/cpapp-b.bin', cp_plan['bytes'])) != cp_plan['candidate_sha256']:
        raise ValueError('外观程序回读不符')
    before_colour = observe('before-colour')
    plan = settings.preflight(before_colour, folder.name, time.monotonic_ns(), components)
    host.compare_properties(before.ram.properties, before_colour.ram.properties)
    if before.stored.properties != before_colour.stored.properties:
        raise ValueError('保存状态在色彩写入前发生变化')
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
    backend.say('FL2／FL3 已导入并回读成功。重启相机后，在创意外观中选择 IN／SH。')
