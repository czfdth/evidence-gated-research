#!/usr/bin/env python3
"""v30 strict observation isolation: native pinned LangChain read-side alias, with two
byte-identical signed PUBLIC views and separately signed PRIVATE cut preimages.

A local experimental signer and fixed trusted relevance/catalog are ASSUMED, not attested.
No production atomicity, external non-equivocation, or natural QA accuracy claim.
"""
import argparse,base64,datetime as dt,hashlib,json,os,shutil
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey,Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from langchain_core.documents import Document
from locomo_readside_v29 import create_retriever,load_upstream,enc,dig,iso,verify,save,UPSTREAM_SHA
Q="Which earlier memory should be selected?"
T=dt.datetime(2026,10,10,12,0,0)
SCORES={"A":.95,"B":.8,"C":.85}
CUT_ID="paired-alias-catalog-cut-v30"
class Clock(dt.datetime):
 @classmethod
 def now(cls,tz=None):return T
class Signer:
 def __init__(self,path,sk):
  self.path=path;self.path.parent.mkdir(parents=True,exist_ok=True);self.sk=sk;self.seq=0
 def sign(self,kind,**fields):
  payload={"kind":kind,"seq":self.seq,**fields};self.seq+=1
  sig=base64.b64encode(self.sk.sign(enc(payload))).decode()
  with self.path.open("ab") as f:f.write(enc({"payload":payload,"signature":sig})+b"\n");f.flush();os.fsync(f.fileno())
def verify_plain(path,pub):
 return verify(path,pub)
