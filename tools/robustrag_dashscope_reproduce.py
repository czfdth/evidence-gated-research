#!/usr/bin/env python3
"""Reproduce ORIGINAL RobustRAG voting/keyword + original PIA/Poison on RealtimeQA,
using a DashScope OpenAI-compatible API adapter.

Original algorithms are extracted as unchanged AST class/function nodes from
PINNED upstream git blobs. This is an API MODEL SUBSTITUTION, *not* a reproduction
of the paper's Mistral/Llama/internal-logit decoding experiments.

No API key is accepted via command line or stored in files. Only read env.
"""
import argparse
import ast
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import logging
import os
from itertools import combinations
from pathlib import Path
import random
import time
import urllib.request
import urllib.error

EXPECTED_BLOBS = {
    "src/defense.py": "dcebedf9d7629963e6cd2998426243d92ac0252f",
    "src/attack.py": "9d56cc97e2a4fb2e2fa10b24bfb46c96c944f642",
    "src/dataset_utils.py": "c2c53c26ad9529d1d47e9622023fd3a10f478f81",
    "src/helper.py": "7c134df5c8f2de7c139af746cf5c2922a306b33d",
    "src/models.py": "7d9ad2b483a2e7a09bce40ccf07c490a8893592a",
    "src/prompt_template.py": "80b7382c59192a124454d0a5a6c709b86b839237",
}
# A fixed source hash is checked before ANY original node is executed.
API_BASE_DEFAULT = "https://dashscope.aliyuncs.com/compatible-mode/v1"

def blob_sha(p):
    data = p.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def verified_tree(root, name):
    p = root / name
    actual = blob_sha(p)
    if actual != EXPECTED_BLOBS[name]:
        raise RuntimeError(f"Source integrity mismatch: {name}; expected {EXPECTED_BLOBS[name]}, got {actual}")
    return ast.parse(p.read_bytes(), filename=str(p))

def transplant(root, path, classnames=(), functions=(), namespace=None):
    ns = namespace if namespace is not None else {}
    nodes = []
    for node in verified_tree(root, path).body:
        if isinstance(node, ast.ClassDef) and node.name in classnames:
            nodes.append(node)
        if isinstance(node, ast.FunctionDef) and node.name in functions:
            nodes.append(node)
    if {n.name for n in nodes} != set(classnames)|set(functions):
        raise RuntimeError(f"Missing upstream nodes in {path}")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(root/path), "exec"), ns)
    return ns

def prompt_templates(root):
    import runpy
    verified_tree(root, "src/prompt_template.py")
    return runpy.run_path(str(root/"src/prompt_template.py"))["GPT_TMPL"]

class DashScopeBackend:
    def __init__(self, model, api_base, cap, temperature=0):
        key = os.getenv("DASHSCOPE_API_KEY")
        if not key:
            raise RuntimeError("DASHSCOPE_API_KEY is unset; configure a repository/runner secret. Never commit the key.")
        if not api_base.startswith("https://dashscope.aliyuncs.com/compatible-mode/v1"):
            raise ValueError("Only the expected official HTTPS DashScope-compatible endpoint is allowed")
        self.key=key
        self.model_name="gpt-compatible-dashscope-parser" # source voting chooses 'gpt' parser; actual model shown separately
        self.actual_model=model
        self.prompt_template=None
        self.cap=cap
        self.temperature=temperature
        self.endpoint=api_base.rstrip("/")+"/chat/completions"
        self._prompts={}
        self.calls=[]
        self.network_calls=0
    def query(self,prompt):
        if prompt in self._prompts:
            r=self._prompts[prompt]
            self.calls.append({"cached":True,"model":self.actual_model,"prompt_tokens":0,
                "completion_tokens":0,"elapsed_seconds":0.0,"output":r,"error":None})
            return r
        if self.network_calls>=self.cap:
            raise RuntimeError(f"Refusing API call beyond --max-api-calls={self.cap}")
        self.network_calls+=1
        payload = dict(model=self.actual_model, temperature=self.temperature,
            max_tokens=96, messages=[
              {"role":"system","content":"Answer concisely; for multiple choice, use exactly A., B., C., D. or E."},
              {"role":"user","content":prompt}])
        req = urllib.request.Request(self.endpoint,
          data=json.dumps(payload).encode("utf-8"),
          headers={"Authorization":"Bearer "+self.key,"Content-Type":"application/json"},
          method="POST")
        start=time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=100) as response:
                obj=json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # DO NOT print response or request headers; they may contain sensitive content.
            raise RuntimeError(f"DashScope HTTP {exc.code}; inspect model, quota, and endpoint") from None
        except Exception as exc:
            raise RuntimeError(f"DashScope request failed ({type(exc).__name__}), no result fabricated") from None
        elapsed=time.perf_counter()-start
        choices=obj.get("choices") or []
        if not choices: raise RuntimeError("API response missing choices")
        msg=choices[0].get("message",{})
        result=msg.get("content","")
        if not isinstance(result,str):
            raise RuntimeError("API response content was not plain text")
        result=result.strip()
        # Source MajorityVoting has an empty-response indexing error.
        # Only fill empty text with abstention, and account for it.
        if not result:
            result="E. No information found"
        usage=obj.get("usage",{})
        self._prompts[prompt]=result
        self.calls.append(dict(cached=False,model=self.actual_model,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            elapsed_seconds=round(elapsed,6),output=result,error=None))
        return result
    def batch_query(self, prompts):
        return [self.query(p) for p in prompts]
    def counters(self):
        return dict(logical_requests=len(self.calls),api_requests=self.network_calls,
           cache_hits=sum(c["cached"] for c in self.calls),
           prompt_tokens=sum(c.get("prompt_tokens",0) for c in self.calls),
           completion_tokens=sum(c.get("completion_tokens",0) for c in self.calls),
           model_latency_seconds=round(sum(c["elapsed_seconds"] for c in self.calls),5))

