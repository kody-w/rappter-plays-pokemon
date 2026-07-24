# RAPPter Plays Pokémon public telemetry corpus

## Purpose

This dataset supports analysis, retrieval, evaluation, and optional downstream
model training using a public record of an autonomous gameplay run.

## Contents

- Every validated revision of the public `story-archive` timeline
- Sanitized execution receipts for autonomous model and verified controller
  actions
- Source Git commit, agent SHA-256, model configuration, progress counters,
  action enums, coarse outcomes, and stuck-signal enums
- A deterministic SQLite materialization and canonical JSONL export

## Exclusions

The corpus contains no ROM/save bytes or hashes, screenshots, video, audio,
coordinates, map IDs, collision maps, prompts, observations, objectives, raw
model output, chat, identities, secrets, authenticated URLs, or local paths.
Manual-control receipts are excluded from the public training-eligible export.

## Provenance and versioning

`story-archive` is the human-diffable source history. Each `story-warehouse`
commit is a complete as-of warehouse snapshot. The manifest names the exact
source commit, builder commit and module hash, database hash, receipt hash,
schema version, counts, and privacy assertions.

## Limitations

This is one evolving run, not an independent benchmark or verified optimal
demonstration. Model revisions may be unknown, observations are partially
observable, early decision-level evidence was not retained, and story coverage
contains explicit gaps. Movement and graph discovery are diagnostic signals,
not proof of semantic progress.

## License

Publisher-owned compilation and generated telemetry are offered under
[CC0-1.0](DATA_LICENSE.md), subject to the third-party-rights disclaimer there.
