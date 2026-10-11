import datetime as dt, os, json, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.durable_audit_v36 import DurableAudit

T=dt.datetime(2026,10,11,12,0)
def at(h):return (T+dt.timedelta(hours=h)).isoformat()

class DurableAuditCases(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)
        self.a=DurableAudit.initialize(self.path,['paris museums tickets','berlin rail timetable','tokyo gardens','seoul cafes'],at(0))
        self.a.cut('c0',at(0),2,['m0','m1'])
    def tearDown(self):
        self.a.close();self.temp.cleanup()
    def child(self, action, stage):
        code=('import sys; from experiments.durable_audit_v36 import DurableAudit; '
              'a=DurableAudit(sys.argv[1],signing=True); '
              + ('a.write("m0",.7,sys.argv[2],crash=sys.argv[3])' if action=='write' else 'a.expire(sys.argv[2],crash=sys.argv[3])'))
        r=subprocess.run([sys.executable,'-c',code,str(self.path),at(1 if action=='write' else 3),stage],cwd=str(Path(__file__).resolve().parents[1]),capture_output=True)
        return r.returncode
    def refresh(self):
        self.a.close();self.a=DurableAudit(self.path,signing=True)
    def test_beforeimages_and_chain_persist(self):
        self.a.write('m0',.7,at(1));self.refresh()
        self.assertEqual(self.a.state()['m0']['importance'],.7)
        self.assertEqual(self.a.counts()['witnesses'],1)
        self.assertEqual(self.a.verify()['events'],3)
        self.assertNotIn('"old"', ''.join(row['payload'] for row in self.a.conn.execute('SELECT payload FROM events')))
    def test_unpermitted_field_cannot_be_retained(self):
        self.a.write('m3',.8,at(1));self.assertEqual(self.a.counts()['witnesses'],0)
        self.assertEqual(self.a.verify()['events'],3)
    def test_incomplete_transaction_event_insert_crash(self):
        self.assertEqual(self.child('write','after_event'),73);self.refresh()
        self.assertEqual(self.a.state()['m0']['importance'],.1)
        self.assertEqual(self.a.counts()['events'],2)
        self.assertEqual(self.a.counts()['witnesses'],0)
    def test_after_state_update_crash_rolls_everything_back(self):
        self.assertEqual(self.child('write','after_state'),74);self.refresh()
        self.assertEqual(self.a.counts()['events'],2)
        self.assertEqual(self.a.counts()['witnesses'],0)
        self.assertEqual(self.a.state()['m0']['importance'],.1)
    def test_after_commit_crash_recovers_exactly_once_state(self):
        self.assertEqual(self.child('write','after_commit'),75);self.refresh()
        self.assertEqual(self.a.state()['m0']['importance'],.7)
        self.assertEqual(self.a.counts()['events'],3)
        self.assertEqual(self.a.counts()['witnesses'],1)
        self.assertEqual(self.a.verify()['events'],3)
    def test_expiry_deletes_evidence_but_keeps_signed_tombstone(self):
        self.a.write('m0',.7,at(1))
        self.assertEqual(self.a.expire(at(3)),['c0'])
        self.refresh()
        self.assertEqual(self.a.counts()['witnesses'],0)
        self.assertEqual(self.a.counts()['expired_cuts'],1)
        self.assertEqual(self.a.verify()['events'],4)
        self.assertIn('EXPIRE',self.a.conn.execute('SELECT payload FROM events ORDER BY seq DESC LIMIT 1').fetchone()[0])
    def test_expiry_is_transactional_on_crash(self):
        self.a.write('m0',.7,at(1))
        self.assertEqual(self.child('expire','after_delete'),76)
        self.refresh()
        self.assertEqual(self.a.counts()['witnesses'],1)
        self.assertEqual(self.a.counts()['active_cuts'],1)
    def test_new_write_automatically_expires_receipts(self):
        self.a.write('m0',.7,at(1))
        self.a.write('m1',.9,at(3))
        self.assertEqual(self.a.counts()['witnesses'],0)
        self.assertEqual(self.a.counts()['active_cuts'],0)
    def test_tampered_receipt_is_rejected(self):
        self.a.write('m0',.7,at(1))
        self.a.conn.execute("UPDATE witnesses SET old_json='0.91'")
        with self.assertRaises(ValueError):self.a.verify()
    def test_tampered_event_rejected(self):
        self.a.write('m0',.7,at(1))
        self.a.conn.execute("UPDATE events SET payload='{}' WHERE seq=2")
        with self.assertRaises(ValueError):self.a.verify()
    def test_reader_mode_no_signing_key(self):
        self.a.write('m0',.7,at(1))
        r=DurableAudit(self.path,signing=False)
        self.assertEqual(r.verify()['events'],3)
        with self.assertRaises(AssertionError):r.write('m1',.8,at(1.3))
        r.close()
    def test_cut_zero_negative_ttl_rejected(self):
        with self.assertRaises(ValueError):self.a.cut('x',at(0),0,['m0'])

if __name__=='__main__':unittest.main()

class IdempotencyCases(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.p=Path(self.temp.name)
        self.a=DurableAudit.initialize(self.p,['p','q','r'],at(0));self.a.cut('c0',at(0),24,['m0'])
    def tearDown(self):self.a.close();self.temp.cleanup()
    def test_retry_after_commit_crash_is_exactly_once(self):
        code='from experiments.durable_audit_v36 import DurableAudit;import sys;a=DurableAudit(sys.argv[1],signing=True);a.write("m0",.77,sys.argv[2],crash="after_commit",request_id="w-123")'
        r=subprocess.run([sys.executable,'-c',code,str(self.p),at(1)],cwd=str(Path(__file__).resolve().parents[1]))
        self.assertEqual(r.returncode,75)
        self.a.close();self.a=DurableAudit(self.p,signing=True)
        before=self.a.counts()
        seq=self.a.write('m0',.77,at(1),request_id='w-123')
        self.assertEqual(seq,2)
        self.assertEqual(before,self.a.counts())
        with self.assertRaises(ValueError):self.a.write('m0',.78,at(1),request_id='w-123')
    def test_retention_expiry_is_enforced_by_audit_clock(self):
        self.a.write('m0',.7,at(1),request_id='w')
        self.a.conn.execute('UPDATE cuts SET expires=? WHERE id=?',(at(2),'c0'))
        self.assertEqual(self.a.audit('c0',2,now=at(3)),'UNVERIFIABLE')