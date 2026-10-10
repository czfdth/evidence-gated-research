#!/usr/bin/env python3
"""v30 audited paired-world witness with complete PUBLIC signed-ledger equality.

The original v29 paired demonstration published old timestamps inside signed CUT
records. That meant the full P observation differed. This corrective experiment
publishes only common cut/catalog/selection/rollback receipts. Private truth is
held separately for grading. The pinned official LangChain retriever still makes
both selections and updates the access-time metadata.

A P auditor runs with ONLY the --out public folder and must abstain. This is an
existence witness for a restricted observation, NOT a production cut-attestation.
"""
import argparse
import base64
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("v29_native_source",HERE/"locomo_readside_v29.py")
v29=importlib.util.module_from_spec(spec)
spec.loader.exec_module(v29)
T=dt.datetime(2026,10,10,12,0,0)
Q="Which earlier memory should be selected?"
RELEVANCE={"A":0.95,"B":0.8,"C":0.85}
CUT_ID="public-audit-target-001"
CLOCK=v29.iso(T)
K=2

class Clock(dt.datetime):
 @classmethod
 def now(cls,tz=None):return T

def data(path):return json.loads(path.read_text())
def name_to_doc(ret):return {x.metadata["item_id"]:x for x in ret.memory_stream}

def generate(root,upstream):
 assert not (root/"public").exists(),"use an empty evidence directory"
 model=v29.load_upstream(upstream)
 pub=root/"public";private=root/"private";pub.mkdir(parents=True);private.mkdir(parents=True)
 sk=Ed25519PrivateKey.generate()
 pk=base64.b64encode(sk.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()
 joint_catalog={"candidate_ids":["A","B","C"],"selector":"pinned-time-weighted",
                "clock":CLOCK,"decay_rate":0.01,"k":K,"query":Q,
                "relevance":RELEVANCE,"old_C_access_age_hours_domain":[1,6],
                "importance_after_rollback":{"A":1.0,"B":0.0,"C":0.0}}
 observations=[];truth=[]
 for index,old_age in enumerate([6,1]):
  documents=[
   v29.Document(page_content="Evidence A",metadata={"item_id":"A","importance":1.0,"last_accessed_at":T}),
   v29.Document(page_content="Evidence B",metadata={"item_id":"B","importance":0.0,"last_accessed_at":T}),
   v29.Document(page_content="Evidence C",metadata={"item_id":"C","importance":0.0,"last_accessed_at":T-dt.timedelta(hours=old_age)})]
  retriever=v29.create_retriever(model,documents,search_k=3,k=K)
  retriever.vectorstore.similarity_search_with_relevance_scores=lambda q,**kw: [
   (d,RELEVANCE[d.metadata["item_id"]]) for d in retriever.memory_stream]
  docs=name_to_doc(retriever)
  oldaccess={k:v29.iso(d.metadata["last_accessed_at"]) for k,d in docs.items()}
  signer=v29.Signed(pub/("world-"+str(index)+"-ledger.jsonl"))
  signer.sk=sk;signer.pk=pk
  # The signed public CUT intentionally does NOT contain the historical
  # timestamp, a digest over it, a private state root or a world-dependent ID.
  # Such a root would break the information-theoretic same-observation claim.
  signer.sign("CUT",cut_id=CUT_ID,
              public_catalog_sha256=v29.dig(v29.enc(joint_catalog)),
              query_sha256=v29.dig(Q.encode()),audit_clock=CLOCK)
  with patch.object(model.datetime,"datetime",Clock):
   order=sorted(retriever.memory_stream,
         key=lambda d:retriever._get_combined_score(d,RELEVANCE[d.metadata["item_id"]],T),reverse=True)
   cut_reference=[d.metadata["item_id"] for d in order[:K]]
   c=docs["C"];old_imp=c.metadata["importance"];c.metadata["importance"]=0.15
   signer.sign("PREWRITE",cut_id=CUT_ID,field="C.importance",
               write_event_id="WC",old_importance=old_imp)
   actual=[d.metadata["item_id"] for d in retriever.invoke(Q)]
   post_read={k:v29.iso(d.metadata["last_accessed_at"]) for k,d in docs.items()}
   c.metadata["importance"]=old_imp
   rollback={k:{"importance":d.metadata["importance"],
                "last_accessed_at":v29.iso(d.metadata["last_accessed_at"])}
             for k,d in docs.items()}
  signer.sign("READ_COMMIT",cut_id=CUT_ID,selected=actual,
              after_access=post_read,write_rollback="C.importance")
  assert len(v29.verify(signer.path,pk))==3
  observations.append({"selected":actual,"rolled_back_state":rollback})
  truth.append({"world_index":index,"private_C_age_hours":old_age,
                "private_cut_access_times":oldaccess,
                "cut_reference":cut_reference,"actual_read":actual,
                "cut_equivalent":set(cut_reference)==set(actual)})
 assert observations[0]==observations[1], observations
 a=(pub/"world-0-ledger.jsonl").read_bytes()
 b=(pub/"world-1-ledger.jsonl").read_bytes()
 assert a==b,"PUBLIC SIGNED CUT+READ LOGS MUST BE BYTE-IDENTICAL"
 assert truth[0]["cut_equivalent"]!=truth[1]["cut_equivalent"]
 v29.save(pub/"catalog.json",joint_catalog)
 v29.save(pub/"observation.json",{"cut_id":CUT_ID,"public_key":pk,
                                  "world_observations":observations,
                                  "public_ledgers_equal":True})
 v29.save(private/"oracle.json",{"paired_worlds":truth,
       "notice":"private grading truth; absent from restricted P public view"})
 print("NATIVE_GENERATE_OK",json.dumps({"identical_public_signed_ledger_sha256":hashlib.sha256(a).hexdigest(),
       "worlds":2,"opposed_labels":True},sort_keys=True))

def audit(pub):
 # ABSOLUTELY NO private/oracle access here. A separate unprivileged process
 # can run with only a copy of this public directory.
 cat=data(pub/"catalog.json");obs=data(pub/"observation.json")
 assert obs["cut_id"]==CUT_ID
 assert obs["public_ledgers_equal"]
 a=(pub/"world-0-ledger.jsonl").read_bytes()
 b=(pub/"world-1-ledger.jsonl").read_bytes()
 assert a==b,"public signed ledgers differ"
 for index in [0,1]:
  messages=v29.verify(pub/("world-"+str(index)+"-ledger.jsonl"),obs["public_key"])
  assert [x["kind"] for x in messages]==["CUT","PREWRITE","READ_COMMIT"]
  assert all(x["cut_id"]==CUT_ID for x in messages)
  assert "old_access" not in json.dumps(messages)
  assert messages[0]["public_catalog_sha256"]==v29.dig(v29.enc(cat))
  assert messages[1]["old_importance"]==0.0
  assert messages[2]["selected"]==["A","C"]
 assert obs["world_observations"][0]==obs["world_observations"][1]
 cut_possible=[]
 for age in cat["old_C_access_age_hours_domain"]:
  scores={}
  for candidate in cat["candidate_ids"]:
   hours=age if candidate=="C" else 0
   scores[candidate]=(1-cat["decay_rate"])**hours+cat["importance_after_rollback"][candidate]+cat["relevance"][candidate]
  selected=sorted(cat["candidate_ids"],key=lambda k:scores[k],reverse=True)[:cat["k"]]
  cut_possible.append({"candidate_age":age,"possible_cut_reference":selected,
                       "cut_equivalent":set(selected)==set(obs["world_observations"][0]["selected"])})
 assert set(x["cut_equivalent"] for x in cut_possible)=={True,False}
 verdict={"verdict":"UNVERIFIABLE","possible_cut_outcomes":cut_possible,
          "public_signed_ledgers_byte_identical":True,
          "public_signed_ledger_sha256":hashlib.sha256(a).hexdigest(),
          "used_private_oracle":False,
          "message":"The public read+rollback observation alone does not identify cut equivalence."}
 v29.save(pub/"audit-verdict.json",verdict)
 print("PUBLIC_ONLY_AUDIT_OK",json.dumps(verdict,sort_keys=True))

def grade(root):
 public=data(root/"public"/"audit-verdict.json")
 private=data(root/"private"/"oracle.json")["paired_worlds"]
 assert public["verdict"]=="UNVERIFIABLE"
 assert len(private)==2 and private[0]["cut_equivalent"]!=private[1]["cut_equivalent"]
 for row in private:
  matching=[p for p in public["possible_cut_outcomes"] if p["candidate_age"]==row["private_C_age_hours"]]
  assert len(matching)==1 and matching[0]["possible_cut_reference"]==row["cut_reference"]
 v29.save(root/"grading-summary.json",{"native_paired_worlds":2,
     "identical_public_signed_event_bytes":True,"different_private_cut_labels":True,
     "restricted_P_verdict":"UNVERIFIABLE","oracle_consistent":True,
     "public_vs_private_layout":"public/ contains no actual old timestamp; private/ stores grading truth"})
 print("PRIVATE_ORACLE_GRADE_OK")

if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--mode",choices=["generate","audit","grade"],required=True)
 p.add_argument("--out",type=Path,required=True)
 p.add_argument("--upstream",type=Path,default=Path("src/time_weighted_retriever_v29.py"))
 a=p.parse_args()
 if a.mode=="generate":generate(a.out,a.upstream)
 if a.mode=="audit":audit(a.out)
 if a.mode=="grade":grade(a.out)
