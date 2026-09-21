# Uncommitted harness changes after FireRed / FSMN VAD runs

Reviewer note for a follow-up agent. This is a code-and-evidence review of the **current uncommitted worktree**, not a request to commit.

Date of review: 2026-09-21.
Branch: `harness-tui-agent` @ `32edab2`.
Question that produced this note: whether the local repo changes are reasonable after running open-source FireRed VAD and an internal VAD through SURE.

**Verdict: agree with the direction; do not treat the current patch as a finished identity design.** The changes match real container-isolation failures from the two VAD runs. They can ship, but identity should be written correctly at generation time, and MCP arguments should be schema-filtered, not special-cased.

Do not revert the runs. Do not expand into model-wrapper rewrites unless the user asks.

## Scope

Uncommitted paths at review time:

```text
M  AGENTS.md
M  README.md
M  packages/coding-agent/test/suite/sure-eval-red-lines.test.ts
M  sure/skills/sure_approve/scripts/test_approval_flow.py
M  sure/skills/sure_infer/scripts/finalize_result_bundle.py
M  sure/skills/sure_infer/scripts/generate_predictions_via_server.py
M  sure/skills/sure_infer/scripts/infer_entrypoint.py
M  sure/skills/sure_infer/scripts/test_finalize_result_bundle.py
?? docs/asr-vad-coding-review.md
?? sure/skills/sure_infer/scripts/test_mounted_model_generation.py
```

Not in this diff (gitignored / run artifacts):

- `sure/models/FireRedTeam__FireRedVAD/`
- `sure/models/AISpeech__FSMN-VAD-aicar016-230626/`
- `sure/results/...`
- Docker images / weights

Those packages and result trees are **evidence**, not the patch under review.

## What the two runs proved

Both models completed Infer + Eval on `dihard3_eval_vad_full_recordings__unversioned` (259 samples). `validation_payload.is_valid=true`. Five VAD metrics were produced.

| Model | Infer run | Eval batch | f1 | p_fa | p_miss | dcf_nist | auc_roc |
|---|---|---|---:|---:|---:|---:|---:|
| `FireRedTeam__FireRedVAD` | `sure/results/FireRedTeam__FireRedVAD/standard_system/main_agent_FireRedTeam__FireRedVAD_20260917_203332_357923` | `sure_eval_15ee214be05b7da2dd868bfc` | 0.936670 | 0.371178 | 0.032753 | 0.117360 | 0.971439 |
| `AISpeech__FSMN-VAD-aicar016-230626` | `sure/results/AISpeech__FSMN-VAD-aicar016-230626/standard_system/main_agent_AISpeech__FSMN-VAD-aicar016-230626_20260921_095518_854249` | `sure_eval_022bc00b22fa06acc93623e3` | 0.917020 | 0.382070 | 0.067790 | 0.146360 | 0.953021 |

Shared runtime facts that the patch is reacting to:

- Execution path: `local_docker`.
- Model mount: `model_dir=/model`.
- Tool: `detect_voice_activity`.
- Tool schema: only `audio_path`, `additionalProperties: false`.
- Observed MCP `argument_keys`: `["audio_path"]`.
- `artifact_path_localization.json` records `mount_name=model` rewritten to the canonical model name.
- Protocol `argument_policy.language_argument` is still `en`, but that value was **not** sent to the tool.

FireRed image: `127.0.0.1:5001/sure/vad/fireredteam__fireredvad@sha256:ddb66cb2d8be49dbebfaa702472bab4e2a12064feef62549b1084a7a097490b4`.

Internal VAD image: `127.0.0.1:5001/sure/vad/aispeech__fsmn-vad-aicar016-230626@sha256:aa23f3f65b5c89d4be082450c7e20863994de81fd6a02c9cef64e68d9bef7ae2`. Its **base_image** is the FireRed digest above. Config describes a firered-inspired postprocessor. The eval chain is valid; the two implementations are not independent.

## Mapping: failure → patch

### 1. Protocol resolution must not scan the parent of `/model`

Old code:

```python
registry = ModelRegistry(model_dir.parent)  # "/" inside the container
model_info = registry.get_model(model_dir.name)  # "model"
```

