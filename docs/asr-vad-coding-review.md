# ASR/VAD coding review runbook

这份手册是 agent 修改 SURE 代码后必须执行的流程审查。目标是证明一条完整的模型评测链路仍然成立：模型可以被发现和封装，封装结果经过审批，审批模型可以完成 ASR 或 VAD 推理，预测可以被原样交给评测引擎，最后的指标和来源身份可以复核。

自动化测试只能证明固定契约没有回归。只跑测试集合不能代替这份流程审查。每次审查都要留下运行目录、模型身份、数据集身份、协议、预测覆盖率和评测结果。

## 0. 先确定审查范围

先阅读本次代码 diff 和上一次已通过的运行记录。记录以下内容：

- 修改涉及 `sure_feed`、`sure_onboard`、`sure_approve`、`sure_infer`、`sure_eval` 中哪些阶段。
- 任务是 `ASR` 还是 `VAD`，数据集的完整 canonical 名称和版本。
- 使用的 approved model 目录、模型版本或镜像 digest。
- 上一次通过运行的 `protocol.yaml`、`prediction_generation_status.json`、`eval_run_report.json` 和指标。
- 本次修改预期影响的行为，以及不应变化的行为。

无法判断影响范围时，执行下面的完整流程。不要因为修改看起来只影响一个脚本，就跳过身份、推理和评测产物的检查。

## 1. Feed：确认模型来源和任务分类

当模型来源、模型卡、任务分类或 `MODEL_INPUT` 发生变化时，运行 `/sure_feed`。模型 URL 优先使用用户提供的精确 ModelScope、HuggingFace 或 GitHub 地址：

```text
/sure_feed url=<model-url> source=<modelscope|huggingface|github> handoff=true
```

agent 要完成以下工作：

1. 阅读模型卡、README、配置、依赖和推理示例。
2. 确认这是 ASR 或 VAD，不能只凭 provider 的宽泛标签判断。
3. 为任务选择 SURE fixture，并确认输入音频格式、采样率、通道数和输出结构。
4. 确认权重来源、运行时、入口脚本和工具名称都有证据。
5. 生成 `sure/handoffs/<model>/model_input.yaml`。

必须检查的产物是 `scan_result.json`、`match_task_result.json`、`metadata_result.json`、`oref_result.json`、`model_input_result.json`、`rank_select_result.json` 和 `handoff_manifest.json`。其中 `matched=true` 必须有匹配证据，`MODEL_INPUT` 必须包含 repo、weights、运行时、入口、fixture 和 IO contract。

如果本次修改只涉及共享推理或评测代码，且模型来源和 `MODEL_INPUT` 没变，可以复用上一次 handoff，但要在审查记录中写明复用理由和文件 digest。

## 2. Onboard：生成并验证可运行模型包

使用 Feed 生成的 handoff：

```text
/sure_onboard model=<handoff-model-name>
```

如果是在已有模型包上修复代码，使用该模型的 `model_input_path` 或 `existing_model_dir`，并明确这是 repair。不要把模型目录下的 `.venv` 当作 Eval runtime；运行时必须按当前 site policy 和锁文件生成并封存。

agent 要按 Onboard 状态机完成发现、分类、构建计划、fixture、环境、权重、wrapper、导入、加载、推理和输出 contract 验证。不能手工伪造 `validation`、`verdict`、`deployment_ready` 或 `execution_surface`。

ASR 至少检查：

- 音频能够被 wrapper 读取。
- 输出包含可评测的 transcription text。
- `language` 只有在模型工具 schema 声明时才发送。
- 多条样本的 key、文本投影和 JSONL 结构一致。

VAD 至少检查：

- 输出的 speech segments 使用明确的秒或毫秒约定。
- 起止时间有限、非负且不超过音频时长。
- frame scores 或等价置信度结构符合模型 contract。
- 包含有声和静音样本，静音样本不会被强行生成语音段。

通过条件：`spec_validation`、`fixture_manifest`、`build_env_result`、`weights_manifest`、`validation`、`verdict`、`deployment_ready` 和 `artifact_manifest` 全部成功，且模型目录可以被后续审批读取。任何失败都要修复后从失败单元继续，不能直接进入审批。

## 3. Approve：审计和显式批准分成两个 run

先审计：

```text
/sure_approve model_dir=<completed-model-dir>
```

检查 `producer_contract_report.json`、`integrity_report.json`、`repair_plan.json`、`approval_manifest.json`、`runtime_verification.json` 和 `review_packet.json`。确认候选目录、模型核心文件、运行时锁、镜像 digest 和验证结果都与 Onboard 输出一致。

审计通过后，不能由 agent 猜测批准决定。只有拿到明确的 `approve` 或 `reject` 决定，才能启动第二个 run：

```text
/sure_approve mode=approve \
  review_manifest=<review-packet.json> \
  decision=approve
```

