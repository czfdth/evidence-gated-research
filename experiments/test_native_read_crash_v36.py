#!/usr/bin/env python3
"""Separate-process native read crash matrix for pinned LangChain + SQLite.

Assertions: event, witnesses and authoritative state are all rolled back
before COMMIT; all durable after COMMIT; retry with the same request ID
returns prior read without a duplicate native mutation.
"""
import datetime as dt, json, os, subprocess, sys, tempfile
from pathlib import Path
from experiments.durable_audit_v36 import DurableAudit

TEXTS=['paris museums tickets','berlin summer rail','tokyo gardens map','seoul cafes itinerary']
BASE=dt.datetime(2026,10,10,12,0)
def when(h):return (BASE+dt.timedelta(hours=h)).isoformat()

def main():
    if len(sys.argv)!=2:raise SystemExit('pass pinned upstream file path')
    source=str(Path(sys.argv[1]).resolve())
    summary=[]
    for stage,expected in [('after_event',73),('after_state',74),('after_commit',75)]:
        with tempfile.TemporaryDirectory() as td:
            a=DurableAudit.initialize(td,TEXTS,when(0))
            a.cut('cut-native',when(0),24,[f'm{i}' for i in range(4)])
            before=a.state();a.close()
            script=('import sys;from experiments.durable_audit_v36 import DurableAudit;'
                    'a=DurableAudit(sys.argv[1],signing=True);'
                    'a.read("paris museum tickets",sys.argv[2],sys.argv[3],'
                    'crash=sys.argv[4],request_id="read-atomic-1")')
            env=dict(os.environ);env['PYTHONPATH']=str(Path(__file__).resolve().parent.parent)
            x=subprocess.run([sys.executable,'-c',script,td,when(1),source,stage],env=env)
            assert x.returncode==expected,(stage,x.returncode)
            b=DurableAudit(td,signing=True)
            assert b.verify()['events'] in (2,3)
            if stage=='after_commit':
                assert b.counts()['events']==3 and b.counts()['witnesses']==2
                assert b.state()!=before
                counts=b.counts()
                seq,ids=b.read('paris museum tickets',when(1),source,request_id='read-atomic-1')
                assert seq==2 and len(ids)==2
                assert counts==b.counts()
                verdict=b.audit('cut-native',seq,now=when(2))
                assert verdict in ('ACCEPT','REJECT')
            else:
                assert b.counts()['events']==2 and b.counts()['witnesses']==0
                assert b.state()==before
                seq,ids=b.read('paris museum tickets',when(1),source,request_id='read-atomic-1')
                assert seq==2 and len(ids)==2
                assert b.counts()['witnesses']==2
                verdict=b.audit('cut-native',seq,now=when(2))
                assert verdict in ('ACCEPT','REJECT')
            summary.append({'stage':stage,'forced_exit':expected,'recovered_verdict':verdict,'events':b.counts()['events'],'witnesses':b.counts()['witnesses']})
            b.close()
    print('V36_NATIVE_READ_CRASH_PASS',json.dumps(summary,sort_keys=True))

if __name__=='__main__':main()