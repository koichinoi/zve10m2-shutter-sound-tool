"""Local, model-pinned shutter sound tool. No camera access during preparation."""
import argparse, array, binascii, datetime, hashlib, importlib.util, json, math, os
from pathlib import Path
import shutil, struct, subprocess, sys, uuid, wave, zipfile, re
import factory_sound

ROOT=Path(__file__).resolve().parent
CFG=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
RESEARCH=Path(CFG['research']); WORK=RESEARCH.parent
TOOLKIT=Path(CFG['toolkit'])
sys.path[:0]=[str(RESEARCH),str(WORK/'research_libs'),str(TOOLKIT/'deps'),str(TOOLKIT),str(WORK/'restore_v0_1')]
libusb_dir=TOOLKIT/'deps/libusb_package'
if libusb_dir.is_dir():
    os.environ['PATH']=str(libusb_dir)+os.pathsep+os.environ.get('PATH','')
MAX_SAMPLES=14880  # largest buffer already exercised on this camera: 15360 bytes
OFF=0x4637500
INITIAL_SHA='e6e842de3ad83d11702d5c258f0ecb1d7a20af85b6c3fb1312f8b1eb87f578dd'
PINS={
 '/cp/cpapp-b.bin':(17387368,'3e3d1f7db67f3831708ec4cab85ac4acc59229a26e6519be6dac3dc7ae72b636'),
 '/usr/lib/libJiritsu.so':(237512,'b260595f78f6b7f791bb69f2973badd85bf530cc198bf15648c8031172bc82f2'),
 '/cp/SysSound.bin':(76992,'1123da9768aa060807b3536838271ca897cf8236af30515b6f6a6b8ce1a4475d')}
