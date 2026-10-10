#!/usr/bin/env python3
"""COLING v29: actual pinned LangChain read-side refresh, auditable paired alias and LoCoMo evidence-aligned queries.
Native execution requires langchain-core==0.3.83. Natural question QA labels are used only
to define an evaluation slice, not to guide semantic ranking or train the ranker.
This is NOT a production atomic audit service or LoCoMo QA accuracy benchmark.
"""
import base64,datetime as dt,hashlib,importlib.util,json,os,re,secrets,time,urllib.request
from pathlib import Path
from unittest.mock import patch
from collections import Counter
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey,Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from importlib.metadata import version
import numpy as np
URL="https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
DATA_SHA="79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
UPSTREAM_SHA="2a55ff628c1d44ebf1faa01008579ac26ed0ae5996daec6dcde3ae4cb9233daa"
DIM=384
def enc(x): return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def dig(x):return hashlib.sha256(x).hexdigest()
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(enc(x)+b"\n")
def iso(t): return t.isoformat(timespec="microseconds")
def vec(text):
 words=re.findall(r"[a-z0-9]+",text.lower()); a=np.zeros(DIM)
 for w in words+[words[i]+"_"+words[i+1] for i in range(len(words)-1)]:
  a[int.from_bytes(hashlib.sha256(w.encode()).digest()[:4],"big")%DIM]+=1
 n=np.linalg.norm(a);return (a/n if n else a).tolist()
class Emb(Embeddings):
 def embed_documents(self,texts):return [vec(s) for s in texts]
 def embed_query(self,text):return vec(text)
class Store(InMemoryVectorStore):
 def _select_relevance_score_fn(self):return lambda s:float(s)