批准通过后必须存在 `approval_ready.json`，且 published model 位于 site policy 配置的 approved models root。若用户选择 reject，流程也算正确终止，但不得继续 `/sure_infer`。

## 4. Infer：先 smoke，再完整推理，再检查可恢复性

使用 approved model 的精确目录名和 canonical 数据集路径：

```text
/sure_infer model=<approved-model> \
  datasets=<dataset-path> \
  execution=local device=cpu max_samples=10 \
  protocol=standard_system
```

Smoke run 必须检查：

- `eval_input_resolved.json` 中的模型、数据集、设备和 execution path 正确。
- `execution_surface.json` 由标准 `infer_entrypoint.py` 生成，路径和 sha256 正确。
- `execution_result.json` 成功，失败阶段为空。
- MCP server command、working directory、image digest、Harness runtime 和 Model runtime 与 approved binding 一致。
- `prediction_generation_status.json` 记录实际 tool name、参数 key、样本数和响应状态。
- `protocol.yaml` 只记录推理协议和来源，不混入评测分数。
- `validation_payload.json` 的 `is_valid=true`，预测和参考 key 完整对齐。

Smoke 通过后运行完整数据集。完整 run 省略 `max_samples` 或设为 `0`：

```text
/sure_infer model=<approved-model> \
  datasets=<dataset-path> \
  execution=local device=cpu protocol=standard_system
```

完整 run 必须覆盖数据集的全部样本，不能把 smoke 预测当作完整预测。ASR 逐条检查 `key<TAB>text` 投影、JSONL 原始响应、文本换行归一化和语言参数；VAD 逐条检查 speech segments、frame scores、音频时长边界、静音样本和空输出。模型目录在推理期间必须保持只读，推理前后的核心文件 digest 必须相同。

如果 smoke 或完整推理失败，读取 `execution_result.json`、stdout/stderr 日志和 `prediction_generation_status.json`，分类失败原因。不要手工删除半成品或伪造成功状态；使用：

```text
/sure_resume <run-id>
```

恢复后确认已完成的样本没有被重复调用，失败状态没有被覆盖，最终产物仍能通过 validation 和 terminal gate。

## 5. Eval：只复用预测，不能重新推理

ASR 使用与数据集语言匹配的指标，例如：

```text
/sure_eval model=<approved-model> \
  datasets=<dataset-name>__<version> \
  source=<infer-run-id> metrics=cer
```

VAD 至少覆盖项目要求的五项指标：

```text
/sure_eval model=<approved-model> \
  datasets=<dataset-name>__<version> \
  source=<infer-run-id> \
  metrics=f1,p_fa,p_miss,dcf_nist,auc_roc
```

评测前确认 source 是本次完整 Infer bundle，数据集集合完全一致。评测阶段禁止启动模型服务、调用 MCP、修改 predictions、替换 reference root 或复用旧分数。

检查 `prediction_source_resolved.json` 和 `eval_run_report.json`：

- `evaluation_only=true`。
- `inference_executed=false`。
- `old_evaluation_reused=false`。
- source model fingerprint、protocol、数据集 digest、预测 sha256 全部对应本次 Infer bundle。
- `validation_payload.is_valid=true`。
- `pipeline_ids` 是实际执行的 pipeline，而不是 agent 猜的名称。
- `report.jsonl`、`report_snapshot.md` 和 `evaluation_runs/<batch>` 已持久化，重复同一身份是幂等操作。

最后完成 `/sure_eval` 的 assessment、extract_lessons 和 run_report 单元。指标异常时写明异常、可能原因和用户确认，不能改基线或改指标方向来消除异常。

## 6. Coding 验收：把代码 diff 和流程证据对上

流程完成后，agent 要回答以下问题：

1. 修改的代码是否真的被本次推理入口加载？
2. MCP 参数是否来自当前 tool schema，而不是旧配置或目录名？
3. 模型身份、挂载目录、镜像 digest、运行时和协议是否在每个产物中一致？
4. smoke、完整推理和恢复是否保持样本 key 覆盖且没有意外重复调用？
5. ASR 的文本预测或 VAD 的时间段是否经过 validation，并由评测引擎实际消费？
6. 指标变化能否由代码 diff、数据集变化或协议变化解释？
7. 失败时系统是否保留失败证据，而不是生成看似成功的 report？

使用相同模型、相同数据集版本、相同 protocol 和相同 sample keys 与上一条基线比较。记录模型 fingerprint、image digest、pipeline IDs、样本覆盖率、每项指标和差异解释。没有完整证据时，结论只能是 `incomplete`，不能写成通过。

## 7. 辅助检查

流程审查之外，运行代码静态检查：

```bash
npm run check
```

只有流程证据、辅助测试和静态检查都符合要求，agent 才能把 coding review 标记为 `passed`。真实模型 wrapper、音频预处理、归一化、阈值或运行时发生变化时，还必须在固定的小样本 ASR/VAD 数据集上执行一次真实模型验收，并把结果与基线一起提交。
