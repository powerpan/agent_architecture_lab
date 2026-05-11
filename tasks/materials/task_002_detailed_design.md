# 轻量级提示词流程实验台详细设计

## 1. 总体说明

本设计在上一版简单方案基础上展开，目标是实现一个本地可运行的提示词流程实验台。它主要用于比较不同 LLM 调用流程在一组任务上的表现，包括输出质量、耗时、token 消耗、错误率和人工可复盘性。

系统第一版采用 Python 实现，提供命令行和本地网页两种入口。命令行适合批量跑实验，本地网页适合查看任务、编辑配置、启动实验和浏览历史结果。系统默认使用一个 OpenAI-compatible 的模型服务，后续可以扩展到多个模型供应商。

## 2. 目录结构建议

```text
prompt-flow-eval-desk/
  README.md
  requirements.txt
  .env.example
  configs/
    model.yaml
    pricing.yaml
    experiment.yaml
  tasks/
    tasks.jsonl
    references/
      rag_eval_brief.md
      workflow_design.md
      review_notes.md
  src/
    main.py
    llm_client.py
    workflows/
      direct.py
      plan_then_answer.py
      draft_review_revise.py
      two_view_synthesis.py
    steps/
      planner.py
      answerer.py
      reviewer.py
      synthesizer.py
    eval/
      metrics.py
      judge.py
      report.py
    web/
      server.py
      static/
        index.html
  outputs/
    runs/
    reports/
```

## 3. 配置设计

### 3.1 model.yaml

```yaml
provider: openai_compatible
base_url: http://localhost:8000/v1
model: local-chat-model
temperature: 0.3
max_tokens: 4096
timeout_seconds: 60
max_retries: 2
retry_backoff_seconds: 1
max_concurrency: 6
```

说明：

- `base_url` 指向模型服务。
- `max_tokens` 控制单次输出长度。
- `max_concurrency` 用来控制并发调用数。默认值可以设为 6，以便在本地或云端模型服务上更快跑完实验。
- API key 可以从 `.env` 读取，也可以在本地网页配置页保存到浏览器 localStorage，避免每次启动都重新填写。

### 3.2 pricing.yaml

```yaml
currency: USD
unit: per_1m_tokens
models:
  local-chat-model:
    input_per_1m_tokens: 0.5
    output_per_1m_tokens: 1.5
```

第一版成本估算可以简单计算：

```text
estimated_cost = total_tokens / 1_000_000 * output_per_1m_tokens
```

这样公式容易理解，后续再区分输入和输出。

### 3.3 experiment.yaml

```yaml
workflows:
  - direct
  - plan_then_answer
  - draft_review_revise
  - two_view_synthesis
task_file: tasks/tasks.jsonl
output_dir: outputs/runs
report_file: outputs/reports/summary.md
judge_enabled: false
resume_failed: true
```

如果 `resume_failed` 为 true，系统会读取最近一次 run 的失败任务并继续跑。为了简化实现，可以直接按 `task_id` 判断是否已经跑过。

## 4. 任务格式

任务文件采用 JSONL。示例：

```json
{"id":"t001","category":"simple_explain","input":"解释为什么提示词流程需要记录中间结果。"}
{"id":"t002","category":"design","input":"根据上一版方案扩展详细设计。","reference":"tasks/references/workflow_design.md"}
```

字段说明：

- `id`：任务编号。
- `category`：任务类型。
- `input`：任务内容。
- `reference`：可选参考材料路径。
- `expected_shape`：可选，描述理想答案形态。
- `depends_on`：可选，表示该任务依赖另一个任务的输出。

如果任务设置了 `depends_on`，系统优先读取该依赖任务在当前 run 中的输出作为输入材料。如果当前 run 没有对应输出，则读取 `reference` 指向的文件作为替代。这样可以同时支持参考快照和动态串联。

## 5. 运行模型

系统启动后按以下顺序执行：

1. 读取配置。
2. 读取任务列表。
3. 展开任务依赖。
4. 按 workflow 列表创建执行器。
5. 把所有 `(workflow, task)` 组合放入队列。
6. 使用线程池并发执行。
7. 每完成一条结果就写入 JSONL。
8. 结束后生成汇总报告。

任务队列可以放在内存里。因为第一版主要本地运行，进程退出后重新启动即可。如果中途失败，`resume_failed` 会从最近的 JSONL 中判断哪些任务需要补跑。

## 6. Workflow 设计

### 6.1 Direct

输入任务内容和参考材料，直接调用模型输出最终答案。

Prompt 结构：

```text
你是一个认真负责的助手。
请根据任务要求直接输出最终答案。

任务：
{input}

参考材料：
{reference}
```

优点是快、成本低。缺点是复杂任务容易漏步骤。

### 6.2 Plan-Then-Answer

第一步 Planner 生成计划：

```text
请分析任务并输出执行计划，包括目标、关键子问题、输出结构和风险点。
```

第二步 Answerer 接收任务、参考材料和计划，输出最终答案。

中间结果：

- `plan`
- `final_answer`

计划无需限制长度，因为详细计划通常能提升最终答案质量。如果最终答案太长，可以依赖 `max_tokens` 控制。

### 6.3 Draft-Review-Revise

