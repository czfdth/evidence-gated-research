#!/usr/bin/env python3
"""SQLite transactional audit prototype for a *single authoritative in-memory retriever adapter*.

Research-only, serial/one SQLite writer. The retriever is reconstructed from the
committed SQLite state for every read; vector embeddings are deterministic and
recreated rather than durably indexed. Neither cross-service atomicity nor
production key custody is established. All signed public event payloads exclude
uncaptured old values (the P observation contract).
"""
import base64, datetime as dt, hashlib, json, os, sqlite3
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

SCHEMA = '''
CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, text TEXT NOT NULL, importance REAL NOT NULL, last_accessed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cuts(id TEXT PRIMARY KEY, start_seq INTEGER NOT NULL, created TEXT NOT NULL, expires TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('ACTIVE','EXPIRED')), policy TEXT NOT NULL, allow_ids TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, signature TEXT NOT NULL, prev_hash TEXT NOT NULL, digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS witnesses(cut_id TEXT NOT NULL, seq INTEGER NOT NULL, field TEXT NOT NULL, old_json TEXT NOT NULL, payload TEXT NOT NULL, signature TEXT NOT NULL, PRIMARY KEY(cut_id,seq,field), FOREIGN KEY(cut_id) REFERENCES cuts(id));
CREATE TABLE IF NOT EXISTS operations(op_id TEXT PRIMARY KEY, seq INTEGER NOT NULL, kind TEXT NOT NULL, input_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS config(k TEXT PRIMARY KEY, v TEXT NOT NULL);
'''