`ModelRegistry._discover_models()` calls `Path.iterdir()` on that parent. On `/` this is a `PermissionError` or a filesystem walk. `ProtocolResolver.resolve("standard_system", ...)` does not even use model params; the registry scan was a pure side effect.

New code builds `ModelInfo` from `model_dir/config.yaml` only. That is the correct isolation boundary.

`sure/skills/sure_infer/scripts/sure_eval/models/registry.py` already documents a mount alias (`/workspace/model` looked up as `"model"`). That alias only works if the parent directory is readable and contains the one bundle. Isolated `/model` mounts do not satisfy that. Do not restore `ModelRegistry(model_dir.parent)`.

### 2. Canonical model name vs mount directory name

Writers previously mixed:

- `model_dir.name` → `"model"` in `prediction_generation_status.json` and `predictions/manifest.json`
- `config.yaml` `name` / `MODEL_NAME` → `FireRedTeam__FireRedVAD` in `protocol.yaml`

The patch makes generation use `config.yaml` `name` (fallback: directory name) and makes finalize accept either the mount basename or the inventory canonical name, then rewrite status/manifest to the canonical name.

Inventory field used for the canonical name:

```text
runtime_inventory.json → model.name
```

Both VAD inventories have this field. Finalize also compares `container_runtime.target_image_ref` (and `model_runtime.runtime_id`, which these inventories do not set).

`infer_entrypoint.py` now always passes `--model-dir` into finalize.

### 3. Do not send `language` to VAD tools

Both wrappers declare:

```yaml
properties:
  audio_path: {type: string}
required: [audio_path]
additionalProperties: false
```

`_build_tool_arguments` still injects `language` whenever the dataset/CLI has one. The new pop:

```python
if "language" not in allowed_tool_args:
    arguments.pop("language", None)
```

is why the successful runs recorded `argument_keys: ["audio_path"]`. Without it, MCP validation would reject the call.

### 4. Other files in the same worktree

- `docs/asr-vad-coding-review.md` plus pointers in `AGENTS.md` / `README.md`: process runbook for Feed → Onboard → Approve → Infer → Eval. Matches what these runs just did. Keep it.
- `sure-eval-red-lines.test.ts`: stop feeding Python via stdin; write a probe file. Restricted Vitest workers can inherit a non-EOF stdin. Unrelated to VAD, keep it.
- `test_approval_flow.py`: fixture now uses `protected/models` under `forbidden_output_roots`, and `allowed_source_roots` as a mapping. Aligns with `sure.site.policy.v1` (`approved` roots must sit under a forbidden parent; dataset roots are a map). Loader still accepts a one-element list and rewrites it to `{default: ...}`, so the mapping change is style, the `protected/` split is the real fixture fix.

## Agree

- Isolated mounts must not require listing the parent of `/model`.
- Artifact `model_name` must be the approved config/inventory name, not the mount basename.
- MCP `tools/call` arguments must not include fields the approved tool schema does not declare. VAD is the example that forced this.
- Finalize may **verify** that generation status, protocol, and approved inventory name the same model and image.
- Prediction JSONL/TXT must not be rewritten during path localization. The new tests keep that rule.
- The two VAD result trees are acceptable evidence that this harness path works for container_only VAD.

## Disagree / do not copy as-is

### A. Finalize should not rewrite identity

`finalize_result_bundle.py` currently:

1. Allows `status.model_name` to be either mount basename or canonical name.
2. Requires `protocol.yaml` `model.model_name` to **already** be canonical.
3. Rewrites `prediction_generation_status.json` and `predictions/manifest.json` to the canonical name.
4. Mixes that rewrite into path localization.

That asymmetry exists because `protocol_writer.py` already reads `config.yaml` `name`, while old generation used `model_dir.name`. After generation also reads `config.yaml`, the rewrite is redundant.

Preferred contract:

- Generation writes canonical `model_name` everywhere it emits identity.
- Finalize fails if status, manifest, protocol, and `runtime_inventory.model.name` disagree.
- Finalize does not mutate identity fields.
- Path localization stays a path-only transform.

