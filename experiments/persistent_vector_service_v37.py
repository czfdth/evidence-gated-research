#!/usr/bin/env python3
"""Test-only durable vector index as a separate HTTP service/process and SQLite DB.

Index version and exact state hash are mandatory. The service does not share the
coordinator transaction, offers no consensus, TLS, authorization or external
writes, and has deliberately no external mutation API beyond versioned apply.
"""
import argparse, hashlib, json, math, os, re, sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIM=384

def canon(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x):return hashlib.sha256(canon(x).encode()).hexdigest()
def vec(s):
    words=re.findall(r'[a-z0-9]+',s.lower());a=[0.0]*DIM
    for w in words+[words[i]+'_'+words[i+1] for i in range(len(words)-1)]:
        idx=int.from_bytes(hashlib.sha256(w.encode()).digest()[:4],'big')%DIM;a[idx]+=1.0
    length=math.sqrt(sum(v*v for v in a));return [v/length for v in a] if length else a

class Index:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=20,check_same_thread=False,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS docs(id TEXT PRIMARY KEY, text TEXT NOT NULL, importance REAL NOT NULL, last_accessed_at TEXT NOT NULL, embedding TEXT NOT NULL, buffer_idx INTEGER NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS revision(version INTEGER PRIMARY KEY, payload_hash TEXT NOT NULL, operation_id TEXT NOT NULL UNIQUE)')
    def revision(self):
        x=self.db.execute('SELECT * FROM revision ORDER BY version DESC LIMIT 1').fetchone()
        return {'version':x['version'],'payload_hash':x['payload_hash']} if x else {'version':-1,'payload_hash':None}
    def snapshot(self):
        return {r['id']:{'text':r['text'],'importance':r['importance'],'last_accessed_at':r['last_accessed_at'],'buffer_idx':r['buffer_idx']} for r in self.db.execute('SELECT * FROM docs ORDER BY buffer_idx')}
    def apply(self,obj):
        version=obj['version'];state=obj['state'];h=obj['payload_hash'];oid=obj['operation_id']
        if digest(state)!=h or version<0:raise ValueError('bad state digest or version')
        if len(set(state))!=len(state):raise ValueError('duplicate id')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            current=self.revision()
            if version==current['version']:
                existing=self.db.execute('SELECT operation_id,payload_hash FROM revision WHERE version=?',(version,)).fetchone()
                if existing['operation_id']!=oid or existing['payload_hash']!=h:raise ValueError('fork at applied revision')
            elif version==current['version']+1:
                self.db.execute('DELETE FROM docs')
                for pos,(id,doc) in enumerate(sorted(state.items())):
                    if set(doc)!={'text','importance','last_accessed_at'}:raise ValueError('unexpected index fields')
                    if not 0<=float(doc['importance'])<=1:raise ValueError('bad importance')
                    self.db.execute('INSERT INTO docs VALUES(?,?,?,?,?,?)',(id,doc['text'],float(doc['importance']),doc['last_accessed_at'],canon(vec(doc['text'])),pos))
                self.db.execute('INSERT INTO revision VALUES(?,?,?)',(version,h,oid))
            else:raise ValueError('gap or stale revision')
            if digest({i:{k:v for k,v in d.items() if k!='buffer_idx'} for i,d in self.snapshot().items()})!=h:
                raise ValueError('index metadata divergent')
            self.db.commit()
        except Exception:
            self.db.rollback();raise
        if obj.get('inject')=='service_post_commit':os._exit(91)
        return self.revision()
    def search(self,query,k):
        q=vec(query);ranked=[]
        for r in self.db.execute('SELECT id,text,importance,last_accessed_at,embedding,buffer_idx FROM docs'):
            score=sum(a*b for a,b in zip(q,json.loads(r['embedding'])))
            ranked.append({'id':r['id'],'text':r['text'],'importance':r['importance'],'last_accessed_at':r['last_accessed_at'],'buffer_idx':r['buffer_idx'],'score':score})
        return sorted(ranked,key=lambda a:(-a['score'],a['buffer_idx']))[:k]

class Handler(BaseHTTPRequestHandler):
    index=None
    def log_message(self,fmt,*args):pass
    def respond(self,obj,code=200):
        data=canon(obj).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.path=='/health':self.respond({'status':'ok',**self.index.revision()})
        elif self.path=='/state':self.respond({'revision':self.index.revision(),'state':self.index.snapshot()})
        else:self.respond({'error':'not_found'},404)
    def do_POST(self):
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n>1_000_000:raise ValueError('payload too large')
            body=json.loads(self.rfile.read(n))
            if self.path=='/apply':out=self.index.apply(body)
            elif self.path=='/search':out={'revision':self.index.revision(),'hits':self.index.search(body['query'],int(body['k']))}
            else:raise ValueError('unknown route')
            self.respond(out)
        except (ValueError,KeyError,TypeError) as e:self.respond({'error':str(e)},409)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--db',required=True);a.add_argument('--port',required=True,type=int);v=a.parse_args()
    Handler.index=Index(v.db)
    ThreadingHTTPServer(('127.0.0.1',v.port),Handler).serve_forever()