def make_originals(root):
    for p in EXPECTED_BLOBS: verified_tree(root,p)
    import spacy
    from nltk.corpus import stopwords
    g=dict(Counter=Counter,defaultdict=defaultdict,combinations=combinations,
        spacy=spacy,stopword_set=set(stopwords.words("english")),
        punctuation='!"#$%&\'()*+,-./:;<=>?@[\\]^_'+chr(96)+'{|}~',
        INJECTION=True,logger=logging.getLogger("upstream_robustrag"),
        save_all_responses=lambda *args,**kwargs: None)
    transplant(root,"src/helper.py",functions=("clean_str",),namespace=g)
    transplant(root,"src/dataset_utils.py",classnames=("DataUtils","RealtimeQA"),namespace=g)
    transplant(root,"src/models.py",classnames=("BaseModel",),namespace=g)
    transplant(root,"src/attack.py",classnames=("Attack","PIA","Poison"),namespace=g)
    transplant(root,"src/defense.py",classnames=("RRAG","MajorityVoting","KeywordAgg"),namespace=g)
    return g, prompt_templates(root)

def run(args):
    if args.limit<1 or args.limit>100 or args.max_api_calls<1 or args.max_api_calls>5000:
        raise ValueError("Invalid limit or API call limit")
    root=Path(args.upstream)
    g,templates=make_originals(root)
    if args.preflight_only:
        data=json.loads((root/"data/realtimeqa.json").read_text("utf-8"))
        required=("qa","qa-mc","qa-hint")
        missing=[k for k in required if k not in templates]
        if missing: raise RuntimeError("Missing original GPT prompt modes: "+str(missing))
        print(json.dumps({"preflight":"PASS","original_classes":
          ["DataUtils","RealtimeQA","BaseModel","PIA","Poison","RRAG","MajorityVoting","KeywordAgg"],
          "reference_dataset_records":len(data),"source_pins":EXPECTED_BLOBS,
          "secret_used":False,"model_calls":0},indent=2))
        return 0
    model=DashScopeBackend(args.model,args.api_base,args.max_api_calls)
    model.prompt_template=templates
    # Unmodified upstream BaseModel.wrap_prompt.
    model.wrap_prompt=g["BaseModel"].wrap_prompt.__get__(model,type(model))
    data_path=root/"data/realtimeqa.json"
    data=json.loads(data_path.read_text("utf-8"))
    chosen=[]
    for ix,datum in enumerate(data):
        if not isinstance(datum.get("choices"),list) or len(datum["choices"])!=4:continue
        try:
            if not 0<=int(datum["choices answer"])<=3: continue
        except (ValueError,TypeError,KeyError): continue
        if len(datum.get("context",[]))<args.top_k:continue
        if not isinstance(datum.get("incorrect answer"),str):continue
        if not datum.get("incorrect_context"):continue
        chosen.append((ix,datum))
        if len(chosen)>=args.limit:break
    if len(chosen)<args.limit: raise RuntimeError(f"Only {len(chosen)} eligible samples")
    random.seed(20271011)
    methods=args.methods.split(",")
    attacks=args.attacks.split(",")
    if any(s not in ("voting","keyword") for s in methods): raise ValueError("Unknown method")
    if any(s not in ("clean","PIA","Poison") for s in attacks): raise ValueError("Unknown attack")
    rows=[]
    # Cache deliberately shared; report logical request vs network requests separately.
    for method in methods:
        util=g["RealtimeQA"].__new__(g["RealtimeQA"])
        util.top_k=args.top_k
        util.as_multi_choices=method=="voting"
        algo=(g["MajorityVoting"](model) if method=="voting" else
              g["KeywordAgg"](model,relative_threshold=0.3,absolute_threshold=3))
        for idx,datum in chosen:
            item=util.process_data_item(deepcopy(datum))
            for attack in attacks:
                input_item=(item if attack=="clean" else
                   g[attack](top_k=args.top_k,poison_num=args.corruption_size,
                             repeat=args.repeat,poison_order="backward").attack(item))
                before=model.counters()
                start=time.perf_counter()
                # Preserve upstream attack-main convention: no attacked certificate.
                raw_pred, certificate=algo.query(deepcopy(input_item),
                        corruption_size=(args.corruption_size if attack=="clean" else 0))
                cost={k:round(model.counters()[k]-before[k],5) for k in before}
                correct=bool(util.eval_response(raw_pred,item))
                # Original attack success eval is string-match, not necessarily MC answer correctness.
                asr=(bool(util.eval_response_asr(raw_pred,item)) if attack!="clean" else False)
                rows.append(dict(index=idx,method=method,attack=attack,
                    correct=correct,original_asr=asr, certificate=bool(certificate),
                    response=raw_pred, costs=cost,
                    wall_seconds=round(time.perf_counter()-start,5)))
                print(f"Completed {method}/{attack}/sample-{idx}: correct={correct} "
                      f"cert={bool(certificate)} requests={cost['api_requests']}",flush=True)
    summaries=[]
    for method in methods:
        for attack in attacks:
            parts=[r for r in rows if r["method"]==method and r["attack"]==attack]
            if not parts: continue
            summaries.append(dict(method=method,attack=attack,n=len(parts),
                accuracy=sum(r["correct"] for r in parts)/len(parts),
                original_target_asr=(sum(r["original_asr"] for r in parts)/len(parts) if attack!="clean" else None),
                certified_correct_rate=sum(r["certificate"] and r["correct"] for r in parts)/len(parts),
                certificate_rate=sum(r["certificate"] for r in parts)/len(parts),
                mean_api_calls=sum(r["costs"]["api_requests"] for r in parts)/len(parts),
                mean_logical_requests=sum(r["costs"]["logical_requests"] for r in parts)/len(parts),
                mean_input_tokens=sum(r["costs"]["prompt_tokens"] for r in parts)/len(parts),
                mean_output_tokens=sum(r["costs"]["completion_tokens"] for r in parts)/len(parts),
                mean_request_latency_seconds=sum(r["costs"]["model_latency_seconds"] for r in parts)/len(parts),
                abstentions=sum(("don't know" in str(r["response"]).lower() or
                                 str(r["response"]).strip().upper().startswith("E.")) for r in parts)/len(parts)))
    output=Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    meta=dict(real_provider_api=True,api_base=args.api_base,model=args.model,
        dataset="public RobustRAG RealtimeQA",data_sha256=hashlib.sha256(data_path.read_bytes()).hexdigest(),
        source_git_blobs=EXPECTED_BLOBS,
        upstream_algorithm_classes_executed=[("RRAG","MajorityVoting","KeywordAgg"),("PIA","Poison")],
        original_prompts="GPT_TMPL",api_model_substitution=True,
        full_original_system_reproduction=False,
        original_decoding_aggregation_executed=False,
        original_training_or_Mistral_Llama_executed=False,
        backend_stats=model.counters(),selection=f"first {len(chosen)} eligible records",
        scope="original class AST and original RealtimeQA processor, API backend; no live retriever",
        caution="Certificates concern upstream assumptions and source correctness evaluation; not proof of actual LLM safety.")
    (output/"rows.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
    (output/"summary.json").write_text(json.dumps(summaries,indent=2),encoding="utf-8")
    (output/"metadata.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
    (output/"model_calls.json").write_text(json.dumps(model.calls,indent=2),encoding="utf-8")
    print(json.dumps({"summary":summaries,"backend":model.counters()},indent=2))
    return 0

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--preflight-only",action="store_true",help="Validate original source, classes, dataset and templates without a secret or model API call")
    p.add_argument("--upstream",default="upstream-RobustRAG")
    p.add_argument("--api-base",default=API_BASE_DEFAULT)
    p.add_argument("--model",default="qwen-plus")
    p.add_argument("--limit",type=int,default=1)
    p.add_argument("--top-k",type=int,default=10)
    p.add_argument("--corruption-size",type=int,default=1)
    p.add_argument("--repeat",type=int,default=3)
    p.add_argument("--methods",default="voting")
    p.add_argument("--attacks",default="clean,PIA,Poison")
    p.add_argument("--max-api-calls",type=int,default=100)
    p.add_argument("--output",default="results/dashscope-robustrag")
    raise SystemExit(run(p.parse_args()))
