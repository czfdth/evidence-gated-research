#!/usr/bin/env python3
"""Attested partial upstream RobustRAG algorithm-path reproduction.
Executes unchanged original upstream class ASTs with a Qwen model adapter.
Not original Mistral/Llama/GPT model; decoding CUDA code not run.
Uses original RealtimeQA dataset, prompt template, data class, PIA/Poison and
majority/keyword aggregation from pinned github blobs.
"""
import argparse, ast, collections, hashlib, json, logging, random, runpy, time
from pathlib import Path
from itertools import combinations
import spacy
from nltk.corpus import stopwords
from retrieval_qa_voting_smoke import RealLLM

EXPECTED = {
    "src/defense.py": "dcebedf9d7629963e6cd2998426243d92ac0252f",
    "src/attack.py": "9d56cc97e2a4fb2e2fa10b24bfb46c96c944f642",
    "src/dataset_utils.py": "c2c53c26ad9529d1d47e9622023fd3a10f478f81",
    "src/helper.py": "7c134df5c8f2de7c139af746cf5c2922a306b33",
    "src/models.py": "7d9ad2b483a2e7a09bce40ccf07c490a8893592a",
    "src/prompt_template.py": "80b7382c59192a124454d0a5a6c709b86b839237",
}
def git_blob(path):
    b=path.read_bytes()
    return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def original_classes(root, path, names, g):
    p=root/path
    actual=git_blob(p)
    if actual!=EXPECTED[path]: raise RuntimeError(f"Unverified source {path}: {actual}")
    tree=ast.parse(p.read_bytes(), filename=str(p))
    nodes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in names]
    if {n.name for n in nodes}!=set(names): raise RuntimeError(f"Original classes missing from {path}")
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(p),"exec"),g)
    return g
def original_function(root, path, fname, g):
    p=root/path
    if git_blob(p)!=EXPECTED[path]: raise RuntimeError("Source mismatch "+path)
    tree=ast.parse(p.read_bytes(),filename=str(p))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==fname]
    if len(nodes)!=1: raise RuntimeError("Missing "+fname)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(p),"exec"),g)
    return g[fname]