def enc(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

def sha(value): return hashlib.sha256(value).hexdigest()

def b64(b): return base64.b64encode(b).decode('ascii')

def parse(s): return dt.datetime.fromisoformat(s)

class DurableAudit:
    def __init__(self, directory, signing=False):
        self.root=Path(directory)
        self.dbpath=self.root/'audit.sqlite3'
        self.root.mkdir(parents=True, exist_ok=True)
        self.conn=sqlite3.connect(self.dbpath, timeout=15, isolation_level=None)
        self.conn.row_factory=sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=FULL')
        self.conn.execute('PRAGMA secure_delete=ON')
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.execute('PRAGMA busy_timeout=15000')
        self.conn.executescript(SCHEMA)
        self.sk=None
        if signing:
            raw=(self.root/'signer.key').read_bytes()
            self.sk=Ed25519PrivateKey.from_private_bytes(raw)
        self.pub=Ed25519PublicKey.from_public_bytes((self.root/'verifier.pub').read_bytes()) if (self.root/'verifier.pub').exists() else None

    @classmethod
    def initialize(cls, directory, texts, now):
        p=Path(directory);p.mkdir(parents=True,exist_ok=True)
        assert not (p/'audit.sqlite3').exists() and not (p/'signer.key').exists()
        key=Ed25519PrivateKey.generate()
        keyfile=p/'signer.key'
        with keyfile.open('xb') as f: os.fchmod(f.fileno(),0o600);f.write(key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption()));f.flush();os.fsync(f.fileno())
        (p/'verifier.pub').write_bytes(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw))
        o=cls(directory, signing=True)
        o.conn.execute('BEGIN IMMEDIATE')
        try:
            for i,t in enumerate(texts):
                o.conn.execute('INSERT INTO items VALUES(?,?,?,?)',(f'm{i}',t,0.10+0.025*i,(parse(now)-dt.timedelta(hours=1+i)).isoformat()))
            o.conn.execute('INSERT INTO config VALUES (?,?)',('catalog',enc({'ids':[f'm{i}' for i in range(len(texts))],'texts':texts,'clock':now,'k':2,'importance_domain':[0,1],'age_upper_hours':1000,'decay_rate':.01})))
            o._event({'kind':'INIT','items':len(texts),'time':now,'catalog':o.catalog()})
            o.conn.commit()
        except Exception:
            o.conn.rollback();raise
        return o

    def close(self):self.conn.close()
    def _start(self):self.conn.execute('BEGIN IMMEDIATE')
    def _event(self, payload):
        assert self.sk is not None, 'writer must load signing key'
        last=self.conn.execute('SELECT seq,digest FROM events ORDER BY seq DESC LIMIT 1').fetchone()
        seq=last['seq']+1 if last else 0
        prev=last['digest'] if last else '0'*64
        obj={'seq':seq, 'prev':prev,**payload}
        s=enc(obj); sig=b64(self.sk.sign(s.encode()))
        dg=sha((s+'|'+sig).encode())
        self.conn.execute('INSERT INTO events VALUES (?,?,?,?,?)',(seq,s,sig,prev,dg))
        return seq

    def _witnesses(self, seq, changes):
        # Called strictly inside the SAME transaction as authoritative item update.
        for cut in self.conn.execute("SELECT id,allow_ids FROM cuts WHERE status='ACTIVE'"):
            allowed=set(json.loads(cut['allow_ids']))
            for key,old in sorted(changes.items()):
                if key.split('.')[0] not in allowed: continue
                obj={'cut':cut['id'],'event_seq':seq,'field':key,'old':old}
                payload=enc(obj); sig=b64(self.sk.sign(payload.encode()))
                self.conn.execute('INSERT INTO witnesses VALUES(?,?,?,?,?,?)',(cut['id'],seq,key,enc(old),payload,sig))

    def catalog(self):return json.loads(self.conn.execute('SELECT v FROM config WHERE k="catalog"').fetchone()['v'])
    def state(self):
        return {r['id']:{'importance':r['importance'],'last_accessed_at':r['last_accessed_at'],'text':r['text']}
                for r in self.conn.execute('SELECT * FROM items ORDER BY id')}

    def cut(self, cut_id, now, ttl_hours, allow_ids):
        if ttl_hours<=0:raise ValueError('nonpositive TTL')
        if not set(allow_ids).issubset(self.state()):raise ValueError('allowlist outside catalog')
        created=parse(now); expires=(created+dt.timedelta(hours=ttl_hours)).isoformat()
        self._start()
        try:
            self._expire_in_tx(now)
            seq=self._event({'kind':'CUT','cut':cut_id,'time':now,'expires':expires,'allow_ids':sorted(set(allow_ids)),'candidate_ids':self.catalog()['ids']})
            self.conn.execute('INSERT INTO cuts VALUES(?,?,?,?,?,?,?)',(cut_id,seq,now,expires,'ACTIVE','allowlist',enc(sorted(set(allow_ids)))))
            self.conn.commit()
        except Exception:self.conn.rollback();raise
        return seq

    def _expire_in_tx(self,now):
        ids=[r['id'] for r in self.conn.execute("SELECT id FROM cuts WHERE status='ACTIVE' AND expires <= ? ORDER BY id",(now,))]
        for id in ids:self.conn.execute('DELETE FROM witnesses WHERE cut_id=?',(id,))
        for id in ids:self.conn.execute("UPDATE cuts SET status='EXPIRED' WHERE id=?",(id,))
        if ids:self._event({'kind':'EXPIRE','cut_ids':ids,'time':now})
        return ids

    def _commit_updates(self, kind, time, updates, extra=None, crash=None, in_tx=False, op_id=None, input_hash=None):
        assert updates
        if not in_tx:self._start()
        try:
            if op_id:
                prior=self.conn.execute('SELECT seq,input_hash FROM operations WHERE op_id=?',(op_id,)).fetchone()
                if prior:
                    if prior['input_hash']!=input_hash:raise ValueError('idempotency key reused with different request')
                    self.conn.commit()
                    return prior['seq']
            self._expire_in_tx(time)
            old={}; changed={}
            for id,fields in updates.items():
                row=self.conn.execute('SELECT * FROM items WHERE id=?',(id,)).fetchone()
                if row is None:raise KeyError(id)
                for field,new in fields.items():
                    if field not in ('importance','last_accessed_at'): raise ValueError('bad field')
                    if field=='importance' and not 0<=new<=1:raise ValueError('bad importance')
                    key=id+'.'+field
                    if row[field]!=new:
                        old[key]=row[field]
                        changed[key]=new
            if not changed:raise ValueError('no changes')
            obj={'kind':kind,'time':time,'updated_keys':sorted(changed)}
            if extra:obj.update(extra)
            if op_id:obj['request_id']=op_id
            seq=self._event(obj)
            if op_id:self.conn.execute('INSERT INTO operations VALUES(?,?,?,?)',(op_id,seq,kind,input_hash))
            if crash=='after_event':os._exit(73)
            self._witnesses(seq,old)
            for key,new in changed.items():
                id,field=key.split('.')
                self.conn.execute(f'UPDATE items SET {field}=? WHERE id=?',(new,id))
            if crash=='after_state':os._exit(74)
            self.conn.commit()
            if crash=='after_commit':os._exit(75)
            return seq
        except Exception:self.conn.rollback();raise

    def write(self,id,value,when,crash=None,request_id=None):
        h=sha(enc({'kind':'WRITE','id':id,'value':value,'when':when}).encode())
        return self._commit_updates('WRITE',when,{id:{'importance':value}},crash=crash,op_id=request_id,input_hash=h)

    def read(self, query, when, upstream_path, crash=None, request_id=None):
        # Hold the single SQLite writer lock throughout the native in-memory
        # call and receipt/state commit. An external vector DB/service would
        # NOT be atomic and is outside the claimed boundary.
        import sys
        from pathlib import Path
        from unittest.mock import patch
        import datetime as dt
        from langchain_core.documents import Document
        exp=Path(__file__).resolve().parent
        if str(exp.parent) not in sys.path:sys.path.insert(0,str(exp.parent))
        from experiments import locomo_readside_v29 as v
        mod=v.load_upstream(Path(upstream_path))
        h=sha(enc({'kind':'READ','query':query,'when':when}).encode())
        self._start()
        try:
            if request_id:
                prior=self.conn.execute('SELECT seq,input_hash FROM operations WHERE op_id=?',(request_id,)).fetchone()
                if prior:
                    if prior['input_hash']!=h:raise ValueError('idempotency key reused with different request')
                    record=json.loads(self.conn.execute('SELECT payload FROM events WHERE seq=?',(prior['seq'],)).fetchone()['payload'])
                    self.conn.commit()
                    return prior['seq'],record['selected']
            state=self.state()
            docs=[Document(page_content=s['text'],metadata={'item_id':id,'importance':s['importance'],'last_accessed_at':parse(s['last_accessed_at'])}) for id,s in state.items()]
            ret=v.create_retriever(mod,docs,len(docs),k=self.catalog()['k'])
            now=parse(when)
            class Clock(dt.datetime):
                @classmethod
                def now(cls,tz=None):return now
            with patch.object(mod.datetime,'datetime',Clock): selected=[d.metadata['item_id'] for d in ret.invoke(query)]
            after={d.metadata['item_id']:d.metadata['last_accessed_at'].isoformat() for d in ret.memory_stream}
            updates={id:{'last_accessed_at':t} for id,t in after.items() if state[id]['last_accessed_at']!=t}
            if len(updates)!=len(selected):raise AssertionError('expected one refresh per returned ID')
            seq=self._commit_updates('READ',when,updates,extra={'query':query,'selected':selected},crash=crash,in_tx=True,op_id=request_id,input_hash=h)
            return seq,selected
        except Exception:
            if self.conn.in_transaction:self.conn.rollback()
            raise

    def expire(self, now, crash=None):
        self._start()
        try:
            ids=self._expire_in_tx(now)
            if crash=='after_delete':os._exit(76)
            self.conn.commit()
            return ids
        except Exception:self.conn.rollback();raise

    def verify(self):
        if self.pub is None:raise ValueError('no public key')
        prior='0'*64
        init=None
        for i,r in enumerate(self.conn.execute('SELECT * FROM events ORDER BY seq')):
            if r['seq']!=i or r['prev_hash']!=prior:raise ValueError('event sequence/chain altered')
            o=json.loads(r['payload'])
            if o.get('seq')!=i or o.get('prev')!=prior:raise ValueError('event payload altered')
            if i==0:init=o
            if i==0 and (o.get('kind')!='INIT' or o.get('catalog')!=self.catalog()):raise ValueError('catalog altered')
            self.pub.verify(base64.b64decode(r['signature']),r['payload'].encode())
            if sha((r['payload']+'|'+r['signature']).encode())!=r['digest']:raise ValueError('event digest altered')
            prior=r['digest']
        count=0
        for r in self.conn.execute('SELECT * FROM witnesses'):
            self.pub.verify(base64.b64decode(r['signature']),r['payload'].encode())
            ob=json.loads(r['payload'])
            if (ob['cut'],ob['event_seq'],ob['field'],enc(ob['old']))!=(r['cut_id'],r['seq'],r['field'],r['old_json']):raise ValueError('witness mismatch')
            cut=self.conn.execute('SELECT allow_ids,status FROM cuts WHERE id=?',(r['cut_id'],)).fetchone()
            if cut is None or cut['status']!='ACTIVE' or r['field'].split('.')[0] not in json.loads(cut['allow_ids']):raise ValueError('unauthorized witness')
            count+=1
        return {'events':i+1 if 'i' in locals() else 0,'witnesses':count}

    def audit(self,cut_id,read_seq,now=None):
        # This function needs only public-key data, never self.sk. The
        # reference is scored using trusted deterministic fixture semantics.
        self.verify()
        cut=self.conn.execute('SELECT * FROM cuts WHERE id=?',(cut_id,)).fetchone()
        if cut is None:raise KeyError(cut_id)
        if cut['status']!='ACTIVE' or (now is not None and parse(now)>=parse(cut['expires'])):return 'UNVERIFIABLE'
        all_events=[json.loads(r['payload']) for r in self.conn.execute('SELECT payload FROM events WHERE seq>? ORDER BY seq',(cut['start_seq'],))]
        read=next((e for e in all_events if e['seq']==read_seq and e['kind']=='READ'),None)
        if read is None:raise ValueError('target read absent/invalid')
        items=self.state();c=self.catalog()
        first={}
        for e in all_events:
            for key in e.get('updated_keys',[]):first.setdefault(key,e['seq'])
        values={}
        for id,v in items.items():
            for field in ('importance','last_accessed_at'):
                key=id+'.'+field
                if key not in first:values[key]=v[field];continue
                w=self.conn.execute('SELECT old_json FROM witnesses WHERE cut_id=? AND seq=? AND field=?',(cut_id,first[key],key)).fetchone()
                values[key]=json.loads(w['old_json']) if w else None
        # Import lexical cosine scorer from the source only, no native model
        # required for independent verifier, but the embedding calculation is
        # the same deterministic fixture formula as the native read path.
        import re, math
        def emb(text):
            words=re.findall(r'[a-z0-9]+',text.lower());a=[0.]*384
            for word in words+[words[i]+'_'+words[i+1] for i in range(len(words)-1)]:
                j=int.from_bytes(hashlib.sha256(word.encode()).digest()[:4],'big')%384;a[j]+=1
            n=math.sqrt(sum(x*x for x in a))
            return [x/n for x in a] if n else a
        q=emb(read['query']);tm=parse(read['time']);ct=parse(cut['created'])
        lo={};hi={}
        for id,s in items.items():
            r=sum(a*b for a,b in zip(q,emb(s['text'])))
            p=values[id+'.importance']; last=values[id+'.last_accessed_at']
            pl,ph=(0.,1.) if p is None else (float(p),float(p))
            if last is None:rl,rh=.99**c['age_upper_hours'],1.0
            else:
                age=(tm-parse(last)).total_seconds()/3600
                rl=rh=.99**age
            lo[id]=r+pl+rl;hi[id]=r+ph+rh
        ids=c['ids'];selected=set(read['selected']);rest=set(ids)-selected
        if len(selected)!=c['k'] or not selected.issubset(ids):raise ValueError('bad selected IDs')
        if all(v is not None for v in values.values()):
            ranked=sorted(ids,key=lambda id:(-lo[id],ids.index(id)))[:c['k']]
            return 'ACCEPT' if set(ranked)==selected else 'REJECT'
        if min(lo[x] for x in selected)>max(hi[y] for y in rest)+1e-8:return 'ACCEPT'
        if any(lo[y]>hi[x]+1e-8 for x in selected for y in rest):return 'REJECT'
        return 'UNVERIFIABLE'

    def counts(self):
        return {'events':self.conn.execute('SELECT COUNT(*) FROM events').fetchone()[0],
                'witnesses':self.conn.execute('SELECT COUNT(*) FROM witnesses').fetchone()[0],
                'active_cuts':self.conn.execute("SELECT COUNT(*) FROM cuts WHERE status='ACTIVE'").fetchone()[0],
                'expired_cuts':self.conn.execute("SELECT COUNT(*) FROM cuts WHERE status='EXPIRED'").fetchone()[0]}