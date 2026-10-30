"""End-to-end factory restoration with simulated camera storage; no USB."""
import copy, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import backend as b
import factory_sound as f

class Camera:
    def __init__(self,before,after,ap,bank,case):
        self.before=before;self.after=after;self.ap=ap;self.bank=bank;self.case=case;self.calls=[];self.bank_called=False
        self.files={'/version.txt':b'33002_03.2025101101','/usr/lib/appFw.so':b.materialize(before),
          '/cp/cpapp-b.bin':(b.WORK/'fl23_research/in_sh_replacement_candidate_v1/cp_cpapp-b.candidate.bin').read_bytes(),
          '/usr/lib/libJiritsu.so':(b.RESEARCH/'sound_code/libJiritsu.so').read_bytes(),
          '/cp/SysSound.bin':f.bank_bytes(b,b.bank_hash(before))}
        if before.get('audio_path'):self.files[before['audio_path']]=Path(before['audio_file']).read_bytes()
        self.original_cp=self.files['/cp/cpapp-b.bin'];self.original_bank=self.files['/cp/SysSound.bin']
        if case=='wrong_bank':self.files['/cp/SysSound.bin']=b'bad'
        if case=='foreign_bank_helper':self.files[bank['result']]=b'unknown'
    def read(self,path,limit,optional=False):
        self.calls.append(('read',path))
        if path not in self.files:
            if optional:return None
            raise FileNotFoundError(path)
        value=self.files[path];assert len(value)<=limit;return value
    def put(self,path,content,native=False):
        self.calls.append(('write',path));self.files[path]=content
        if path!='/tmp/jiritsu/libJit.so':return
        if content==self.ap[0]:
            if self.case=='ap_usb_loss':raise OSError('AP reply lost')
            failure=self.case=='ap_failure'
            self.files[self.ap[1]]=self.ap[2].run('guard_partial' if failure else 'success',return_raw=True)
            if not failure:self.files['/usr/lib/appFw.so']=b.materialize(self.after)
            del self.files[path]
        elif content==self.bank['blob']:
            self.bank_called=True
            # The AP must already match its target in full before touching SysSound.
            assert b.sha(self.files['/usr/lib/appFw.so'])==self.after['app_sha256']
            if self.case=='bank_usb_loss':raise OSError('bank reply lost')
            failure=self.case=='bank_failure'
            self.files[self.bank['result']]=self.bank['harness'].emulate('partial_write' if failure else 'success',5 if failure else None,return_raw=True)
            if not failure:self.files['/cp/SysSound.bin']=f.bank_bytes(b,b.bank_hash(self.after))
            if self.case=='bank_mismatch':self.files['/cp/SysSound.bin']=bytes(76992)
            if self.case=='colour_mismatch':self.files['/cp/cpapp-b.bin']=bytes(len(self.original_cp))
        else:raise AssertionError('Unknown native code')
    def clean(self,path,expected):
        self.calls.append(('clean',path))
        if path in self.files:assert self.files[path]==expected;del self.files[path]

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.custom=b.initial_state();cls.stock=f.factory_state(b);cls.root=b.ROOT/'factory_checks'
        def ap(name):
            path=cls.root/name
            return ((path/'permanent_program_installer.so').read_bytes(),'/tmp/jiritsu/zvs_'+name+'.result',b.module(name+'_test',path/'worker_test.py'))
        cls.forward=ap('app_restore');cls.inverse=ap('app_reinstall')
        test=b.module('bank_host_harness',cls.root/'bank/bank_test.py')
        cls.bank={'blob':(cls.root/'bank/cp_data_apply.so').read_bytes(),'result':'/tmp/jiritsu/zvs_factory_checks_bankapply.result','parser':test.parse,'harness':test}
        cls.bank_inverse={'blob':(cls.root/'bank/cp_data_restore.so').read_bytes(),'result':'/tmp/jiritsu/zvs_factory_checks_bankrestore.result','parser':test.parse,'harness':type('InverseHarness',(),{'emulate':staticmethod(lambda *a,**kw:test.emulate(*a,restore=True,**kw))})}
    def scenario(self,case='success',inverse=False):
        before,after=(self.stock,self.custom) if inverse else (self.custom,self.stock)
        ap=self.inverse if inverse else self.forward;bank=self.bank_inverse if inverse else self.bank
        io=Camera(before,after,ap,bank,case);report={'complete':False,'events':[]};error=None
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'op';folder.mkdir()
            with patch.object(b,'ROOT',root):
                try:b.transact(io,folder,report,before,after,*ap[:2],ap[2].parse,bank)
                except Exception as e:error=e
                current=b.load(root/'current.json') if (root/'current.json').exists() else None
                previous=b.load(root/'previous.json') if (root/'previous.json').exists() else None
                pending=(root/'pending.json').exists()
        return io,report,error,current,previous,pending
    def test_factory_success_keeps_colour(self):
        io,r,e,current,previous,pending=self.scenario()
        self.assertIsNone(e);self.assertTrue(r['complete']);self.assertTrue(r['app_verified']);self.assertTrue(r['sound_bank_verified']);self.assertFalse(pending)
        self.assertEqual(b.sha(io.files['/usr/lib/appFw.so']),f.STOCK_APP_SHA)
        self.assertEqual(b.sha(io.files['/cp/SysSound.bin']),f.STOCK_BANK_SHA)
        self.assertEqual(io.files['/cp/cpapp-b.bin'],io.original_cp);self.assertEqual(previous,self.custom);self.assertTrue(current['factory'])
        self.assertIn(self.custom['audio_path'],io.files)
    def test_previous_custom_can_be_reinstalled_after_factory(self):
        io,r,e,current,previous,pending=self.scenario(inverse=True)
        self.assertIsNone(e);self.assertTrue(r['complete']);self.assertFalse(pending)
        self.assertEqual(current,self.custom);self.assertTrue(previous['factory'])
        self.assertEqual(b.sha(io.files['/cp/SysSound.bin']),f.CUSTOM_BANK_SHA)
        self.assertEqual(io.files['/cp/cpapp-b.bin'],io.original_cp)
    def test_preflight_never_writes(self):
        for case in ('wrong_bank','foreign_bank_helper'):
            io,r,e,cur,prev,pending=self.scenario(case)
            self.assertIsNotNone(e);self.assertFalse(any(c[0]=='write' for c in io.calls));self.assertFalse(pending)
    def test_ap_failure_never_starts_bank(self):
        for case in ('ap_usb_loss','ap_failure'):
            io,r,e,cur,prev,pending=self.scenario(case)
            self.assertIsNotNone(e);self.assertFalse(io.bank_called);self.assertTrue(pending);self.assertIsNone(cur)
    def test_partial_factory_not_reported_success(self):
        for case in ('bank_usb_loss','bank_failure','bank_mismatch','colour_mismatch'):
            io,r,e,cur,prev,pending=self.scenario(case)
            self.assertIsNotNone(e);self.assertFalse(r['complete']);self.assertTrue(r['app_verified']);self.assertTrue(pending);self.assertIsNone(cur)
            self.assertEqual(sum(c==('write','/tmp/jiritsu/libJit.so') for c in io.calls),2)
    def test_only_shutter_bytes_differ(self):
        a=f.bank_bytes(b,f.CUSTOM_BANK_SHA);z=f.bank_bytes(b,f.STOCK_BANK_SHA)
        self.assertEqual(a[:3200],z[:3200]);self.assertEqual(a[6144:],z[6144:])
        self.assertNotEqual(a[3200:6144],z[3200:6144])
    def test_factory_plan_disables_hook_first(self):
        plan=b.load(self.root/'app_restore/plan.json')
        self.assertEqual([e['offset'] for e in plan['edits']],[0x2d5039c,0x60,b.OFF])
        plan=b.load(self.root/'app_reinstall/plan.json')
        self.assertEqual([e['offset'] for e in plan['edits']],[b.OFF,0x60,0x2d5039c])
    def test_unknown_factory_metadata_rejected(self):
        bad=copy.deepcopy(self.stock);bad['app_sha256']=b.INITIAL_SHA
        with self.assertRaises(ValueError):b.materialize(bad)

if __name__=='__main__':unittest.main(verbosity=2)