class OriginalPromptQwen(RealLLM):
    def __init__(self, original_wrap, prompt_templates):
        super().__init__(max_new_tokens=24)
        self._original_wrap = original_wrap
        self.prompt_template = prompt_templates
    def wrap_prompt(self,*args,**kwargs):
        return self._original_wrap(self,*args,**kwargs)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--upstream",default="upstream-RobustRAG")
    ap.add_argument("--limit",type=int,default=2)
    ap.add_argument("--top-k",type=int,default=10)
    ap.add_argument("--output",default="results/upstream-algorithms")
    args=ap.parse_args()
    root=Path(args.upstream); out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    if not 1<=args.limit<=10 or not 2<=args.top_k<=20: raise ValueError("Bounded CPU smoke only")
    for key,digest in EXPECT.items():
        if git_blob(root/key)!=digest: raise RuntimeError("Source integrity failure "+key)
    random.seed(20271011)
    namespace=dict(__name__="original_robustrag_attested", Counter=collections.Counter,
        defaultdict=collections.defaultdict, combinations=combinations, spacy=spacy,
        logger=logging.getLogger("RRAG"), INJECTION=False, punctuation=r"""!"#$%&'()*+,-./:;<=>?@[\]^_\x60{|}~""",
        stopword_set=set(stopwords.words("english")), save_all_responses=lambda *a,**k: None)
    original_function(root,"src/helper.py","clean_str",namespace)
    original_classes(root,"src/dataset_utils.py",["DataUtils","RealtimeQA"],namespace)
    original_classes(root,"src/attack.py",["Attack","PIA","Poison"],namespace)
    original_classes(root,"src/defense.py",["RRAG","MajorityVoting","KeywordAgg"],namespace)
    original_classes(root,"src/models.py",["BaseModel"],namespace)
    templates=runpy.run_path(str(root/"src/prompt_template.py"))["GPT_TMPL"]
    model=OriginalPromptQwen(namespace["BaseModel"].wrap_prompt,templates)
    records=json.loads((root/"data/realtimeqa.json").read_text())
    selected=[]
    for idx,obj in enumerate(records):
        try:
            choices=obj["choices"]
            correct=obj["choices answer"]
            int(correct)
            if len(choices)!=4 or len(obj.get("context",[]))<args.top_k: continue
            if not isinstance(obj.get("incorrect answer"),str) or not obj.get("incorrect_context"): continue
        except (KeyError,ValueError,TypeError): continue
        selected.append((idx,obj))
        if len(selected)>=args.limit: break
    if not selected: raise RuntimeError("No eligible official questions with attacks/choices")
    rows=[]
    for mode in ("voting", "keyword"):
        util=namespace["RealtimeQA"].__new__(namespace["RealtimeQA"])
        util.top_k=args.top_k;util.as_multi_choices=(mode=="voting")
        algo=namespace["MajorityVoting"](model) if mode=="voting" else namespace["KeywordAgg"](model,relative_threshold=0.5,absolute_threshold=5)
        for idx,raw in selected:
            base=util.process_data_item(json.loads(json.dumps(raw)))
            for attackname in ("clean","PIA","Poison"):
                if attackname=="clean": item=base
                else: item=namespace[attackname](top_k=args.top_k,poison_num=1,repeat=3).attack(base)
                before=model.counters()
                start=time.perf_counter()
                try:
                    if mode=="voting":
                        response,cert=algo.query(item,corruption_size=(1 if attackname=="clean" else 0))
                    else:
                        response,cert=algo.query(item,corruption_size=(1 if attackname=="clean" else 0))
                    err=""
                except Exception as ex:
                    response="";cert=False;err=type(ex).__name__+": "+str(ex)
                end=time.perf_counter()
                after=model.counters()
                cost={k:round(after[k]-before[k],5) for k in before}
                try:
                    correct=bool(util.eval_response(response,base)) if not err else False
                except Exception:correct=False
                rows.append(dict(id=idx,method=mode,attack=attackname,
                    response=response,correct=correct,certified=bool(cert),error=err,
                    model_calls=cost,wall_seconds=round(end-start,3),
                    attack_source="original upstream PIA/Poison code",
                    model_adapter="Qwen2.5-0.5B, substituted for author original models"))
                print("Case",idx,mode,attackname,"correct",correct,"certificate",cert,"error",err,flush=True)
    run=dict(original_blob_ids=EXPECTED, original_source_pinned=True, data="upstream data/realtimeqa.json",
        model="Qwen/Qwen2.5-0.5B-Instruct", original_prompt_family="GPT_TMPL", corpus_count=len(selected),
        external_model_substitution=True, INJECTION=False,
        attack_model="one last-position passage modification by original PIA/Poison",
        limitations="Partial method reproduction only. No original main.py, no Mistral/Llama/GPT, no decoding aggregation, no Biogen LLM-as-a-judge.",
        totals=model.counters())
    (out/"rows.json").write_text(json.dumps(rows,indent=2))
    (out/"metadata.json").write_text(json.dumps(run,indent=2))
    (out/"raw_calls.json").write_text(json.dumps(model.calls,indent=2))
    (out/"summary.json").write_text(json.dumps([
        dict(method=m,attack=a,n=len(xs),correct=sum(x["correct"] for x in xs),
            certified=sum(x["certified"] for x in xs),errors=[x["error"] for x in xs if x["error"]])
        for m in ("voting","keyword") for a in ("clean","PIA","Poison")
        for xs in [[x for x in rows if x["method"]==m and x["attack"]==a]]
    ],indent=2))
    if any(r["error"] for r in rows):
        print("Warning: Some method paths could not complete; inspect summary",flush=True)
    print(json.dumps(run,indent=2),flush=True)

if __name__=="__main__":main()
