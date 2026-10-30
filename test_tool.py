"""Offline safety and functionality checks. Never opens USB."""
import copy, json, struct, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import backend as b

class FakeIO:
    def __init__(self,before,after,blob,result,harness,case):
        self.case=case;self.writes=[];self.calls=[];self.blob=blob;self.result=result;self.harness=harness;self.after=after
        self.files={'/version.txt':b'33002_03.2025101101','/usr/lib/appFw.so':b.materialize(before),
            '/cp/cpapp-b.bin':(b.WORK/'fl23_research/in_sh_replacement_candidate_v1/cp_cpapp-b.candidate.bin').read_bytes(),
            '/usr/lib/libJiritsu.so':(b.RESEARCH/'sound_code/libJiritsu.so').read_bytes(),
            '/cp/SysSound.bin':(b.WORK/'restore_v0_1/custom_SysSound.bin').read_bytes(),
            before['audio_path']:Path(before['audio_file']).read_bytes()}
        if case=='wrong_version':self.files['/version.txt']=b'other'
        if case=='wrong_cp':self.files['/cp/cpapp-b.bin']=b'other'
        if case=='wrong_ap':self.files['/usr/lib/appFw.so']=b'other'
        if case=='foreign_helper':self.files['/tmp/jiritsu/libJit.so']=b'foreign'
        if case=='foreign_audio':self.files[after['audio_path']]=b'foreign'
    def read(self,path,limit,optional=False):
        self.calls.append(('read',path))
        if path not in self.files:
            if optional:return None
            raise FileNotFoundError(path)
        data=self.files[path]
        assert len(data)<=limit
        return data
    def put(self,path,content,native=False):
        self.calls.append(('write',path));self.writes.append(path);self.files[path]=content
        if self.case=='audio_loss' and path==self.after['audio_path']:raise OSError('USB lost')
        if path=='/tmp/jiritsu/libJit.so':
            if self.case=='native_loss':raise OSError('USB lost')
            scenario='guard_partial' if self.case=='native_failure' else 'success'
            self.files[self.result]=self.harness.run(scenario,return_raw=True)
            if self.case!='native_failure':self.files['/usr/lib/appFw.so']=b.materialize(self.after)
            self.files.pop(path)
            if self.case=='bad_postread':self.files['/cp/cpapp-b.bin']=b'changed'
    def clean(self,path,expected):
        self.calls.append(('clean',path))
        if path in self.files:assert self.files[path]==expected;del self.files[path]

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=b.initial_state();cls.after=b.load(max((b.ROOT/'sounds').glob('*/state.json'),key=lambda p:p.stat().st_mtime))
        folder=b.ROOT/'offline_checks/forward'
        cls.blob,cls.result,cls.harness=b.build_worker(folder,cls.before,cls.after)
    def scenario(self,case):
        io=FakeIO(self.before,self.after,self.blob,self.result,self.harness,case)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'operation';folder.mkdir();report={'complete':False,'events':[]};error=None
            with patch.object(b,'ROOT',root):
                try:b.transact(io,folder,report,self.before,self.after,self.blob,self.result,self.harness.parse)
                except Exception as e:error=e
                pending=(root/'pending.json').exists()
                current=b.load(root/'current.json') if (root/'current.json').exists() else None
            if error:self.assertFalse(report['complete'])
        return io,report,error,pending,current
    def test_success_and_preservation(self):
        io,r,error,pending,current=self.scenario('success')
        self.assertIsNone(error);self.assertTrue(r['complete']);self.assertFalse(pending)
        self.assertEqual(current['app_sha256'],self.after['app_sha256']);self.assertTrue(r['backup_verified'])
        self.assertEqual(io.writes,[self.after['audio_path'],self.result.replace('.result','.stage.so'),'/tmp/jiritsu/libJit.so'])
    def test_preflight_failures_do_not_write(self):
        for case in ('wrong_version','wrong_ap','wrong_cp','foreign_helper','foreign_audio'):
            with self.subTest(case=case):
                io,r,error,pending,current=self.scenario(case)
                self.assertIsNotNone(error);self.assertEqual(io.writes,[]);self.assertFalse(pending);self.assertIsNone(current)
    def test_losses_stop_without_retry(self):
        for case in ('audio_loss','native_loss'):
            with self.subTest(case=case):
                io,r,error,pending,current=self.scenario(case)
                self.assertIsInstance(error,OSError);self.assertTrue(pending);self.assertIsNone(current)
                self.assertEqual(io.calls[-1][0],'write');self.assertEqual(len(io.writes),len(set(io.writes)))
    def test_native_or_postread_failure_retains_evidence(self):
        for case in ('native_failure','bad_postread'):
            with self.subTest(case=case):
                io,r,error,pending,current=self.scenario(case)
                self.assertIsNotNone(error);self.assertTrue(pending);self.assertIsNone(current)
                self.assertIn(self.result,io.files);self.assertFalse(any(c[0]=='clean' for c in io.calls))
    def test_codec_bounds_and_extremes(self):
        for samples in ([0],[32767,-32768]*100,[0]*14880):
            blob,out=b.encode(samples);self.assertLessEqual(len(blob),15360);self.assertEqual(len(blob)%32,0)
            for i in range(0,len(blob),32):
                self.assertLessEqual(blob[i],8)
                decoded=[(v if v<128 else v-256)*(1<<blob[i]) for v in blob[i+1:i+32]]
                self.assertEqual(decoded,out[i//32*31:i//32*31+31])
        for samples in ([],[0]*14881):
            with self.assertRaises(ValueError):b.encode(samples)
    def test_encoder_matches_hardware_verified_payload(self):
        import wave
        blob=Path(self.before['audio_file']).read_bytes();decoded=[]
        for i in range(0,len(blob),32):decoded.extend((v if v<128 else v-256)*(1<<blob[i]) for v in blob[i+1:i+32])
        with wave.open(str(b.WORK.parent/'outputs/project11_full_audio_preview.wav')) as w:
            frames=w.getnframes();old=list(struct.unpack('<%dh'%frames,w.readframes(frames)))
        encoded,decoded=b.encode(old)
        self.assertEqual(encoded,blob)
    def test_forbidden_audio_path_rejected(self):
        state=copy.deepcopy(self.after);state['audio_path']='/cp/cpapp-b.bin'
        with self.assertRaises(ValueError):b.materialize(state)
    def test_pending_and_power_guards(self):
        with tempfile.TemporaryDirectory() as td,patch.object(b,'ROOT',Path(td)):
            with self.assertRaises(ValueError):b._install('missing',False)
            (Path(td)/'pending.json').write_text('{}')
            with self.assertRaises(ValueError):b._install('missing',True)

if __name__=='__main__':unittest.main(verbosity=2)