def sha(b):return hashlib.sha256(b).hexdigest()
def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,obj):
    p=Path(p);tmp=p.with_suffix(p.suffix+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(tmp,p)
def say(s):print(s,flush=True)
def run(cmd,**kw):
    p=subprocess.run(list(map(str,cmd)),capture_output=True,creationflags=0x08000000 if os.name=='nt' else 0,**kw)
    if p.returncode:raise RuntimeError(p.stderr.decode('utf-8','replace')[-2500:] or p.stdout.decode('utf-8','replace')[-2500:])
    return p.stdout
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def encode(samples):
    if not 1<=len(samples)<=MAX_SAMPLES:raise ValueError('音频须在 0.620 秒以内；不会自动截短。')
    output=bytearray();decoded=[]
    for start in range(0,len(samples),31):
        block=list(samples[start:start+31]);block += [0]*(31-len(block))
        shift=next((s for s in range(9) if all(-128<=round(v/(1<<s))<=127 for v in block)),8)
        values=[max(-128,min(127,round(v/(1<<shift)))) for v in block]
        output.append(shift);output.extend(v&255 for v in values)
        decoded.extend(v*(1<<shift) for v in values)
    while len(output)%128:
        output.extend(bytes(32));decoded.extend([0]*31)
    return bytes(output),decoded
def write_wav(path,samples):
    with wave.open(str(path),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000)
        f.writeframes(struct.pack('<%dh'%len(samples),*samples))
def initial_state():
    app=(RESEARCH/'appFw.permanent_candidate.so').read_bytes()
    if sha(app)!=INITIAL_SHA:raise ValueError('已有成功版本的本地备份校验失败')
    audio=WORK/'full_audio/project11_full_filter0.bin'
    return {'name':'Video Project 11（之前成功的完整声音）','app_sha256':INITIAL_SHA,
            'guard_hex':app[OFF:OFF+0xb00].hex(),'header_hex':app[0x60:0x70].hex(),
            'call_hex':app[0x2d5039c:0x2d503a0].hex(),
            'audio_path':'/cp/zve10m2_project11_full.bin','audio_file':str(audio),
            'audio_sha256':sha(audio.read_bytes()),'hardware_verified':True}
def materialize(state):
    if state.get('factory'):
        if state['app_sha256']!=factory_sound.STOCK_APP_SHA or bank_hash(state)!=factory_sound.STOCK_BANK_SHA or state.get('audio_path') is not None:raise ValueError('原厂状态记录异常')
        return factory_sound.stock_app(sys.modules[__name__])
    path=state['audio_path']
    if path!='/cp/zve10m2_project11_full.bin' and not re.fullmatch(r'/cp/zvs_[0-9a-f]{16}\.bin',path):raise ValueError('音频路径不属于本工具的专用范围')
    payload=Path(state['audio_file']).read_bytes()
    if sha(payload)!=state['audio_sha256'] or not 128<=len(payload)<=15360 or len(payload)%128 or any(payload[i]>8 for i in range(0,len(payload),32)):
        raise ValueError('音频数据校验失败')
    b=bytearray((RESEARCH/'appFw.permanent_candidate.so').read_bytes())
    if sha(b)!=INITIAL_SHA:raise ValueError('本地程序基线校验失败')
    if bytes.fromhex(state['call_hex'])!=b[0x2d5039c:0x2d503a0]:raise ValueError('声音加载入口异常')
    sizes=struct.unpack('<QQ',bytes.fromhex(state['header_hex']))
    if sizes[0]!=sizes[1] or not OFF<sizes[0]<=OFF+0xb00:raise ValueError('声音加载范围异常')
    for at,key,n in [(OFF,'guard_hex',0xb00),(0x60,'header_hex',16),(0x2d5039c,'call_hex',4)]:
        v=bytes.fromhex(state[key])
        if len(v)!=n:raise ValueError('声音配置长度异常')
        b[at:at+n]=v
    if sha(b)!=state['app_sha256']:raise ValueError('声音配置校验失败')
    return bytes(b)
def current_state():return load(ROOT/'current.json') if (ROOT/'current.json').exists() else initial_state()
def bank_hash(state):return state.get('sound_bank_sha256',factory_sound.CUSTOM_BANK_SHA)
def state_pins(state):return {**PINS,'/cp/SysSound.bin':(76992,bank_hash(state))}
def compile_guard(folder,audio,path):
    from elftools.elf.elffile import ELFFile
    src=(RESEARCH/'permanent_boot_guard.c').read_text(encoding='utf-8')
    src=src.replace('/cp/zve10m2_project11_full.bin',path).replace('15360',str(len(audio))).replace('block<480','block<'+str(len(audio)//32)).replace('0x0051ac92U',f'0x{binascii.crc32(audio):08x}U')
    (folder/'guard.c').write_text(src,encoding='utf-8')
    flags=['-target','aarch64-linux-gnu','-O2','-fPIC','-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-unwind-tables','-fno-asynchronous-unwind-tables','-ffunction-sections','-fdata-sections','-nostdlib','-no-pie','-static','-g0','-Wl,--build-id=none','-Wl,--no-undefined','-Wl,-e,zv_guard_wrapper','-Wl,-T,'+str(RESEARCH/'permanent_boot_guard.ld')]
    run([CFG['zig'],'cc',*flags,'-o',folder/'guard.elf',RESEARCH/'permanent_boot_guard.S',folder/'guard.c'],timeout=120)
    with (folder/'guard.elf').open('rb') as f:
        elf=ELFFile(f);s=elf.get_section_by_name('.guard');code=s.data()
        if s['sh_addr']!=OFF or not 0<len(code)<=0xb00:raise ValueError('加载程序超出允许范围')
        if any(s['sh_type'] in ('SHT_REL','SHT_RELA','SHT_DYNAMIC') and s['sh_size'] for s in elf.iter_sections()):raise ValueError('加载程序有未解析引用')
    (folder/'guard.bin').write_bytes(code)
    return code
def guard_test(folder,audio,path,code):
    # Execute the actual compiled instructions in the previously reviewed CPU harness.
    source=(RESEARCH/'test_permanent_boot_guard.py').read_text(encoding='utf-8').replace('15360','len(PAYLOAD)').replace('count=4000000','count=6000000')
    source=source.replace("data[:101]+bytes([data[101]^1])+data[102:]","data[:min(101,len(data)-1)]+bytes([data[min(101,len(data)-1)]^1])+data[min(101,len(data)-1)+1:]")
    testpath=folder/'guard_test.py';testpath.write_text(source,encoding='utf-8')
    # The harness loads its fixtures at import. Redirect ROOT without changing the original file.
    source=source.replace('ROOT=Path(__file__).resolve().parent','ROOT=Path('+repr(str(RESEARCH))+')')
    testpath.write_text(source,encoding='utf-8');m=module('generated_guard_test',testpath)
    m.CODE=code;m.PAYLOAD=audio;m.PATH=path.encode()+b'\0'
    cases=[]
    for owned in (False,True):
        for case in ('valid','missing','short','long','corrupt','bad_control','read_error','close_error'):
            cases.append(m.run(case,owned=owned))
    cases.append(m.run('foreign'));cases.append(m.run(base=0x40000000))
    return len(cases)
def prepare(source,gain):
    if not math.isfinite(gain) or not 0.1<=gain<=1.0:raise ValueError('音量应为 10% 至 100%')
    source=Path(source).resolve()
    if not source.is_file():raise ValueError('找不到所选音频')
    folder=ROOT/'sounds'/uuid.uuid4().hex;folder.mkdir(parents=True)
    say('解码音频，保留完整内容…')
    pcm=run([CFG['ffmpeg'],'-v','error','-nostdin','-i',source,'-map','0:a:0','-t','0.621','-ac','1','-ar','24000','-f','s16le','pipe:1'],timeout=60)
    samples=array.array('h');samples.frombytes(pcm)
    if not 1<=len(samples)<=MAX_SAMPLES:raise ValueError('这段超过当前已验证的 0.620 秒容量。请选择更短的音频；本工具没有截取或写入相机。')
    # Decode beyond the permitted range above, rather than silently trimming a long file.
    adjusted=[max(-32768,min(32767,round(x*gain))) for x in samples]
    audio,preview=encode(adjusted);(folder/'audio.bin').write_bytes(audio)
    write_wav(folder/'preview.wav',preview[:len(samples)])
    camera_path='/cp/zvs_'+sha(audio)[:16]+'.bin'
    say('生成加载配置，并模拟正常启动、缺失和损坏文件…')
    code=compile_guard(folder,audio,camera_path);cases=guard_test(folder,audio,camera_path,code)
    app=bytearray(materialize(initial_state()));app[OFF:OFF+0xb00]=code.ljust(0xb00,b'\0')
    app[0x60:0x70]=struct.pack('<QQ',OFF+len(code),OFF+len(code))
    state={'name':source.name,'source':str(source),'source_sha256':sha(source.read_bytes()),'seconds':len(samples)/24000,'gain':gain,
           'app_sha256':sha(app),'guard_hex':app[OFF:OFF+0xb00].hex(),'header_hex':app[0x60:0x70].hex(),'call_hex':app[0x2d5039c:0x2d503a0].hex(),
           'audio_file':str(folder/'audio.bin'),'audio_path':camera_path,'audio_sha256':sha(audio),'preview':str(folder/'preview.wav'),
           'guard_test_cases':cases,'hardware_verified':False,'entire_decoded_audio_used':True}
    save(folder/'state.json',state)
    say('PREPARED '+str(folder/'state.json'));return folder/'state.json'
def build_worker(folder,before,after):
    a=materialize(before);b=materialize(after);factory=bool(after.get('factory'))
    audio=b'\0' if factory else Path(after['audio_file']).read_bytes()
    if not factory and (sha(audio)!=after['audio_sha256'] or len(audio)>15360):raise ValueError('音频内容或容量校验失败')
    locations=[(OFF,0xb00),(0x60,16),(0x2d5039c,4)]
    # Disable the hook before shrinking the executable segment or erasing its code.
    if factory:locations.reverse()
    edits=[(at,a[at:at+n],b[at:at+n]) for at,n in locations]
    plan={'edits':[{'offset':at,'before_hex':x.hex(),'after_hex':y.hex()} for at,x,y in edits]}
    save(folder/'plan.json',plan)
    array_c=lambda name,data:'static const u8 '+name+'[]={'+','.join(map(str,data))+'};'
    lines=['#define RESTORE_ORIGINAL_PROGRAM 1'] if factory else [];rows=[]
    for i,(at,x,y) in enumerate(edits):
        lines += [array_c('old_'+str(i),x),array_c('new_'+str(i),y)]
        rows.append('{'+str(at)+'UL,'+str(len(x))+',old_'+str(i)+',new_'+str(i)+'}')
    lines += ['static const struct Window windows[]={'+','.join(rows)+'};',array_c('audio_payload',audio)]
    (folder/'permanent_program_manifest.h').write_text('\n'.join(lines),encoding='ascii')
    result='/tmp/jiritsu/zvs_'+folder.name+'.result'
    audio_path=after.get('audio_path') or '/cp/zve10m2_project11_full.bin'
    src=(RESEARCH/'permanent_program_installer.c').read_text(encoding='utf-8').replace('/cp/zve10m2_project11_full.bin',audio_path).replace('/tmp/jiritsu/zve10m2.bootinstall.result',result)
    (folder/'worker.c').write_text(src,encoding='utf-8');shutil.copy2(RESEARCH/'sound_maps_probe.c',folder/'sound_maps_probe.c')
    run([CFG['zig'],'cc','-target','aarch64-linux-gnu','-shared','-fPIC','-O2','-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-unwind-tables','-fno-asynchronous-unwind-tables','-nostdlib','-g0','-Wl,--strip-debug','-Wl,--no-undefined','-Wl,-Bsymbolic','-Wl,-z,noexecstack','-o',folder/'permanent_program_installer.so',folder/'worker.c'],timeout=120)
    src=(RESEARCH/'build_test_permanent_installer.py').read_text(encoding='utf-8')
    src=src.replace("ROOT/'permanent_boot_plan.json'","ROOT/'plan.json'").replace("(ROOT.parent/'full_audio/project11_full_filter0.bin')","(ROOT/'audio.bin')")
    src=src.replace('/cp/zve10m2_project11_full.bin',audio_path).replace("path.endswith('project11_full.bin')","path=="+repr(audio_path))
    src=src.replace('/tmp/jiritsu/zve10m2.bootinstall.result',result)
    (folder/'audio.bin').write_bytes(audio);(folder/'worker_test.py').write_text(src,encoding='utf-8')
    test=module('generated_worker_test',folder/'worker_test.py')
    scenarios=('success','already_mode_zero','existing_result','valid_wbi','missing_audio','wrong_audio','wrong_device','wrong_program','mode_failure','remount_failure','changed_inode','journal_sync_failure','guard_partial','header_partial','hook_partial','program_sync_failure','readonly_failure','program_close_failure')
    if factory:scenarios=tuple(c for c in scenarios if c not in ('missing_audio','wrong_audio'))
    cases=[test.run(c) for c in scenarios]
    save(folder/'worker_tests.json',{'passed':True,'cases':cases,'camera_io':False})
    return (folder/'permanent_program_installer.so').read_bytes(),result,test

class CameraIO:
    def __init__(self,camera,paths,events):
        import cp_probe_transport as small
        import segmented_read_transport as wire
        self.small=small;self.wire=wire;self.camera=camera;self.events=events;self.paths=set(paths)
        # Dedicated module instance: the historical diagnostic allowlist stays unchanged.
        self.reader=module('tool_segmented_reader',RESEARCH/'segmented_read_transport.py')
        self.reader.PATHS=frozenset(paths)
    def read(self,path,limit,optional=False):
        if path not in self.paths:raise ValueError('读取路径未授权')
        try:
            self.reader.exchange(self.camera.dev,self.reader.select_request(path),4,self.events)
            return self.reader.exchange(self.camera.dev,self.reader.READ,limit+4,self.events)
        except self.reader.JiritsuResultError as exc:
            if optional and exc.code==0x10000006:return None
            raise
    def put(self,path,content,native=False):
        if path not in self.paths:raise ValueError('写入路径未授权')
        if not getattr(self.camera.dev,'_probe_usable',True):raise ValueError('连接已中断，不自动重试')
        select=struct.pack('<HH',0x1001,15)+b'\0'+(path if native else '/tmp/jiritsu/../..'+path).encode()+b'\0'
        write=struct.pack('<HH',0x1001,16)+b'\0\xff\0'+content
        self.small.exchange(self.camera.dev,select,4,self.events,(select,))
        self.small.exchange(self.camera.dev,write,4,self.events,(write,))
    def clean(self,path,expected):
        value=self.read(path,65536,True)
        if value is None:return
        if value!=expected:raise ValueError('临时文件内容异常，保留现场')
        select=struct.pack('<HH',0x1001,15)+b'\0'+path.encode()+b'\0'
        delete=struct.pack('<HH',0x1001,18)+b'\0\xff'
        self.small.exchange(self.camera.dev,select,4,self.events,(select,))
        self.small.exchange(self.camera.dev,delete,4,self.events,(delete,))
        if self.read(path,65536,True) is not None:raise ValueError('清理结果无法确认')

def transact(io,folder,report,before,after,blob,result,parser,bank_worker=None):
    lib='/tmp/jiritsu/libJit.so';stage=result.replace('.result','.stage.so')
    if io.read('/version.txt',256)!=b'33002_03.2025101101':raise ValueError('只支持 ZV-E10M2 1.02')
    snapshots={}
    for path,(size,digest) in {'/usr/lib/appFw.so':(93620512,before['app_sha256']),**state_pins(before)}.items():
        say('核对并备份 '+Path(path).name+'…');data=io.read(path,size)
        if len(data)!=size or sha(data)!=digest:raise ValueError('相机状态与已知版本不一致：'+path)
        snapshots[path]=data
    oldaudio=None
    if before.get('audio_path'):
        oldaudio=io.read(before['audio_path'],16384)
        if sha(oldaudio)!=before['audio_sha256']:raise ValueError('当前声音不符合备份记录')
        snapshots[before['audio_path']]=oldaudio
    if io.read('/etc/ld.so.preload',4096,True):raise ValueError('存在其他启动修改，停止')
    helper_paths=[lib,stage,result]
    if bank_worker:helper_paths += [bank_worker['result'],bank_worker['result'].replace('.result','.stage.so')]
    for p in helper_paths:
        if io.read(p,65536,True) is not None:raise ValueError('存在未完成的操作文件，保留现场')
    audio=None;existing=None
    if after.get('audio_path'):
        audio=Path(after['audio_file']).read_bytes();existing=io.read(after['audio_path'],16384,True)
        if existing is not None and existing!=audio:raise ValueError('目标音频路径已存在不同内容')
    if (bank_hash(before)!=bank_hash(after)) != bool(bank_worker):raise ValueError('缺少对应的声音包恢复程序')
    factory_sound.bank_bytes(sys.modules[__name__],bank_hash(after))
    backup=folder/'backup.zip'
    with zipfile.ZipFile(backup,'x',zipfile.ZIP_DEFLATED,compresslevel=1) as z:
        for p,b in snapshots.items():z.writestr(p.lstrip('/'),b)
        z.writestr('before.json',json.dumps(before));z.writestr('after.json',json.dumps(after))
    with zipfile.ZipFile(backup) as z:
        for p,b in snapshots.items():
            if z.read(p.lstrip('/'))!=b:raise ValueError('本地备份核对失败')
    report['backup_verified']=True;report['backup']=str(backup);save(folder/'report.json',report)
    save(ROOT/'pending.json',{'report':str(folder/'report.json'),'before':before,'after':after})
    report['mutation_started']=True;save(folder/'report.json',report)
    if audio is not None:
        if existing is None:io.put(after['audio_path'],audio)
        if io.read(after['audio_path'],16384)!=audio:raise ValueError('音频回读不一致')
    io.put(stage,blob,native=True)
    if io.read(stage,65536)!=blob:raise ValueError('写入辅助程序核对失败')
    report['native_attempted']=True;save(folder/'report.json',report)
    say('写入对应的快门加载配置…')
    io.put(lib,blob,native=True)
    raw=io.read(result,65536);(folder/'native_result.bin').write_bytes(raw);native=parser(raw)
    report['native']={k:(v.hex() if isinstance(v,bytes) else v) for k,v in native.items()};save(folder/'report.json',report)
    if not native['complete']:raise ValueError('写入未完成；不要重试，请保留报告')
    for path,(size,digest) in {'/usr/lib/appFw.so':(93620512,after['app_sha256']),**state_pins(before)}.items():
        say('回读核对 '+Path(path).name+'…');data=io.read(path,size)
        if len(data)!=size or sha(data)!=digest:raise ValueError('写后完整核对不一致：'+path)
    if audio is not None and io.read(after['audio_path'],16384)!=audio:raise ValueError('新声音文件核对失败')
    if oldaudio is not None and io.read(before['audio_path'],16384)!=oldaudio:raise ValueError('之前的声音文件核对失败')
    io.clean(stage,blob);io.clean(lib,blob)
    report['app_verified']=True;save(folder/'report.json',report)
    if bank_worker:
        say('恢复快门声音包，保留其他提示音和色彩设置…')
        bank_result=bank_worker['result'];bank_stage=bank_result.replace('.result','.stage.so');bank_blob=bank_worker['blob']
        if io.read('/cp/SysSound.bin',76992)!=snapshots['/cp/SysSound.bin']:raise ValueError('声音包在恢复前发生变化')
        io.put(bank_stage,bank_blob,native=True)
        if io.read(bank_stage,65536)!=bank_blob:raise ValueError('声音包辅助程序核对失败')
        report['bank_native_attempted']=True;save(folder/'report.json',report)
        io.put(lib,bank_blob,native=True)
        bank_raw=io.read(bank_result,65536);(folder/'bank_native_result.bin').write_bytes(bank_raw);bank_native=bank_worker['parser'](bank_raw)
        report['bank_native']={k:(v.hex() if isinstance(v,bytes) else v) for k,v in bank_native.items()};save(folder/'report.json',report)
        if not bank_native['complete']:raise ValueError('加载程序已更新，但声音包恢复未完成；保留报告，不自动重试')
        for path,(size,digest) in {'/usr/lib/appFw.so':(93620512,after['app_sha256']),**state_pins(after)}.items():
            data=io.read(path,size)
            if len(data)!=size or sha(data)!=digest:raise ValueError('原厂恢复最终核对失败：'+path)
        io.clean(bank_stage,bank_blob);io.clean(lib,bank_blob)
        report['sound_bank_verified']=True
    report['complete']=True;report['cold_boot_listening_verified']=False;save(folder/'report.json',report)
    save(ROOT/'previous.json',before);save(ROOT/'current.json',after)
    (ROOT/'pending.json').unlink()
    say('写入并回读成功。拔线、关机、等指示灯熄灭，取出电池一分钟后开机试听。')

def _install(target,power):
    if not power:raise ValueError('请先确认电量超过 50%')
    if (ROOT/'pending.json').exists():raise ValueError('有未确认的写入记录，已阻止再次写入。请保留 pending.json 和报告。')
    before=current_state();after=factory_sound.factory_state(sys.modules[__name__]) if target=='factory' else load(target);materialize(before);materialize(after)
    if before['app_sha256']==after['app_sha256']:raise ValueError('所选声音已是工具记录的当前版本，不重复写入')
    folder=ROOT/'operations'/uuid.uuid4().hex[:16];folder.mkdir(parents=True)
    report={'complete':False,'camera_io':False,'events':[],'mutation_started':False,'before_name':before['name'],'after_name':after['name']}
    save(folder/'before.json',before);save(folder/'after.json',after)
    try:
        say('在电脑上检查本次写入与失败回退流程…')
        blob,result,harness=build_worker(folder,before,after)
        # Prepare and emulate the exact inverse before permitting any camera access.
        inverse=folder/'inverse';inverse.mkdir();build_worker(inverse,after,before)
        bank_worker=None
        if bank_hash(before)!=bank_hash(after):
            say('检查原厂声音槽位的恢复与失败回退…')
            bank_worker=factory_sound.build_bank_worker(sys.modules[__name__],folder/'bank',bank_hash(before),bank_hash(after))
        report['forward_and_inverse_tests_passed']=True;save(folder/'report.json',report)
        sys.path.insert(0,str(Path(CFG['toolkit'])/'Sony-PMCA-RE'))
        from pmca.commands.usb import senserShellCommand
        def callback(camera):
            report['camera_io']=True
            paths={'/version.txt','/usr/lib/appFw.so',*PINS,'/etc/ld.so.preload','/tmp/jiritsu/libJit.so',result,result.replace('.result','.stage.so')}
            paths.update(s['audio_path'] for s in (before,after) if s.get('audio_path'))
            if bank_worker:paths.update((bank_worker['result'],bank_worker['result'].replace('.result','.stage.so')))
            transact(CameraIO(camera,paths,report['events']),folder,report,before,after,blob,result,harness.parse,bank_worker)
        senserShellCommand(driverName='libusb',complete=callback)
        if not report['complete']:raise ValueError('没有完成相机操作。请开机并以 USB 海量存储器模式连接。')
    except Exception as e:
        report['error']=str(e);raise
    finally:save(folder/'report.json',report);say('报告：'+str(folder/'report.json'))

def install(target,power):
    import msvcrt
    # Lock lifetime is the process lifetime; a crash cannot leave a stale held lock.
    with (ROOT/'operation.lock').open('a+b') as lock:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise ValueError('另一个窗口正在操作相机，请等待完成')
        try:return _install(target,power)
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='command',required=True)
    a=s.add_parser('prepare');a.add_argument('source');a.add_argument('--gain',type=float,default=1)
    a=s.add_parser('install');a.add_argument('target');a.add_argument('--power-confirmed',action='store_true')
    a=s.add_parser('restore');a.add_argument('--power-confirmed',action='store_true')
    a=s.add_parser('factory');a.add_argument('--power-confirmed',action='store_true')
    a=s.add_parser('detect')
    args=p.parse_args()
    try:
        if args.command=='prepare':prepare(args.source,args.gain)
        elif args.command=='install':install(args.target,args.power_confirmed)
        elif args.command=='factory':install('factory',args.power_confirmed)
        elif args.command=='restore':
            if not (ROOT/'previous.json').exists():raise ValueError('还没有用本工具替换过声音，因此没有上一版可恢复')
            install(ROOT/'previous.json',args.power_confirmed)
        else:
            text=run(['powershell','-NoProfile','-Command',"Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB*VID_054C*' } | Select-Object -ExpandProperty InstanceId"],timeout=30).decode('utf-8','replace')
            say('检测到 Sony USB 设备；写入时将继续核对机型和固件。' if text.strip() else '未检测到 Sony USB 设备，请选择海量存储器模式并连接。')
    except Exception as e:say('未完成：'+str(e));return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
