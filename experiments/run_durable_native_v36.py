#!/usr/bin/env python3
"""Run with real pinned langchain-core==0.3.83 + verified upstream .py.

Usage (in an environment with installed pinned deps):
 python experiments/run_durable_native_v36.py --upstream src/time_weighted_retriever_v29.py --out results/v36-durable-native
Creates controlled ephemeral-test keys: never deploy these files as durable keys.
"""
import argparse, datetime as dt, hashlib, json, shutil
from pathlib import Path
from experiments.durable_audit_v36 import DurableAudit, enc, sha

TEXTS=['paris museums tickets','berlin summer rail','tokyo gardens map','seoul cafes itinerary','rome ancient ruins','london theatre seats','madrid cycling tours','oslo harbor ferry']
QUERIES=['paris museum tickets advice','tokyo gardens and map','berlin summer rail','rome ancient ruins','seoul cafes','london theatre','madrid cycling','oslo harbor']
T=dt.datetime(2026,10,10,12,0,0)
def when(hours):return (T+dt.timedelta(hours=hours)).isoformat()

def main():
    p=argparse.ArgumentParser();p.add_argument('--upstream',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    import importlib.metadata
    assert importlib.metadata.version('langchain-core')=='0.3.83','require official pinned package'
    import sys
    from experiments.locomo_readside_v29 import UPSTREAM_SHA
    assert sha(Path(a.upstream).read_bytes())==UPSTREAM_SHA
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    root=out/'working-database'
    if root.exists():shutil.rmtree(root)
    db=DurableAudit.initialize(root,TEXTS,when(0))
    policy=[('hot3',list(range(3)),4),('hot5',list(range(5)),8),('full',list(range(8)),30),('none',[],12)]
    saved=[];rows=[]
    for epoch in range(8):
        t=epoch*2
        name,allowed,ttl=policy[epoch%len(policy)]
        cid=f'cut-{epoch}'
        db.cut(cid,when(t),ttl,[f'm{i}' for i in allowed])
        for step in range(2):
            uid=(epoch*3+step)%8
            db.write(f'm{uid}',round(.11+.07*((epoch+step)%9),3),when(t+.10+step*.25),request_id=f'write-{epoch}-{step}')
            seq,selected=db.read(QUERIES[(epoch+step*3)%8],when(t+.20+step*.25),a.upstream,request_id=f'read-{epoch}-{step}')
            label=db.audit(cid,seq,now=when(t+.30+step*.25))
            saved.append((cid,seq));rows.append({'epoch':epoch,'cut':cid,'read_seq':seq,'returned':selected,'verdict_immediate':label,'policy':name})
        db.close();db=DurableAudit(root,signing=True)
        assert db.verify()['events']>0
    # Re-evaluate cut claims at 16h, while some cuts are already expired.
    db.expire(when(18))
    for r in rows:r['verdict_after_18h']=db.audit(r['cut'],r['read_seq'],now=when(18))
    final={'system':'SQLite WAL FULL + signed append-only receipts','langchain_core':'0.3.83','official_source_sha256':UPSTREAM_SHA,
           'serial_native_reads':len(rows),'explicit_writes':16,'cut_count':8,'read_side_updates':len(rows)*2,
           'verdicts_immediate':{v:sum(r['verdict_immediate']==v for r in rows) for v in ('ACCEPT','REJECT','UNVERIFIABLE')},
           'verdicts_after_18h':{v:sum(r['verdict_after_18h']==v for r in rows) for v in ('ACCEPT','REJECT','UNVERIFIABLE')},
           'persisted_counts':db.counts(),'signatures':db.verify(),'db_file_bytes':db.dbpath.stat().st_size,
           'wal_file_bytes':Path(str(db.dbpath)+'-wal').stat().st_size if Path(str(db.dbpath)+'-wal').exists() else 0,
           'limitations':'Serial in-memory retriever reconstructed from SQLite; no external vector DB atomicity, no forensic erasure, no independent signing root, no autonomous idle purge.'}
    (out/'native-results.json').write_text(json.dumps({'summary':final,'rows':rows},indent=2,sort_keys=True))
    db.close()
    print('V36_DURABLE_NATIVE',json.dumps(final,sort_keys=True))
if __name__=='__main__':main()