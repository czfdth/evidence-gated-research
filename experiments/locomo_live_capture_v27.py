#!/usr/bin/env python3
"""Actual langchain-core LoCoMo prewrite signing, overwrite, read and separated audit."""
import argparse,base64,hashlib,json,os,re,time,random,urllib.request
from collections import Counter
from pathlib import Path
import numpy as np
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey,Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
URL="https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
HASH="79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
K=24;E=12;BETA=.36;DIM=384;BUDGETS=(0,3,6,9,12)
def enc(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
def h(b):return hashlib.sha256(b).hexdigest()
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(enc(x)+b"\n")
def vec(s):
 w=re.findall(r"[a-z0-9]+",s.lower());a=np.zeros(DIM,dtype=float)
 for v in w+[w[i]+"_"+w[i+1] for i in range(len(w)-1)]:
  a[int.from_bytes(hashlib.sha256(v.encode()).digest()[:4],"big")%DIM]+=1
 norm=float(np.linalg.norm(a))
 return a/norm if norm else a
def sim(a,b):return float(vec(a)@vec(b))
class Ledger:
 def __init__(self,p):
  self.f=open(p,"wb");self.sk=Ed25519PrivateKey.generate();self.n=0
 def pub(self):return base64.b64encode(self.sk.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
 def put(self,kind,**kwargs):
  obj={"kind":kind,"seq":self.n,"ns":time.time_ns(),**kwargs};self.n+=1
  signed={"payload":obj,"sig":base64.b64encode(self.sk.sign(enc(obj))).decode()}
  self.f.write(enc(signed)+b"\n");self.f.flush();os.fsync(self.f.fileno())
 def close(self):self.f.close()
def turns(sample):
 c=sample["conversation"];out=[]
 for sess in sorted((v for v in c if re.fullmatch(r"session_\d+",v)),key=lambda x:int(x.split("_")[1])):
  for x in c[sess]:
   if isinstance(x.get("text"),str) and len(x["text"].strip())>=15:
    out.append({"text":x["text"],"dia_id":str(x.get("dia_id","")),"session":sess})
 return out
def generate(root,limit):
 from importlib.metadata import version
 import langchain_core
 from langchain_core.embeddings import Embeddings
 from langchain_core.vectorstores import InMemoryVectorStore
 from langchain_core.retrievers import BaseRetriever
 from langchain_core.documents import Document
 assert version("langchain-core")=="0.3.83"
 class Embed(Embeddings):
  def embed_documents(self,texts):return [vec(x).tolist() for x in texts]
  def embed_query(self,text):return vec(text).tolist()
 class Store(InMemoryVectorStore):
  def _select_relevance_score_fn(self):return lambda s:float(s)
 class Retriever(BaseRetriever):
  store:object
  n:int
  def _get_relevant_documents(self,query,*,run_manager):
   scored=self.store.similarity_search_with_relevance_scores(query,k=self.n)
   assert len(scored)==self.n
   scored.sort(key=lambda x:(-(float(x[1])+BETA*float(x[0].metadata["importance"])),x[0].metadata["slot"]))
   return [x[0] for x in scored[:1]]
 dfile=root/"locomo10.json"
 if not dfile.exists():
  for attempt in range(3):
   try:
    with urllib.request.urlopen(URL,timeout=90) as f:data=f.read()
    assert h(data)==HASH
    dfile.write_bytes(data);break
   except Exception:
    if attempt==2:raise
    time.sleep(3*(attempt+1))
 assert h(dfile.read_bytes())==HASH
 dataset=json.loads(dfile.read_text());assert len(dataset)==10
 protocol={"dataset_url":URL,"dataset_sha256":HASH,"license":"CC BY-NC 4.0","version":version("langchain-core"),"actual_calls":"InMemoryVectorStore.add_documents and BaseRetriever.invoke","selector":"hashed lexical cosine + 0.36*importance","changed_field":"importance","immutable_content":True,"data_scope":"natural LoCoMo QA, partly unsupported by 24-slot fixture","known_limitations":"ephemeral signer, synthetic metadata salience, known candidate IDs; no external attestation or database atomicity"}
 save(root/"protocol.json",protocol)
 generated=[];first_pub=None
 for cno,sample in enumerate(dataset[:limit]):
  t=turns(sample);assert len(t)>80
  source=sample["qa"];qas=[q for q in source if isinstance(q.get("question"),str) and len(q["question"])>11]
  assert len(qas)>=36
  train=[q["question"] for q in qas[:12]]
  tests=[{"qid":i,"question":q["question"],"category":q.get("category"),"evidence":q.get("evidence",[])} for i,q in enumerate(qas[12:44])]
  base=root/"runs"/str(sample["sample_id"]);base.mkdir(parents=True)
  docs=t[:K];ids=[f"s{i:02d}" for i in range(K)]
  old={ids[i]:round((len(x["text"])%17+1)/20,3) for i,x in enumerate(docs)}
  content={ids[i]:x["text"] for i,x in enumerate(docs)}
  store=Store(Embed())
  store.add_documents([Document(id=ids[i],page_content=x["text"],metadata={"slot":ids[i],"importance":old[ids[i]]}) for i,x in enumerate(docs)],ids=ids)
  retriever=Retriever(store=store,n=K)
  oracle={str(q["qid"]):retriever.invoke(q["question"])[0].metadata["slot"] for q in tests}
  sm=np.array([[sim(q,x["text"]) for x in docs] for q in train])
  freq=Counter();pol=Counter()
  for row in sm:
   for i in np.argsort(-row,kind="stable")[:4]:freq[int(i)]+=1
   pivot=float(np.sort(row)[-2])
   for i in range(E):pol[i]+=1/(.045+abs(float(row[i])-pivot))
  order=list(range(E));random.Random(2027+cno).shuffle(order)
  plans={}
  for name,ranking in {"random":order,"recency":list(range(E-1,-1,-1)),"frequency":sorted(range(E),key=lambda i:(-freq[i],i)),"polarity":sorted(range(E),key=lambda i:(-pol[i],i))}.items():
   for b in BUDGETS:plans[f"{name}_b{b}"]=[ids[i] for i in ranking[:b]]
  plans["full_undo"]=[ids[i] for i in range(E)]
  log=Ledger(base/"events.jsonl")
  public=log.pub();(base/"public-key.b64").write_text(public+"\n")
  log.put("CUT",catalog={"ids":ids,"text_sha256":{id:h(content[id].encode()) for id in ids},"domain":[0,1],"updated_ids":ids[:E],"plans":plans,"beta":BETA})
  log.put("FULL_SNAPSHOT",old_importance=old)
  updates=[]
  for i in range(E):
   id=ids[i];new=round((len(t[len(t)//2+i]["text"])%19+1)/21,3)
   for p,keep in plans.items():
    if id in keep:log.put("PREWRITE",policy=p,id=id,old=old[id])
   # Actual LangChain overwrite, AFTER signed preimage fsync.
   store.add_documents([Document(id=id,page_content=content[id],metadata={"slot":id,"importance":new})],ids=[id])
   updated={d.metadata["slot"]:d.metadata["importance"] for d,_ in store.similarity_search_with_relevance_scores(content[id],k=K)}
   assert updated[id]==new
   log.put("WRITE",id=id,new=new,source_dialog=t[len(t)//2+i]["dia_id"])
   updates.append(id)
  post={d.metadata["slot"]:{"text":d.page_content,"importance":float(d.metadata["importance"])} for d,_ in store.similarity_search_with_relevance_scores(train[0],k=K)}
  assert set(post)==set(ids)
  save(base/"post.json",post);save(base/"questions.json",tests)
  log.put("POST",post_hash=h(enc(post)),question_hash=h(enc(tests)))
  read={}
  for q in tests:
   got=retriever.invoke(q["question"])[0].metadata["slot"]
   read[str(q["qid"])]=got
   log.put("READ",qid=q["qid"],question_hash=h(q["question"].encode()),selected=got)
  log.close()
  save(base/"truth_oracle.json",oracle) # never opened by separate audit process
  save(base/"observed.json",read)
  save(base/"fixture_info.json",{"native_queries":len(tests),"writes":len(updates),"train_queries":len(train),"sample_id":sample["sample_id"],"sessions":len(set(x["session"] for x in t)),"origin_supported_test_queries":sum(bool(set(map(str,q["evidence"])) & {d["dia_id"] for d in docs}) for q in tests)})
  generated.append({"sample":sample["sample_id"],"natural_questions":len(tests),"writes":len(updates)})
 save(root/"generation.json",{"samples":generated,"real_framework":True})
 print("GENERATED",json.dumps(generated))
def audit(root):
 verdicts=[];rows=[]
 for base in sorted((root/"runs").iterdir()):
  key=base.joinpath("public-key.b64").read_text().strip()
  vk=Ed25519PublicKey.from_public_bytes(base64.b64decode(key))
  raw=[json.loads(x) for x in (base/"events.jsonl").read_text().splitlines()]
  ev=[]
  for i,x in enumerate(raw):
   vk.verify(base64.b64decode(x["sig"]),enc(x["payload"]))
   assert x["payload"]["seq"]==i
   ev.append(x["payload"])
  cat=ev[0]["catalog"];assert ev[0]["kind"]=="CUT" and ev[1]["kind"]=="FULL_SNAPSHOT"
  post=json.loads((base/"post.json").read_text());qs=json.loads((base/"questions.json").read_text())
  assert len(post)==len(cat["ids"]) and h(enc(post))==next(e["post_hash"] for e in ev if e["kind"]=="POST")
  assert h(enc(qs))==next(e["question_hash"] for e in ev if e["kind"]=="POST")
  assert {i:h(post[i]["text"].encode()) for i in post}==cat["text_sha256"]
  writes={e["id"]:e for e in ev if e["kind"]=="WRITE"}
  assert set(writes)==set(cat["updated_ids"])
  for id,e in writes.items():assert post[id]["importance"]==e["new"]
  caps={}
  for e in ev:
   if e["kind"]=="PREWRITE":
    tup=(e["policy"],e["id"])
    assert tup not in caps and e["seq"]<writes[e["id"]]["seq"]
    caps[tup]=e["old"]
  signed_reads={str(e["qid"]):e for e in ev if e["kind"]=="READ"}
  assert len(signed_reads)==len(qs)
  for q in qs:assert signed_reads[str(q["qid"])]["question_hash"]==h(q["question"].encode())
  # Byte totals count signed canonical payloads and real persisted file bytes.
  shared=sum(len(enc(x))+1 for x in raw if x["payload"]["kind"] in ("CUT","WRITE","POST","READ"))
  shared+=(base/"post.json").stat().st_size+(base/"questions.json").stat().st_size
  for name,captured in {**cat["plans"],"full_snapshot":cat["ids"]}.items():
   old=ev[1]["old_importance"] if name=="full_snapshot" else {id:caps[(name,id)] for id in captured}
   if name!="full_snapshot":assert {(p,id) for p,id in caps if p==name}=={(name,id) for id in captured}
   b=len(enc(raw[1]))+1 if name=="full_snapshot" else sum(len(enc(x))+1 for x in raw if x["payload"]["kind"]=="PREWRITE" and x["payload"]["policy"]==name)
   counter=Counter();vv=[]
   for q in qs:
    claim=signed_reads[str(q["qid"])]["selected"];sc=[]
    for id in cat["ids"]:
     r=sim(q["question"],post[id]["text"])
     if id in old:low=high=r+BETA*old[id]
     elif id not in writes:low=high=r+BETA*post[id]["importance"]
     else:low,high=r,r+BETA
     sc.append((id,low,high))
    target=next(x for x in sc if x[0]==claim);out=[x for x in sc if x[0]!=claim]
    verdict=("ACCEPT" if target[1]>max(x[2] for x in out)+1e-9 else
             "REJECT" if max(x[1] for x in out)>target[2]+1e-9 else "UNVERIFIABLE")
    counter[verdict]+=1;vv.append({"qid":q["qid"],"selected":claim,"verdict":verdict})
   rows.append({"conversation":base.name,"policy":name,"budget_values":len(captured),
                "n":len(qs),"accept":counter["ACCEPT"],"reject":counter["REJECT"],
                "unverifiable":counter["UNVERIFIABLE"],"definite":counter["ACCEPT"]+counter["REJECT"],
                "signed_retention_bytes":b,"shared_input_bytes":shared,"total_audit_bytes":shared+b})
   verdicts.append({"conversation":base.name,"policy":name,"verdicts":vv})
 save(root/"audit-results.json",rows);save(root/"audit-verdicts.json",verdicts)
 print("AUDITED",len(rows),"strategy-conversation rows, natural queries",sum(r["n"] for r in rows))
def evaluate(root):
 rows=json.loads((root/"audit-results.json").read_text())
 verdicts=json.loads((root/"audit-verdicts.json").read_text())
 incorrect=[];checked=0
 for v in verdicts:
  truth=json.loads((root/"runs"/v["conversation"]/"truth_oracle.json").read_text())
  for q in v["verdicts"]:
   checked+=1
   truth_accept=q["selected"]==truth[str(q["qid"])]
   if q["verdict"]!="UNVERIFIABLE" and (q["verdict"]=="ACCEPT")!=truth_accept:incorrect.append([v["conversation"],v["policy"],q["qid"]])
 assert not incorrect,incorrect[:10]
 agg={}
 for r in rows:
  z=agg.setdefault(r["policy"],{"claims":0,"definite":0,"accept":0,"reject":0,"retained_bytes":0,"total_bytes":0,"n_runs":0,"budget":r["budget_values"]})
  z["claims"]+=r["n"];z["definite"]+=r["definite"];z["accept"]+=r["accept"];z["reject"]+=r["reject"]
  z["retained_bytes"]+=r["signed_retention_bytes"];z["total_bytes"]+=r["total_audit_bytes"];z["n_runs"]+=1
 for z in agg.values():
  z["coverage"]=z["definite"]/z["claims"];z["retention_bytes_mean"]=z["retained_bytes"]/z["n_runs"];z["all_bytes_mean"]=z["total_bytes"]/z["n_runs"]
 result={"checks":checked,"false_definite":len(incorrect),"comparisons":agg,"limitations":"Natural LoCoMo questions; synthetic importance updates derived from later dialogue, lexical hashed embeddings, local trusted signer, no production external cut attestation or autonomous Agent"}
 save(root/"summary.json",result)
 print("EVALUATED",json.dumps(result,sort_keys=True))
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--out",type=Path,default=Path("locomo_live_evidence"));p.add_argument("--mode",choices=["generate","audit","evaluate"],required=True);p.add_argument("--limit",type=int,default=10)
 a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 {"generate":generate,"audit":audit,"evaluate":evaluate}[a.mode](a.out,a.limit) if a.mode=="generate" else {"audit":audit,"evaluate":evaluate}[a.mode](a.out)
