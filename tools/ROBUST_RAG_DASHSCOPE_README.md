# Source-pinned RobustRAG × DashScope reproduction

**Status:** original source/prompt/data verification is automated; the real DashScope inference phase requires a GitHub Actions secret. No passwords or API keys are stored in this repository.

## Secure one-time setup

1. **Immediately revoke any DashScope key that has been pasted into chat, an issue, a commit, or a public log. Generate a new restricted key.**
2. Open [this repository's GitHub Actions Secrets settings](https://github.com/czfdth/evidence-gated-research/settings/secrets/actions).
3. Choose **New repository secret**, name it exactly `DASHSCOPE_API_KEY`, and paste the *new rotated key*. Consider configuring a minimal spending/quota limit in DashScope. Never send the new key in a chat.
4. Notify the research assistant only that the secret is set. The assistant can trigger the existing branch workflow by a new commit; don't send the secret itself.

## Workflow

The complete source is [`tools/robustrag_dashscope_reproduce.py`](../tools/robustrag_dashscope_reproduce.py).
The runnable Actions workflow is [`.github/workflows/robustrag-dashscope.yml`](../.github/workflows/robustrag-dashscope.yml).

The workflow uses an unchanged original AST extraction for the following upstream classes:

- RealtimeQA and DataUtils / BaseModel's prompt formatting.
- MajorityVoting and KeywordAgg.
- PIA and Poison, using the original classes and original reference dataset.
- GPT prompt family, with the DashScope Qwen-plus API substituted for the original models.

Sources are pinned using Git blob SHA-1 and checked before execution.
The API endpoint is `https://dashscope.aliyuncs.com/compatible-mode/v1`.
The workflow initially limits spend to one public question and at most 400 uncached API calls.
Outputs include per-query predictions, correctness, source-defined target ASR, certificate flags, latency, token usage, cache stats, and source hashes.

**Honest scope boundary:** this is not a full replication of the original paper's Mistral/Llama/GPT experiments. Original secure decoding uses GPU-side token probability/logit and key/value-cache internals that are not available through chat-completion-only DashScope APIs. A positive upstream certificate is contingent on all original assumptions; model substitution and public test subset must be disclosed.

The network-run outputs are published as private-to-repo GitHub Actions artifacts with 7-day retention (GitHub workflow metadata is publicly visible). Only public RealtimeQA inputs are used. No submitted manuscript, author coding materials or API keys are uploaded.
