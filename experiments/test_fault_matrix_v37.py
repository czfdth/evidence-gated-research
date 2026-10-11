#!/usr/bin/env python3
"""Two-process crash and service-partition recovery at each critical point.
Run with original, SHA pinned LangChain source and installed LangChain 0.3.83.
"""
import argparse, datetime as dt, json, os, sqlite3, subprocess, sys, tempfile
from pathlib import Path
from experiments.run_cross_service_v37 import TEXTS, ProcessService, matches, at
from experiments.cross_service_audit_v37 import Coordinator, DivergenceError, IndexUnavailable, http

STAGES={'after_event':81,'before_commit':82,'after_coordinator_commit':83,'after_apply':85,'after_ack':86,'service_post_commit':None}


def one(root,upstream,method,stage):
    svc=ProcessService(root/'index');svc.start();c=None
    try:
        c=Coordinator.initialize(root/'coord',svc.url,TEXTS,at(0));c.cut('cutA',at(0),24,[f'm{i}' for i in range(8)]);c.close();c=None
        child=subprocess.run([sys.executable,'-m','experiments.fault_worker_v37','--root',str(root/'coord'),'--url',svc.url,'--upstream',str(upstream),'--method',method,'--stage',stage],capture_output=True,text=True,timeout=20)
        if stage!='service_post_commit':assert child.returncode==STAGES[stage],(stage,child.returncode,child.stderr)
        else:assert child.returncode!=0,(stage,child.stderr)
        if svc.p.poll() is not None:svc.stop();svc.start()
        c=Coordinator(root/'coord',svc.url,signing=True)
        pending=c.recovery_counts()['pending']
        if stage in ('after_event','before_commit'):
            assert pending==0 and c.version()==0,(stage,c.recovery_counts())
        elif stage=='after_ack':assert pending==0 and c.version()==1
        else:assert pending==1 and c.version()==1,(stage,c.recovery_counts())
        c.recover();matches(c)
        oldver=c.version();oldstate=c.state()
        if method=='WRITE':
            res=c.write('m0',.731,'2026-10-10T12:15:00','crash-target-write')
            assert c.state()['m0']['importance']==.731
            if stage in ('after_event','before_commit'):assert c.version()==oldver+1
            else:assert c.version()==oldver
        else:
            seq,sel=c.read('paris museum tickets','2026-10-10T12:15:00',upstream,'crash-target-read')
            assert len(sel)==2
            if stage in ('after_event','before_commit'):assert c.version()==oldver+1
            else:assert c.version()==oldver
            assert c.audit('cutA',seq,now='2026-10-10T12:18:00')=='ACCEPT'
        matches(c);v=c.version();c.close();c=None
        svc.restart();c=Coordinator(root/'coord',svc.url,signing=True);c.recover();matches(c)
        assert c.version()==v
        return {'method':method,'stage':stage,'child_code':child.returncode,'pre_recovery_pending':pending,'final_version':v,'recovery':'pass'}
    finally:
        if c:c.close()
        svc.stop()


def extra(root):
    svc=ProcessService(root/'index');svc.start();c=None
    try:
        c=Coordinator.initialize(root/'coord',svc.url,TEXTS,at(0))
        svc.stop()
        try:c.write('m0',.731,at(.2),'offline-write')
        except IndexUnavailable:pass
        else:raise AssertionError('write while service unavailable permitted')
        assert c.version()==0
        svc.start();matches(c)
        c.write('m0',.731,at(.2),'offline-write');matches(c)
        # Tamper persistent index without increasing revision. Gateway must fail closed.
        svc.stop()
        p=sqlite3.connect(root/'index'/'index.sqlite3');p.execute("UPDATE docs SET importance=0.123 WHERE id='m0'");p.commit();p.close()
        svc.start()
        try:c.read('paris museum tickets',at(.4),'no-upstream-needed','bad-read')
        except DivergenceError:pass
        else:raise AssertionError('modified index accepted')
        c.close();c=None
        return {'offline_write':'refused','index_divergence':'refused'}
    finally:
        if c:c.close()
        svc.stop()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--upstream',required=True);parser.add_argument('--out',required=True);a=parser.parse_args()
    from importlib.metadata import version
    assert version('langchain-core')=='0.3.83'
    from experiments.locomo_readside_v29 import UPSTREAM_SHA
    from experiments.durable_audit_v36 import sha
    assert sha(Path(a.upstream).read_bytes())==UPSTREAM_SHA
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    results=[]
    with tempfile.TemporaryDirectory(prefix='v37-faults-') as t:
        root=Path(t)
        for method in ('WRITE','READ'):
            for stage in STAGES:
                d=root/(method+'_'+stage);d.mkdir()
                x=one(d,a.upstream,method,stage);results.append(x)
                print('V37_FAULT_PASS',method,stage,'pending',x['pre_recovery_pending'],flush=True)
        d=root/'partitions';d.mkdir();negative=extra(d)
    report={'faults':results,'n_faults':len(results),'failed_oracle_checks':0,'negative_controls':negative,
            'constraints':'Controlled single gateway writer, two SQLite DBs in separate processes, local HTTP, no malicious service compromise or distributed consensus.'}
    (out/'fault-matrix-results.json').write_text(json.dumps(report,sort_keys=True,indent=2))
    print('V37_CROSS_SERVICE_FAULT_PASS',json.dumps({'n_faults':len(results),'negative_controls':negative},sort_keys=True))

if __name__=='__main__':main()