class Signed:
 def __init__(self,path):
  self.path=path;path.parent.mkdir(parents=True,exist_ok=True)
  self.sk=Ed25519PrivateKey.generate()
  self.pk=base64.b64encode(self.sk.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
  self.sequence=0
 def sign(self,kind,**kw):
  payload={"kind":kind,"seq":self.sequence,**kw};self.sequence+=1
  record={"payload":payload,"signature":base64.b64encode(self.sk.sign(enc(payload))).decode()}
  with self.path.open("ab") as f:f.write(enc(record)+b"\n");f.flush();os.fsync(f.fileno())
  return record
def verify(path,pk):
 vk=Ed25519PublicKey.from_public_bytes(base64.b64decode(pk))
 out=[]
 for i,line in enumerate(path.read_bytes().splitlines()):
  d=json.loads(line);vk.verify(base64.b64decode(d["signature"]),enc(d["payload"]))
  assert d["payload"]["seq"]==i
  out.append(d["payload"])
 return out
def load_upstream(path):
 assert dig(path.read_bytes())==UPSTREAM_SHA
 spec=importlib.util.spec_from_file_location("pinned_tw_v29",path)
 mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 mod.TimeWeightedVectorStoreRetriever.model_rebuild(_types_namespace=vars(mod))
 return mod
def create_retriever(mod,documents,search_k,k=2):
 st=Store(Emb())
 ret=mod.TimeWeightedVectorStoreRetriever(vectorstore=st,decay_rate=.01,k=k,
    other_score_keys=["importance"],default_salience=None,search_kwargs={"k":search_k})
 ret.add_documents(documents)
 return ret
def turns(sample):
 c=sample["conversation"];out=[]
 for sess in sorted((s for s in c if re.fullmatch("session_[0-9]+",s)),key=lambda z:int(z.split("_")[1])):
  for z in c[sess]:
   if isinstance(z.get("text"),str) and len(z["text"].strip())>=15:
    out.append({"dia_id":str(z.get("dia_id","")),"text":z["text"],"session":sess})
 return out
def get_dataset(root):
 d=root/"locomo10.json"
 if not d.exists():
  data=urllib.request.urlopen(URL,timeout=100).read()
  assert dig(data)==DATA_SHA
  d.write_bytes(data)
 assert dig(d.read_bytes())==DATA_SHA
 return json.loads(d.read_text())
def paired_alias(mod,root):
 """Paired deterministic histories: full post-read state identical, cut reference differs.
 Synthetic relevance controls are fixed; upstream retriever score/update implementation is unchanged.
 """
 root.mkdir(parents=True,exist_ok=True)
 T=dt.datetime(2026,10,10,12,0,0)
 class Clock(dt.datetime):
  @classmethod
  def now(cls,tz=None):return T
 worlds=[]
 for label,age in [("old_C_6h",6),("old_C_1h",1)]:
  docs=[Document(page_content="Evidence A",metadata={"item_id":"A","importance":1.0,"last_accessed_at":T}),
        Document(page_content="Evidence B",metadata={"item_id":"B","importance":0.0,"last_accessed_at":T}),
        Document(page_content="Evidence C",metadata={"item_id":"C","importance":0.0,"last_accessed_at":T-dt.timedelta(hours=age)})]
  ret=create_retriever(mod,docs,3,k=2)
  # Native upstream consumes fixed, declared query relevance of A, B and C.
  scores={"A":.95,"B":.8,"C":.85}
  ret.vectorstore.similarity_search_with_relevance_scores=lambda query,**kwargs: [(d,scores[d.metadata["item_id"]]) for d in ret.memory_stream]
  q="Which earlier memory should be selected?";cut_id="paired-"+label
  origin={d.metadata["item_id"]:iso(d.metadata["last_accessed_at"]) for d in ret.memory_stream}
  signer=Signed(root/(label+"-signed-ledger.jsonl"))
  # Signed CUT preimages are retained for truth; restricted observer omits them.
  signer.sign("CUT",cut_id=cut_id,query_hash=dig(q.encode()),old_access=origin)
  with patch.object(mod.datetime,"datetime",Clock):
   ref=sorted(ret.memory_stream,key=lambda d:ret._get_combined_score(d,scores[d.metadata["item_id"]],T),reverse=True)[:2]
   reference=[x.metadata["item_id"] for x in ref]
   c=next(d for d in ret.memory_stream if d.metadata["item_id"]=="C")
   before_c=c.metadata["importance"];c.metadata["importance"]=.15
   signer.sign("PREWRITE",cut_id=cut_id,field="C.importance",old_value=before_c,write_event_id="WC")
   selected=[d.metadata["item_id"] for d in ret.invoke(q)]
   after_read={d.metadata["item_id"]:iso(d.metadata["last_accessed_at"]) for d in ret.memory_stream}
   c.metadata["importance"]=before_c # write-only rollback, not access-time rollback
   after_rollback={d.metadata["item_id"]:{"importance":d.metadata["importance"],"last_accessed_at":iso(d.metadata["last_accessed_at"])} for d in ret.memory_stream}
  signer.sign("READ_COMMIT",cut_id=cut_id,selected=selected,after_access=after_read)
  verify(signer.path,signer.pk)
  worlds.append({"world":label,"cut_reference":reference,"valid_read_result":selected,
       "cut_equivalent":set(selected)==set(reference),
       "rolled_back_state":after_rollback,"prewrite_access":origin,"verified_signed_events":3,
       "public_key":signer.pk})
 assert worlds[0]["valid_read_result"]==worlds[1]["valid_read_result"],worlds
 assert worlds[0]["rolled_back_state"]==worlds[1]["rolled_back_state"],worlds
 assert worlds[0]["cut_equivalent"]!=worlds[1]["cut_equivalent"],worlds
 save(root/"paired-alias-results.json",{"worlds":worlds,"observation_identical_after_rollback":True,
  "cut_relative_labels_opposed":True,
  "interpretation":"Only restricted observation (Y, rolled-back state) aliases. Authenticated preimages distinguish the worlds."})
 return worlds
def natural_reads(mod,root,limit):
 ds=get_dataset(root);rows=[];detail=[];total_full=0
 for ix,sample in enumerate(ds[:limit]):
  dialog=turns(sample);ids={x["dia_id"] for x in dialog if x["dia_id"]}
  qas=[q for q in sample["qa"] if isinstance(q.get("question"),str) and len(q["question"])>11]
  natural=[q for q in qas if bool(set(map(str,q.get("evidence",[]))) & ids)]
  if len(natural)>32:natural=natural[:32]
  assert natural,("no evidence aligned questions",sample["sample_id"])
  t0=dt.datetime.now()-dt.timedelta(hours=7)
  docs=[Document(page_content=x["text"],metadata={"dia_id":x["dia_id"],"item_id":f"s{i:04d}",
         "importance":0.0,"last_accessed_at":t0,"created_at":t0}) for i,x in enumerate(dialog)]
  ret=create_retriever(mod,docs,len(docs),k=2)
  signer=Signed(root/"natural-ledgers"/(str(sample["sample_id"])+".jsonl"))
  cut_id=dig(enc({"sample":sample["sample_id"],"slots":[x["dia_id"] for x in dialog],"nonce":secrets.token_hex(16)}))
  signer.sign("CATALOG",cut_id=cut_id,n_items=len(docs),text_sha256=dig(enc([x["text"] for x in dialog])))
  original=[];updates=0;overlap=0
  for qid,q in enumerate(natural):
   question=q["question"];evidence=set(map(str,q.get("evidence",[])))
   pre={str(i):iso(d.metadata["last_accessed_at"]) for i,d in enumerate(ret.memory_stream)}
   signer.sign("PRE_READ",cut_id=cut_id,read_id=qid,query_sha256=dig(question.encode()),
               pre_state_sha256=dig(enc(pre)))
   # True installed LangChain BaseRetriever.invoke -> original pinned time-weighted update.
   selected=ret.invoke(question)
   selected_ids=[x.metadata["item_id"] for x in selected]
   changed=[d.metadata["item_id"] for d in ret.memory_stream if iso(d.metadata["last_accessed_at"])!=pre[str(d.metadata["buffer_idx"])]]
   signer.sign("READ_COMMIT",cut_id=cut_id,read_id=qid,selected=selected_ids,
               changed=changed,post_state_sha256=dig(enc({str(i):iso(d.metadata["last_accessed_at"]) for i,d in enumerate(ret.memory_stream)})))
   assert set(changed)==set(selected_ids)
   updates+=len(changed);overlap+=int(bool(evidence.intersection(d.metadata["dia_id"] for d in selected)))
   original.append({"question":question,"gold_evidence":sorted(evidence),"selected_dia_ids":[d.metadata["dia_id"] for d in selected],
     "selected_overlap_gold":bool(evidence.intersection(d.metadata["dia_id"] for d in selected))})
  checked=verify(signer.path,signer.pk)
  assert len(checked)==1+2*len(natural)
  row={"conversation":sample["sample_id"],"stored_dialogue_turns":len(dialog),
      "dataset_qa_count":len(qas),"supported_questions":len(natural),"actual_read_calls":len(natural),
      "read_side_last_accessed_at_updates":updates,"selected_evidence_overlap":overlap,
      "signed_events":len(checked),"ledger_bytes":signer.path.stat().st_size,"public_key":signer.pk}
  rows.append(row);detail.append({"conversation":sample["sample_id"],"questions":original});total_full+=len(dialog)
 save(root/"natural-aligned-summary.json",{"dataset_sha256":DATA_SHA,"framework_version":version("langchain-core"),
 "upstream_source_sha256":UPSTREAM_SHA,"source":"LoCoMo natural QA with gold evidence in FULL stored conversation; QA labels used only for inclusion/evaluation",
 "full_conversation_turns":total_full,"rows":rows,"total_supported_queries":sum(r["supported_questions"] for r in rows),
 "native_read_calls":sum(r["actual_read_calls"] for r in rows),"actual_access_time_mutations":sum(r["read_side_last_accessed_at_updates"] for r in rows),
 "query_selected_evidence_overlap":sum(r["selected_evidence_overlap"] for r in rows),
 "no_semantic_QA_accuracy_claim":True})
 save(root/"natural-aligned-queries.json",detail)
 return rows
if __name__=="__main__":
 import argparse
 p=argparse.ArgumentParser();p.add_argument("--out",type=Path,default=Path("v29-results"));p.add_argument("--upstream",type=Path,default=Path("src/time_weighted_retriever_v29.py"));p.add_argument("--limit",type=int,default=10);a=p.parse_args()
 assert version("langchain-core")=="0.3.83";a.out.mkdir(parents=True,exist_ok=True)
 mod=load_upstream(a.upstream)
 paired=paired_alias(mod,a.out/"paired-alias")
 rows=natural_reads(mod,a.out,a.limit)
 # Do not redistribute full LoCoMo dataset, only manifest and output of selected public questions.
 f=a.out/"locomo10.json"
 if f.exists():f.unlink()
 print("V29_COMPLETE",json.dumps({"paired_alias":len(paired),
 "supported_natural_queries":sum(x["supported_questions"] for x in rows),
 "full_dialogue_turns":sum(x["stored_dialogue_turns"] for x in rows),
 "actual_timestamp_refreshes":sum(x["read_side_last_accessed_at_updates"] for x in rows)},sort_keys=True))