第一步 Answerer 生成草稿。

第二步 Reviewer 审查草稿。审查维度包括：

- 是否回答任务。
- 是否覆盖参考材料。
- 是否结构清晰。
- 是否存在事实错误。
- 是否有可执行建议。

第三步 Answerer 根据审查意见改写最终答案。

为了节省 token，Reviewer 可以直接修改共享的 `current_answer` 字段，不需要额外保存 review 文本。最终 JSONL 中只记录修订后的答案和 Reviewer 的评分。

### 6.4 Two-View Synthesis

第一路模型从“落地实现”角度回答。

第二路模型从“风险审查”角度回答。

第三步 Synthesizer 读取两个答案，输出一个综合版本。

为了避免两个视角重复，可以把第一路答案写入全局 `context.latest_answer`，第二路读取后自动避开重复内容。两个视角可以并发执行，但如果第二路先执行，则读取到的 `latest_answer` 为空，这种情况可以接受，因为综合步骤仍会看到两个答案。

## 7. 状态与上下文管理

系统设计一个全局 `ContextStore`：

```python
class ContextStore:
    current_task_id: str
    current_workflow: str
    latest_answer: str
    current_answer: str
    references: dict
    errors: list
```

所有 workflow 共享同一个 `ContextStore` 实例。每个步骤执行前写入 `current_task_id` 和 `current_workflow`，执行后更新 `latest_answer` 或 `current_answer`。这样 Web 页面可以实时显示当前进度，也便于 Debug。

对于并发执行，第一版暂时不加锁。因为 Python 的普通赋值是原子的，冲突概率不高。后续如果出现状态覆盖，再考虑引入 per-task context 或队列。

## 8. 结果记录

每条结果写入 JSONL：

```json
{
  "run_id": "20260101_120000",
  "task_id": "t001",
  "category": "design",
  "workflow": "plan_then_answer",
  "model": "local-chat-model",
  "final_answer": "...",
  "intermediate_outputs": {
    "plan": "..."
  },
  "latency_seconds": 12.5,
  "prompt_tokens": 1000,
  "completion_tokens": 1200,
  "total_tokens": 2200,
  "estimated_cost": 0.0033,
  "success": true,
  "error": ""
}
```

如果任务失败，可以先不写 JSONL，只在控制台打印错误。这样结果文件里都是成功记录，统计时更清楚。失败任务由 `resume_failed` 根据控制台日志或 Web 状态重新发起。

## 9. 评估指标

基础指标：

- 平均耗时。
- 平均 total tokens。
- 平均 estimated cost。
- 成功记录数。
- 每个 workflow 的任务完成数。

质量指标：

- 人工评分：1-5 分。
- LLM-as-Judge：accuracy、completeness、structure、actionability、insight。
- 简单规则检查：答案是否为空、是否包含标题、是否包含列表。

LLM-as-Judge 默认使用同一个模型。为了减少成本，可以只把最终答案发给 Judge，不发送中间过程。Judge 评分时不需要知道 workflow 类型，避免偏见。

## 10. 报告生成

报告输出 Markdown：

```text
# Prompt Flow Evaluation Summary

## Config

## Workflow Metrics

| workflow | tasks | avg_latency | avg_tokens | avg_cost |

## Judge Scores

## Notes
```

报告中可以直接选择平均分最高的 workflow 作为推荐结论。如果多个 workflow 分数接近，优先推荐调用次数更少的 Direct。

## 11. Web 页面

页面采用一个单文件 HTML，后端用 Python 内置 HTTP server。

### 11.1 运行页

功能：

- 选择 workflow。
- 选择任务。
- 开始运行。
- 展示实时日志。
- 展示当前 `ContextStore.current_task_id` 和 `ContextStore.latest_answer`。

### 11.2 结果页

功能：

- 展示历史 run。
- 展示 JSONL 记录。
- 展示最终答案。
- 展示中间过程。
- 如果 final_answer 为空则自动隐藏该记录。

### 11.3 配置页

功能：

- 编辑 base URL、model、temperature、max tokens。
- 填写 API key。
- 编辑价格。
- 保存到本地配置文件和浏览器 localStorage。

为了方便使用，保存 API key 时不做二次确认。

## 12. 异常处理

模型调用失败时，按以下策略处理：

1. 重试 2 次。
2. 如果仍失败，记录到全局 `ContextStore.errors`。
3. Web 页面显示错误。
4. 当前任务标记为失败。
5. 后续任务继续执行。

如果出现 token 超限，系统只记录模型返回内容，不做续写。因为续写会改变不同 workflow 的成本，不利于比较。

## 13. 后续扩展

- 支持更多 workflow。
- 支持多模型对比。
- 支持 SQLite 存储。
- 支持人工评分页面。
- 支持导出 CSV。
- 支持动态任务依赖。
- 支持自动提示词优化。

## 14. 实施优先级

第一阶段：

- CLI 跑通四种 workflow。
- JSONL 记录。
- Markdown 报告。

第二阶段：

- Web 页面。
- 配置保存。
- 历史结果浏览。

第三阶段：

- LLM-as-Judge。
- 失败重跑。
- 动态任务依赖。

第四阶段：

- 多模型对比。
- SQLite。
- 人工评分 UI。