def generate(out,upstream):
 mod=load_upstream(upstream)
 views=out/"auditor_views";secret=out/"oracle_only"
 views.mkdir(parents=True,exist_ok=True);secret.mkdir(parents=True,exist_ok=True)
 sk=Ed25519PrivateKey.generate()
 pub=base64.b64encode(sk.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
 catalog={"cut_id":CUT_ID,"candidate_ids":["A","B","C"],"query":Q,"k":2,
   "score_relevance":SCORES,"importance_cut":{"A":1.0,"B":0.0,"C":0.0},
   "score_clock":iso(T),"decay_rate":.01,
   "temporal_domain":{"C.last_accessed_at":[iso(T-dt.timedelta(hours=6)),iso(T-dt.timedelta(hours=1))]},
   "fixed_old_access":{"A":iso(T),"B":iso(T)},
   "write_event_id":"WC","signed_by_public_key":pub}
 catalog_hash=dig(enc(catalog))
 hidden={}
 for name,age in [("world0",6),("world1",1)]:
  docs=[Document(page_content="Evidence A",metadata={"item_id":"A","importance":1.0,"last_accessed_at":T}),
   Document(page_content="Evidence B",metadata={"item_id":"B","importance":0.0,"last_accessed_at":T}),
   Document(page_content="Evidence C",metadata={"item_id":"C","importance":0.0,"last_accessed_at":T-dt.timedelta(hours=age)})]
  ret=create_retriever(mod,docs,3,k=2)
  ret.vectorstore.similarity_search_with_relevance_scores=lambda query,**kwargs: [(d,SCORES[d.metadata["item_id"]]) for d in ret.memory_stream]
  root=views/name;root.mkdir()
  # Public receipts authenticate schema and event, NOT complete cut values or their hashes.
  public=Signer(root/"public-ledger.jsonl",sk)
  public.sign("CATALOG",cut_id=CUT_ID,catalog_digest=catalog_hash,query_digest=dig(Q.encode()))
  old_C=iso(next(d for d in ret.memory_stream if d.metadata["item_id"]=="C").metadata["last_accessed_at"])
  # Optional capture preimage, saved in separately controlled per-world view. Before any write/read.
  capture=Signer(root/"capture-C-last-access.jsonl",sk)
  capture.sign("PREIMAGE",cut_id=CUT_ID,catalog_digest=catalog_hash,
   write_event_id="WC",field="C.last_accessed_at",old_value=old_C)
  # Oracle history remains outside the auditor view, and MUST NOT be supplied to B=0 auditor.
  priv=Signer(secret/(name+"-truth.jsonl"),sk)
  priv.sign("PRIVATE_CUT_TRUTH",cut_id=CUT_ID,pre_read_C_last_access=old_C)
  with patch.object(mod.datetime,"datetime",Clock):
   ref=sorted(ret.memory_stream,key=lambda d:ret._get_combined_score(d,SCORES[d.metadata["item_id"]],T),reverse=True)[:2]
   cut_ref=[x.metadata["item_id"] for x in ref]
   c=next(d for d in ret.memory_stream if d.metadata["item_id"]=="C")
   old_importance=c.metadata["importance"]
   public.sign("PREWRITE",cut_id=CUT_ID,catalog_digest=catalog_hash,write_event_id="WC",
              field="C.importance",old_value=old_importance)
   c.metadata["importance"]=.15
   result=[d.metadata["item_id"] for d in ret.invoke(Q)]
   c.metadata["importance"]=old_importance
   post={d.metadata["item_id"]:{"importance":d.metadata["importance"],
    "last_accessed_at":iso(d.metadata["last_accessed_at"])} for d in ret.memory_stream}
  public.sign("READ_COMMIT",cut_id=CUT_ID,catalog_digest=catalog_hash,write_event_id="WC",
              read_id="R1",query_digest=dig(Q.encode()),selected=result,post_state=post)
  save(root/"catalog.json",catalog)
  save(root/"observed-state.json",{"cut_id":CUT_ID,"query":Q,"selected":result,"post_rollback":post})
  assert len(verify_plain(root/"public-ledger.jsonl",pub))==3
  assert len(verify_plain(root/"capture-C-last-access.jsonl",pub))==1
  assert len(verify_plain(secret/(name+"-truth.jsonl"),pub))==1
  hidden[name]={"cut_reference":cut_ref,"actual_read":result,"cut_equivalent":set(cut_ref)==set(result),
   "pre_read_C_last_access":old_C}
 # The FULL public signed receipts (including bytewise deterministic Ed25519 signatures),
 # public catalog and post-read evidence, not just a projected tuple, must coincide.
 for fn in ("public-ledger.jsonl","catalog.json","observed-state.json"):
  assert (views/"world0"/fn).read_bytes()==(views/"world1"/fn).read_bytes(),fn
 assert hidden["world0"]["cut_equivalent"]!=hidden["world1"]["cut_equivalent"]
 assert hidden["world0"]["actual_read"]==hidden["world1"]["actual_read"]
 save(secret/"oracle-labels.json",hidden)
 save(out/"public-proof-summary.json",{"public_signed_ledger_byte_equal":True,
  "catalog_byte_equal":True,"post_rollback_byte_equal":True,
  "private_capture_distinguishes":True,
  "signed_private_cut_truth_not_in_public_view":True,
  "native_langchain_version":"0.3.83","upstream_sha256":UPSTREAM_SHA,
  "scope":"Fixed synthetic 3-item native LangChain scoring configuration; independent signer trust assumed"})
 return hidden
def audit(out):
 """Auditor reads one view root only. No oracle files are opened."""
 status={}
 for name in ("world0","world1"):
  root=out/"auditor_views"/name
  catalog=json.loads((root/"catalog.json").read_text())
  obs=json.loads((root/"observed-state.json").read_text())
  cut_id=catalog["cut_id"];pub=catalog["signed_by_public_key"];digest=dig(enc(catalog))
  ledger=verify_plain(root/"public-ledger.jsonl",pub)
  assert len(ledger)==3 and [x["kind"] for x in ledger]==["CATALOG","PREWRITE","READ_COMMIT"]
  assert all(x["cut_id"]==cut_id and x["catalog_digest"]==digest for x in ledger)
  assert ledger[-1]["post_state"]==obs["post_rollback"]
  assert ledger[-1]["selected"]==obs["selected"]
  assert ledger[1]["write_event_id"]==catalog["write_event_id"]
  # Two allowed undisclosed historical timestamp values lead to opposed verdicts.
  def cut_reference(old_C):
   delta=(T-dt.datetime.fromisoformat(old_C)).total_seconds()/3600
   score={"A":SCORES["A"]+1+1,"B":SCORES["B"]+1,"C":SCORES["C"]+.99**delta}
   return sorted(score,key=lambda k:-score[k])[:2]
  vals=catalog["temporal_domain"]["C.last_accessed_at"]
  possible=[set(cut_reference(v))==set(obs["selected"]) for v in vals]
  no_capture=("ACCEPT" if all(possible) else "CUT-MISMATCH" if not any(possible) else "UNVERIFIABLE")
  assert no_capture=="UNVERIFIABLE"
  capture=verify_plain(root/"capture-C-last-access.jsonl",pub)
  assert len(capture)==1
  item=capture[0]
  assert item["kind"]=="PREIMAGE" and item["cut_id"]==cut_id
  assert item["catalog_digest"]==digest and item["write_event_id"]==catalog["write_event_id"]
  assert item["field"]=="C.last_accessed_at" and item["old_value"] in vals
  with_capture="ACCEPT" if set(cut_reference(item["old_value"]))==set(obs["selected"]) else "CUT-MISMATCH"
  status[name]={"no_capture":no_capture,"one_signed_capture":with_capture}
 save(out/"audit-only-results.json",status)
 return status
def evaluate(out):
 res=json.loads((out/"audit-only-results.json").read_text())
 truth=json.loads((out/"oracle_only/oracle-labels.json").read_text())
 for name,v in res.items():
  assert v["no_capture"]=="UNVERIFIABLE"
  assert (v["one_signed_capture"]=="ACCEPT")==truth[name]["cut_equivalent"]
 assert res["world0"]["one_signed_capture"]!=res["world1"]["one_signed_capture"]
 save(out/"evaluation-only-summary.json",{"views":2,"byte_identical_public_views":True,
  "no_capture_abstentions":2,"one_signed_preimage_correct_verdicts":2,
  "incorrect_definite_verdicts":0,
  "important_scope":"oracle used only in grading, not audit; native world generated with installed official LangChain"})
 return res
if __name__=="__main__":
 ap=argparse.ArgumentParser();ap.add_argument("--out",type=Path,default=Path("v30-native-evidence"))
 ap.add_argument("--upstream",type=Path,default=Path("src/time_weighted_retriever_v29.py"))
 ap.add_argument("--mode",choices=["generate","audit","evaluate"],required=True)
 args=ap.parse_args()
 if args.mode=="generate":print("V30_GENERATE",generate(args.out,args.upstream))
 if args.mode=="audit":print("V30_AUDIT",audit(args.out))
 if args.mode=="evaluate":print("V30_EVALUATE",evaluate(args.out))
