#!/usr/bin/env python3
"""Transactional-outbox coordination between authoritative audit SQLite and a
separate durable HTTP vector index. Single coordinator writer, fail-closed gate.
Not distributed ACID, distributed consensus, durable key management, or a
production retrieval service. All write/read operations must pass this gateway.
"""
import datetime as dt, json, os, sqlite3, urllib.error, urllib.request
from pathlib import Path
from unittest.mock import patch
from experiments.durable_audit_v36 import DurableAudit, sha, enc, parse
from experiments.persistent_vector_service_v37 import digest

class DivergenceError(RuntimeError):pass
class IndexUnavailable(RuntimeError):pass

def http(base,path,payload=None):
    try:
        data=enc(payload).encode() if payload is not None else None
        req=urllib.request.Request(base+path,data=data,headers={'Content-Type':'application/json'},method='POST' if payload is not None else 'GET')
        with urllib.request.urlopen(req,timeout=3) as r:return json.load(r)
    except (urllib.error.HTTPError,) as e:
        raise DivergenceError(f'index rejected {path} HTTP {e.code}: {e.read()[:200]!r}') from e
    except (urllib.error.URLError,ConnectionError,TimeoutError) as e:
        raise IndexUnavailable(str(e)) from e

class RemoteStore:
    """A LangChain vectorstore adapter is built dynamically to preserve the
    real pinned TimeWeightedVectorStoreRetriever code unchanged."""
    @staticmethod
    def make(url,expected_version):
        from langchain_core.vectorstores import InMemoryVectorStore
        from langchain_core.embeddings import Embeddings
        from langchain_core.documents import Document
        class NoopEmb(Embeddings):
            def embed_query(self,text):raise RuntimeError('not used')
            def embed_documents(self,texts):raise RuntimeError('not used')
        class NetworkStore(InMemoryVectorStore):
            def similarity_search_with_relevance_scores(self,query,**kwargs):
                result=http(url,'/search',{'query':query,'k':kwargs.get('k',100)})
                if result['revision']['version']!=expected_version:raise DivergenceError('index revision changed during native search')
                return [(Document(page_content=r['text'],metadata={'item_id':r['id'],'buffer_idx':r['buffer_idx']}),r['score']) for r in result['hits']]
        return NetworkStore(NoopEmb())

