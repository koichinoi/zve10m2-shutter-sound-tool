"""Pinned factory assets and bounded SysSound restoration; no USB on import."""
from pathlib import Path
import json

STOCK_APP_SHA='bf000e13f33109cfd09152777480de196bc6dd7a25c8d2e9d5c3e6829dc23d92'
STOCK_BANK_SHA='b4804e635e45e37d8f19e56c2329850c168869adbd1ec777cd713d7b791c8151'
CUSTOM_BANK_SHA='1123da9768aa060807b3536838271ca897cf8236af30515b6f6a6b8ce1a4475d'

def bank_bytes(b,digest):
    files={STOCK_BANK_SHA:'original_SysSound.bin',CUSTOM_BANK_SHA:'custom_SysSound.bin'}
    if digest not in files:raise ValueError('声音包版本不在已核对的范围内')
    data=(b.WORK/'restore_v0_1'/files[digest]).read_bytes()
    if len(data)!=76992 or b.sha(data)!=digest:raise ValueError('本地声音包备份校验失败')
    return data

def stock_app(b):
    data=(b.RESEARCH/'sound_code/nflasha15_appFw.so').read_bytes()
    if len(data)!=93620512 or b.sha(data)!=STOCK_APP_SHA:raise ValueError('原厂加载程序备份校验失败')
    return data

def factory_state(b):
    stock_app(b);bank_bytes(b,STOCK_BANK_SHA)
    return {'name':'原厂快门声音','factory':True,'app_sha256':STOCK_APP_SHA,
            'sound_bank_sha256':STOCK_BANK_SHA,'audio_path':None,'hardware_verified':False}

def build_bank_worker(b,folder,before_digest,after_digest):
    """Reuse the tested fixed-window worker, retarget ONLY SysSound's 2944-byte slot."""
    folder.mkdir(parents=True,exist_ok=True)
    old=bank_bytes(b,before_digest);new=bank_bytes(b,after_digest)
    if old[:3200]!=new[:3200] or old[6144:]!=new[6144:]:raise ValueError('声音包差异超出快门槽位')
    edits=[(at,old[at:min(at+256,6144)],new[at:min(at+256,6144)]) for at in range(3200,6144,256)]
    assert len(edits)==12
    source_root=b.WORK/'fl23_research/cp_worker_v1'
    source=(source_root/'cp_data_worker.c').read_text(encoding='utf-8')
    source=source.replace('/cp/cpapp-b.bin','/cp/SysSound.bin').replace('17387368UL','76992UL')
    (folder/'cp_data_worker.c').write_text(source,encoding='utf-8')
    result_template='/tmp/jiritsu/zvs_'+folder.parent.name+'_bank{mode}.result'
    for restore in (False,True):
        mode='restore' if restore else 'apply'
        windows=[(at,y,x) for at,x,y in reversed(edits)] if restore else edits
        lines=[f'#define WORKER_MODE {int(restore)}',f'#define RESULT_PATH "{result_template.format(mode=mode)}"'];entries=[]
        for i,(at,x,y) in enumerate(windows):
            for name,data in (('before',x),('after',y)):
                lines.append(f'static const u8 {name}_{i}[]={{'+','.join(map(str,data))+'};')
            entries.append(f'{{{at}UL,{len(x)},before_{i},after_{i}}}')
        lines.append('static const struct Window windows[]={'+','.join(entries)+'};')
        (folder/f'cp_data_{mode}.h').write_text('\n'.join(lines),encoding='ascii')
        b.run([b.CFG['zig'],'cc','-target','aarch64-linux-gnu','-shared','-fPIC','-O2','-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-unwind-tables','-fno-asynchronous-unwind-tables','-nostdlib','-g0','-Wl,--strip-debug','-Wl,--no-undefined','-Wl,-Bsymbolic','-Wl,-z,noexecstack','-DCP_DATA_MANIFEST="cp_data_'+mode+'.h"','-o',folder/f'cp_data_{mode}.so',folder/'cp_data_worker.c'],timeout=120)
    plan={'edits':[{'offset':at,'before_hex':x.hex(),'after_hex':y.hex()} for at,x,y in edits]}
    b.save(folder/'bank_plan.json',plan)
    harness=(source_root/'build_test_cp_worker.py').read_text(encoding='utf-8')
    start=harness.index('PLAN=json.loads(');end=harness.index('\ndef sha(',start)
    harness=harness[:start]+"PLAN=json.loads((ROOT/'bank_plan.json').read_text(encoding='utf-8'))\nEDITS=[(e['offset'],bytes.fromhex(e['before_hex']),bytes.fromhex(e['after_hex'])) for e in PLAN['edits']]\nassert len(EDITS)==12\n"+harness[end:]
    harness=harness.replace('/cp/cpapp-b.bin','/cp/SysSound.bin').replace('17387367 if','76991 if').replace('else 17387368','else 76992')
    harness=harness.replace("f'/tmp/jiritsu/zve10m2.insh{mode}.result'","f'"+result_template+"'")
    harness=harness.replace("def emulate(kind='success',fault_index=None,restore=False):","def emulate(kind='success',fault_index=None,restore=False,return_raw=False):")
    harness=harness.replace("    return {'case':kind", "    if return_raw:return bytes(out)\n    return {'case':kind")
    (folder/'bank_test.py').write_text(harness,encoding='utf-8')
    test=b.module('generated_bank_test',folder/'bank_test.py')
    basic=('success','already_zero','eintr','short_reads','short_writes','existing_result','not_root','valid_wbi','wbi_read_error','wrong_device','bad_mode','mode_write_failure','mode_close_failure','wrong_source','cp_open_failure','wrong_size','not_regular','changed_inode','reopen_changed','journal_before','cp_close_failure','initial_journal_write','initial_journal_partial','initial_journal_sync','final_journal_failure','preflight_read_error','recheck_read_error')
    indexed=('partial_write','write_error','sync_error','readback_error','journal_after','foreign_readback','rollback_read_error','rollback_write_error','rollback_sync_error','rollback_inode_error')
    cases=[]
    for restore in (False,True):
        cases += [dict(test.emulate(case,restore=restore),restore=restore) for case in basic]
        cases += [dict(test.emulate(case,i,restore),restore=restore) for case in indexed for i in range(12)]
    b.save(folder/'bank_tests.json',{'passed':True,'camera_io':False,'cases':cases,'only_sound_slot_written':True,'before_sha256':before_digest,'after_sha256':after_digest})
    return {'blob':(folder/'cp_data_apply.so').read_bytes(),'result':result_template.format(mode='apply'),'parser':test.parse,'harness':test}
