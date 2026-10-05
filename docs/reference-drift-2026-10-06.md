# Reference Drift Review

Date: 2026-10-06

Method: compared each pinned source-audit commit with the repository's latest
commit through the GitHub compare API. This is a drift review, not a claim that
every upstream change has been semantically reproduced locally.

## ARIS

- Previous pin: `2132036060e03e8d0df69a4b21e5971819c0c2d6`
- New pin: `3b19a22dc5a64c983d2eafd6c2c94000fadc4f8d`
- Changed: 2 commits, 12 files.
- Material change: optional Grok and Antigravity CLI bridges, plus reviewer
  routing notes.

Decision: no local gate change. The upstream note explicitly says these direct
consultation tools are not new reviewer values and do not satisfy a review
gate. Our `cross_review.py` already has the stricter rule: an acquittal needs a
known different model family and complete provider provenance. A bridge alone
must not be counted as an independent review.

## open-science

- Previous pin: `e4ba390f9f797800b06aa70c5ccae51a956f4baf`
- New pin: `bd9a61a80a73df317573b15ce1a32f1d007cba9b`
- Changed: 9 commits, about 150 files.
- Material changes: artifact provenance graph now records advisory cross-language
  file dependency edges and marks unresolved file reads as truncated history;
  replay exposes standalone artifact/review records immediately.

Decision: the replay UI change is outside this CLI workflow. The provenance
graph change is method-level and is recorded as a future graph-alignment item;
it does not justify weakening any current gate or auto-accepting a dependency
that has not been observed at runtime. The pin is updated only to the reviewed
snapshot, and the future item remains explicit rather than silently marked as
implemented.

## Boundary

Updating a pin means "this upstream state was read and classified", not "all
upstream behavior is now implemented locally". The next scheduled audit will
fail again if either repository publishes another commit.