class Coordinator(DurableAudit):
    def __init__(self,root,url,signing=True):
        super().__init__(root,signing=signing)
        self.url=url
        self.conn.execute('CREATE TABLE IF NOT EXISTS outbox(version INTEGER PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE, payload_hash TEXT NOT NULL, state_json TEXT NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    @classmethod
    def initialize(cls,root,url,texts,now):
        d=DurableAudit.initialize(root,texts,now);d.close()
        c=cls(root,url,True);c._start()
        try:
            state=c.state()
            c.conn.execute('INSERT INTO outbox VALUES(0,?,?,?,0)',('bootstrap',digest(state),enc(state)))
            c.conn.commit()
        except Exception:c.conn.rollback();raise
        c.recover()
        return c
    def version(self):return self.conn.execute('SELECT MAX(version) FROM outbox').fetchone()[0]
    def recovery_counts(self):
        return {'version':self.version(),'pending':self.conn.execute('SELECT count(*) FROM outbox WHERE acknowledged=0').fetchone()[0],
                'applied':self.conn.execute('SELECT count(*) FROM outbox WHERE acknowledged=1').fetchone()[0]}
    def _assert_index(self):
        v=self.version();d=http(self.url,'/state');current=d['revision']
        if current['version']!=v or current['payload_hash']!=digest(self.state()):raise DivergenceError('index version or state hash mismatch')
        state=d['state'];normalized={id:{k:x for k,x in doc.items() if k!='buffer_idx'} for id,doc in state.items()}
        if normalized!=self.state():raise DivergenceError('index metadata mismatch')
        return v
    def recover(self,inject=None):
        for r in self.conn.execute('SELECT * FROM outbox WHERE acknowledged=0 ORDER BY version').fetchall():
            body={'version':r['version'],'operation_id':r['operation_id'],'payload_hash':r['payload_hash'],'state':json.loads(r['state_json'])}
            if inject=='service_post_commit':body['inject']='service_post_commit'
            ans=http(self.url,'/apply',body)
            if ans['version']!=r['version'] or ans['payload_hash']!=r['payload_hash']:raise DivergenceError('bad apply ack')
            if inject=='after_apply':os._exit(85)
            self._start()
            try:
                self.conn.execute('UPDATE outbox SET acknowledged=1 WHERE version=? AND operation_id=?',(r['version'],r['operation_id']))
                self.conn.commit()
            except Exception:self.conn.rollback();raise
        self._assert_index()
    def _commit_v37(self,kind,when,changes,extra,request_id,crash=None):
        # Requires a held coordinator writer lock. Non-retried duplicate requests
        # are checked by the outer caller before expensive native invocation.
        before=self.state();old={};changed={}
        for id,fields in changes.items():
            for field,new in fields.items():
                if field not in ('importance','last_accessed_at'):raise ValueError('unsupported update')
                if field=='importance' and not (0<=float(new)<=1):raise ValueError('importance out of bounds')
                if before[id][field]!=new:
                    old[id+'.'+field]=before[id][field];changed[id+'.'+field]=new
        if not changed:raise ValueError('no updates')
        self._expire_in_tx(when)
        payload={'kind':kind,'time':when,'updated_keys':sorted(changed),'request_id':request_id}
        payload.update(extra)
        seq=self._event(payload)
        fp=sha(enc({'kind':kind,'when':when,'updates':changes,'extra':extra}).encode())
        self.conn.execute('INSERT INTO operations VALUES(?,?,?,?)',(request_id,seq,kind,fp))
        if crash=='after_event':os._exit(81)
        self._witnesses(seq,old)
        for key,val in changed.items():
            id,field=key.split('.');self.conn.execute(f'UPDATE items SET {field}=? WHERE id=?',(val,id))
        nxt=self.version()+1;state=self.state()
        self.conn.execute('INSERT INTO outbox VALUES(?,?,?,?,0)',(nxt,request_id,digest(state),enc(state)))
        if crash=='before_commit':os._exit(82)
        self.conn.commit()
        if crash=='after_coordinator_commit':os._exit(83)
        self.recover(inject=crash if crash in ('after_apply','service_post_commit') else None)
        if crash=='after_ack':os._exit(86)
        return seq
    def _duplicate(self,op_id,kind,when,args):
        r=self.conn.execute('SELECT seq,kind FROM operations WHERE op_id=?',(op_id,)).fetchone()
        if not r:return None
        if r['kind']!=kind:raise ValueError('request ID reused across operation types')
        event=json.loads(self.conn.execute('SELECT payload FROM events WHERE seq=?',(r['seq'],)).fetchone()['payload'])
        if event['time']!=when:raise ValueError('request ID reused with different time')
        if kind=='WRITE' and (event['id']!=args['id'] or event['value']!=args['value']):raise ValueError('request ID payload mismatch')
        if kind=='READ' and event['query']!=args['query']:raise ValueError('request ID query mismatch')
        return event
    def write(self,id,value,when,request_id,crash=None):
        self.recover();self._start()
        try:
            prev=self._duplicate(request_id,'WRITE',when,{'id':id,'value':value})
            if prev:self.conn.commit();return prev['seq']
            self._assert_index()
            seq=self._commit_v37('WRITE',when,{id:{'importance':value}},{'id':id,'value':value},request_id,crash)
            return seq
        except Exception:
            if self.conn.in_transaction:self.conn.rollback()
            raise
    def read(self,query,when,upstream_path,request_id,crash=None):
        self.recover();self._start()
        try:
            prev=self._duplicate(request_id,'READ',when,{'query':query})
            if prev:self.conn.commit();return prev['seq'],prev['selected']
            rev=self._assert_index()
            from langchain_core.documents import Document
            from experiments.locomo_readside_v29 import load_upstream
            mod=load_upstream(Path(upstream_path))
            state=self.state()
            docs=[Document(page_content=d['text'],metadata={'item_id':i,'buffer_idx':pos,'importance':d['importance'],'last_accessed_at':parse(d['last_accessed_at'])}) for pos,(i,d) in enumerate(sorted(state.items()))]
            retriever=mod.TimeWeightedVectorStoreRetriever(vectorstore=RemoteStore.make(self.url,rev),memory_stream=docs,k=2,search_kwargs={'k':len(docs)},decay_rate=.01,other_score_keys=['importance'])
            now=parse(when)
            class Clock(dt.datetime):
                @classmethod
                def now(cls,tz=None):return now
            with patch.object(mod.datetime,'datetime',Clock):selected=[d.metadata['item_id'] for d in retriever.invoke(query)]
            changes={d.metadata['item_id']:{'last_accessed_at':d.metadata['last_accessed_at'].isoformat()} for d in retriever.memory_stream if d.metadata['last_accessed_at'].isoformat()!=state[d.metadata['item_id']]['last_accessed_at']}
            if set(changes)!=set(selected) or len(changes)!=2:raise AssertionError('native read refresh mismatch')
            seq=self._commit_v37('READ',when,changes,{'query':query,'selected':selected},request_id,crash)
            return seq,selected
        except Exception:
            if self.conn.in_transaction:self.conn.rollback()
            raise