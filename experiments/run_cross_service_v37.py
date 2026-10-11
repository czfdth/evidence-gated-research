#!/usr/bin/env python3
"""Host-controlled long-horizon cross-process lifecycle and crash recoverability.
Uses the genuine pinned TimeWeightedVectorStoreRetriever source; no external
production vector database, concurrent writers or distributed ACID claim.
"""
import argparse, datetime as dt, json, os, shutil, socket, subprocess, sys, time
from pathlib import Path
from experiments.cross_service_audit_v37 import Coordinator, http, IndexUnavailable, DivergenceError
from experiments.durable_audit_v36 import sha

TEXTS=['paris museums tickets','berlin summer rail','tokyo gardens map','seoul cafes itinerary','rome ancient ruins','london theatre seats','madrid cycling tours','oslo harbor ferry']
QUERIES=['paris museum tickets advice','tokyo gardens and map','berlin summer rail','rome ancient ruins','seoul cafes','london theatre','madrid cycling','oslo harbor']
T=dt.datetime(2026,10,10,12,0)
def at(h):return (T+dt.timedelta(hours=h)).isoformat()
def port():
    s=socket.socket();s.bind(('127.0.0.1',0));n=s.getsockname()[1];s.close();return n
class ProcessService:
    def __init__(self,root):
        self.root=Path(root);self.port=port();self.url=f'http://127.0.0.1:{self.port}';self.p=None
    def start(self):
        if self.p is not None:raise RuntimeError('already running')
        self.p=subprocess.Popen([sys.executable,'-m','experiments.persistent_vector_service_v37','--db',str(self.root/'index.sqlite3'),'--port',str(self.port)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        for _ in range(120):
            if self.p.poll() is not None:raise RuntimeError(f'server failed: {self.p.stderr.read()!r}')
            try:
                http(self.url,'/health');return
            except (IndexUnavailable,ConnectionError):time.sleep(.04)
        raise TimeoutError('service start timeout')
    def stop(self):
        if self.p is not None:
            self.p.terminate()
            try:self.p.wait(timeout=5)
            except subprocess.TimeoutExpired:self.p.kill();self.p.wait()
            self.p.stderr.close();self.p=None
    def restart(self):self.stop();self.start()

def matches(c):
    x=http(c.url,'/state');a={i:{k:v for k,v in d.items() if k!='buffer_idx'} for i,d in x['state'].items()}
    assert a==c.state(),(a,c.state())
    assert x['revision']['version']==c.version()
    assert c.recovery_counts()['pending']==0
    assert c.verify()['events']>0
    return x['revision']['version']

def main():
    a=argparse.ArgumentParser();a.add_argument('--upstream',required=True);a.add_argument('--out',required=True);args=a.parse_args()
    from importlib.metadata import version
    assert version('langchain-core')=='0.3.83'
    from experiments.locomo_readside_v29 import UPSTREAM_SHA
    assert sha(Path(args.upstream).read_bytes())==UPSTREAM_SHA
    root=Path(args.out);root.mkdir(parents=True,exist_ok=True)
    store=root/'coordinator';svc=ProcessService(root/'index-service')
    if store.exists():shutil.rmtree(store)
    if svc.root.exists():shutil.rmtree(svc.root)
    svc.start();c=None
    try:
        c=Coordinator.initialize(store,svc.url,TEXTS,at(0));matches(c)
        outcomes=[];restarts=0;refused=0
        for epoch in range(8):
            if epoch==3:
                svc.stop()
                try:c.read(QUERIES[0],at(epoch*2+.01),args.upstream,'blocked-index-offline')
                except IndexUnavailable:refused+=1
                else:raise AssertionError('read proceeded while index service was offline')
                svc.start();matches(c)
            cut_id=f'cut-{epoch}';c.cut(cut_id,at(epoch*2),100,TEXTS and [f'm{i}' for i in range(8)])
            for j in range(2):
                t=epoch*2+j*.25
                id=f'm{(epoch*3+j)%8}'
                new=round(.13+.06*((epoch*2+j)%8),3)
                if new==c.state()[id]['importance']:new=round(new+.027,3)
                c.write(id,new,at(t+.1),f'write-{epoch}-{j}')
                matches(c)
                seq,ids=c.read(QUERIES[(epoch+j*3)%8],at(t+.2),args.upstream,f'read-{epoch}-{j}')
                label=c.audit(cut_id,seq,now=at(t+.24))
                matches(c)
                outcomes.append({'epoch':epoch,'seq':seq,'selected':ids,'verdict':label,'cut':cut_id})
            c.close();c=None;svc.restart();restarts+=1
            c=Coordinator(store,svc.url,signing=True);c.recover();matches(c)
        assert len(outcomes)==16
        report={'native_reads':16,'read_side_refreshes':32,'writes':16,'cut_count':8,'service_restarts':restarts,'service_unavailable_reads_refused':refused,
                'coord_version':c.version(),'index_revision':http(svc.url,'/health')['version'],
                'outbox':c.recovery_counts(),'ledger':c.verify(),
                'verdicts':{x:sum(r['verdict']==x for r in outcomes) for x in ('ACCEPT','REJECT','UNVERIFIABLE')},
                'limitations':'Separate HTTP vector service with SQLite durable vectors (research backend). Exactly one trusted gateway writer. Replay convergence, NOT distributed atomicity, independent KMS, real neural embeddings, production security, hostile DB writers, or independent service concurrency.'}
        (root/'native-results.json').write_text(json.dumps({'summary':report,'rows':outcomes},indent=2,sort_keys=True))
        print('V37_NATIVE_CROSS_SERVICE',json.dumps(report,sort_keys=True))
    finally:
        if c is not None:c.close()
        svc.stop()

if __name__=='__main__':main()