If a compatibility window for old in-flight runs is required, gate it explicitly and do not leave dual acceptance as the long-term API.

### B. Runtime identity check is weaker than it looks

```python
identity_key = "target_image_ref" if field == "container_runtime" else "runtime_id"
```

For these VAD inventories, `model_runtime.runtime_id` is absent, so that half of the loop is `None == None`. The only real check is `target_image_ref`. That is enough for `container_only`, but do not document it as a full runtime fingerprint.

If the check is kept, compare the fields the inventory actually uses for eval identity (`target_image_ref` for container, `runtime_id` / lock hashes for python) and skip missing sides instead of pretending both always apply.

### C. Filter MCP arguments by schema, do not special-case `language`

`language` is not the only extra key `_build_tool_arguments` can add. A later undeclared field will hit `additionalProperties: false` the same way.

After `_build_tool_arguments`, drop every key not in `allowed_tool_args` (and keep required-key validation). Use that same set in `_merge_protocol_tool_args`. Tests should cover:

- VAD / schema without `language` → call args are exactly `{audio_path: ...}`
- ASR / schema with `language` → `language` is sent
- An unrelated extra key is dropped or rejected, not only `language`

### D. `test_mounted_model_generation.py` still mocks `Path.iterdir`

After the registry bypass, that mock never fires. It does not prove isolation. Replace it with a direct assertion that protocol resolution reads only `model_dir/config.yaml` and does not construct `ModelRegistry`. Keep the language in/out test; that one is load-bearing.

### E. Provenance from the eval runs is thinner than AGENTS.md

Both `source_inference_provenance.json` files only link `protocol.yaml`. Maintainer table in `AGENTS.md` also wants generation status and runtime inventory when available. That gap is **not introduced by this diff**. Do not block this patch on it; do not claim the eval provenance chain is complete either.

## Suggested follow-up work (for the agent reading this)

Keep the change set scoped to harness identity / MCP args / tests / the runbook. Do not onboard or re-infer the VAD models unless asked.

1. Stop rewrite in `finalize_result_bundle.py`; verify-only when `--model-dir` is passed.
2. Keep generation as the single writer of canonical `model_name`.
3. Replace `arguments.pop("language", None)` with schema whitelist filtering.
4. Tighten `test_mounted_model_generation.py` and keep `test_finalize_result_bundle.py` covering: matching identity passes, mismatched name fails, mismatched image digest fails, prediction JSONL bytes unchanged.
5. Leave the approval fixture and stdin-probe test as they are unless a regression appears.
6. Run, from this repo’s rules:
   - `python3 -m unittest` on the touched infer/approve test modules (harness venv if `pydantic` / `sure_eval` is required)
   - `python3 -m py_compile sure/skills/sure_infer/scripts/*.py`
   - `npm run check` after code changes
7. Do not commit unless the user asks. Stage only files changed in that follow-up session.

## Files to read first

```text
sure/skills/sure_infer/scripts/generate_predictions_via_server.py
  _resolve_protocol_parameters
  _build_tool_arguments
  _declared_tool_args
  main() model_name / arguments.pop("language")

sure/skills/sure_infer/scripts/finalize_result_bundle.py
sure/skills/sure_infer/scripts/infer_entrypoint.py   # stage_finalize
sure/skills/sure_infer/scripts/protocol_writer.py    # already uses config name
sure/skills/sure_infer/scripts/sure_eval/models/registry.py
sure/skills/sure_infer/scripts/sure_eval/protocols/resolver.py

sure/models/FireRedTeam__FireRedVAD/config.yaml
sure/models/AISpeech__FSMN-VAD-aicar016-230626/config.yaml
sure/results/FireRedTeam__FireRedVAD/standard_system/main_agent_FireRedTeam__FireRedVAD_20260917_203332_357923/artifact_path_localization.json
sure/results/AISpeech__FSMN-VAD-aicar016-230626/standard_system/main_agent_AISpeech__FSMN-VAD-aicar016-230626_20260921_095518_854249/artifact_path_localization.json
```

This document is the review. The receiving agent should implement A–D if asked to act on it, and should not treat the two VAD metric tables as a reason to change thresholds or baselines.
