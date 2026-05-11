# 提示词流程实验台详细设计审查报告

## 1. 总体判断

上一版详细设计已经把配置、任务、流程、记录、报告和 Web 页面都展开了，整体上可以支撑一个本地实验工具的第一版。但设计中存在多处会影响实验可信度、数据完整性和运行稳定性的风险。最大的问题不是模块缺失，而是几个关键取舍没有说清楚：到底要做公平的离线比较，还是要做真实的动态串联工作流；到底要显式记录每一步，还是用共享上下文省 token；到底要优先稳定，还是优先跑得快。

如果这些问题不处理，平台可能能跑出结果，但结果不一定可信。尤其是动态依赖、共享 ContextStore、并发执行和失败记录这几处，会让不同 workflow 的输入不一致，也会让错误被隐藏。

## 2. 任务依赖与比较公平性问题

### 2.1 问题描述

详细设计在任务格式中加入了 `depends_on`，并规定“如果当前 run 中有依赖任务输出，就优先使用该输出；否则使用 reference 文件”。这会让同一个任务在不同 workflow、不同运行顺序下看到不同输入。

例如 `t002` 依赖 `t001`：

- Direct 在 `t001` 输出较短，`t002` 看到的是短材料。
- Plan-Then-Answer 在 `t001` 输出较长，`t002` 看到的是长材料。
- 如果某次 run 中 `t001` 失败，`t002` 又会退回读取 reference 文件。

这样任务二的输入已经不一样，后续比较 workflow 的质量、成本和耗时就不再公平。

### 2.2 风险

- 实验结果混入上游输出质量差异。
- 某个 workflow 因为上游产物更长而承担更多 token 成本。
- 失败回退到 reference 后，结果看似成功，但实际测试条件已经改变。
- summary 报告无法解释输入差异。

### 2.3 建议

把任务模式拆成两类：

1. **Snapshot Mode**：所有任务只使用预先准备好的上一版材料，适合架构横向比较。
2. **Chain Mode**：后续任务使用前序任务的真实输出，适合研究工作流传播效应。

两类模式不能混在一个 summary 里统计。第一版建议默认只支持 Snapshot Mode，后续再单独增加 Chain Mode。

## 3. 全局 ContextStore 的状态污染问题

### 3.1 问题描述

设计中所有 workflow 共享一个全局 `ContextStore`，里面包含 `current_task_id`、`latest_answer`、`current_answer`、`references` 和 `errors`。同时设计又允许线程池并发执行，并且暂时不加锁。

这会带来明显状态污染：

- A 任务执行时写入 `current_answer`。
- B 任务执行时覆盖 `current_answer`。
- Reviewer 读取到的可能不是自己任务的草稿。
- Web 页面显示的 `latest_answer` 可能来自另一个 workflow。
- Two-View Synthesis 的第二路答案可能读取到其他任务的 `latest_answer`。

### 3.2 风险

- 输出内容串任务。
- 中间过程无法复盘。
- 偶发 bug 难以复现。
- 并发数越高，污染概率越大。

### 3.3 建议

第一版不要使用全局可变 ContextStore 承载业务内容。可以保留只读或展示型状态，例如当前进度，但每个 `(workflow, task)` 必须有独立上下文对象：

```python
RunContext(run_id, workflow, task_id, inputs, intermediate_outputs)
```

所有步骤只能写自己的 `RunContext`，不能读写全局 `latest_answer`。如果需要页面实时展示，可以由事件队列推送快照，而不是让页面直接读取共享对象。

## 4. 并发与限流问题

### 4.1 问题描述

`model.yaml` 默认 `max_concurrency: 6`，执行流程使用线程池并发跑所有 `(workflow, task)` 组合。但设计没有全局限流、供应商限速、请求间隔、队列退避，也没有说明并发对成本和稳定性的影响。

### 4.2 风险

- 本地模型服务可能被打满，导致延迟统计失真。
- 云端模型服务可能触发 rate limit。
- 失败重试叠加并发后，会形成请求风暴。
- 不同 workflow 的等待时间受队列位置影响，不再可比。

### 4.3 建议

第一版默认并发应为 1。后续如果增加并发，需要至少具备：

- 全局 semaphore。
- 每模型请求间隔。
- 指数退避。
- 每任务超时。
- 重试次数计入结果。
- rate limit 错误单独分类。

## 5. 成本估算公式错误

### 5.1 问题描述

详细设计中的成本公式为：

```text
estimated_cost = total_tokens / 1_000_000 * output_per_1m_tokens
```

这个公式把输入 token 和输出 token 都按输出单价计算。多数模型的输入和输出价格不同，输出通常更贵。这样会导致成本估算偏差。

### 5.2 风险

- prompt 很长的 workflow 可能被高估或低估。
- Draft-Review-Revise 这类多轮流程的真实成本不清楚。
- 决策者可能因为错误成本选择错误 workflow。

### 5.3 建议

至少拆成：

```text
input_cost = prompt_tokens / 1_000_000 * input_price
output_cost = completion_tokens / 1_000_000 * output_price
estimated_cost = input_cost + output_cost
```

Judge 成本也应单独记录，并在报告里说明是否计入总成本。

## 6. 失败记录被隐藏

### 6.1 问题描述

设计中写到“如果任务失败，可以先不写 JSONL，只在控制台打印错误”。这个做法会让结果文件只包含成功记录。

### 6.2 风险

- 成功率被虚高。
- summary 报告无法统计失败数量。
- 失败任务的 prompt、workflow、错误类型丢失。
- `resume_failed` 依赖控制台日志，不可靠。

### 6.3 建议

失败也必须写入 JSONL，`success=false`，并记录：

- `error`
- `error_type`
- `retry_count`
- `latency_seconds`
- `prompt_tokens`，如果可获得
- `intermediate_outputs`，保留失败前步骤

## 7. 中间过程记录不完整

### 7.1 问题描述

Draft-Review-Revise 中，Reviewer 被允许直接修改共享 `current_answer`，最终 JSONL 中只记录修订后的答案和评分，不保存 review 文本。

### 7.2 风险

- 无法判断 Reviewer 是否真的发现问题。
- 无法复盘最终答案变化。
- 如果 Reviewer 改错内容，无法定位责任。
- 多 Agent 流程的价值被隐藏。

### 7.3 建议

中间过程至少保存：

- `draft`
- `review`
- `revised_answer`
- 每一步 token 和耗时
- 每一步 finish reason

Reviewer 不应该直接改共享答案，而是输出审查意见，由 Answerer 根据审查意见生成修订版。

## 8. API key 与本地安全问题

### 8.1 问题描述

设计允许 API key 保存到浏览器 localStorage，并且保存时不做二次确认。

### 8.2 风险

- localStorage 容易被页面脚本读取。
- 如果本地页面后续引入第三方脚本，key 有泄露风险。
- 配置导出或截图时可能暴露 key。

### 8.3 建议

API key 只读环境变量或本地 `.env`。Web 页面可以提供写入 `.env` 的能力，但必须：

- 不回显完整 key。
- 不写入 YAML。
- 不写入结果文件。
- 保存前提示将写入本地文件。

## 9. Judge 设计不足

### 9.1 问题描述

LLM-as-Judge 只看最终答案，不看任务参考材料和中间过程。它使用同一个模型评分，也没有说明 rubric 的具体标准。

### 9.2 风险

- Judge 可能偏向更长、更像报告的答案。
- 无法判断答案是否忠实于参考材料。
- 不同 workflow 的中间过程质量无法评价。
- 同模型自评可能放大模型偏好。

### 9.3 建议

Judge 输入至少包含：

- 原始任务。
- 上一版材料或 reference。
- 最终答案。
- 明确评分 rubric。

评分结果应保存原始输出，解析失败也要记录。

## 10. Web 页面结果过滤问题

### 10.1 问题描述

结果页设计中提到“如果 final_answer 为空则自动隐藏该记录”。这会隐藏失败、截断或无输出的问题。

### 10.2 风险

- 用户只看到成功案例。
- 失败率无法从页面感知。
- 空答案和异常答案无法排查。

### 10.3 建议

结果页必须显示所有记录。失败记录以错误状态展示。空 final_answer 应显示错误、调用详情和中间过程。

## 11. 最重要的取舍问题

本设计中最模糊、也最值得单独判断的问题是：

**第一版应该坚持 Snapshot Mode，只用上一版材料做公平横向比较，还是应该尽早加入 Chain Mode，让后续任务读取前序真实输出，以更贴近真实工作流？**

这个问题有明显两面性：

- Snapshot Mode 更公平、可复现、适合比较 workflow 本身。
- Chain Mode 更贴近真实连续工作，但会把上游输出质量、长度和失败传播混入结果。
- Snapshot Mode 可能低估审查流程对坏草稿的修复能力。
- Chain Mode 可能让结果更真实，却更难解释。

如果产品目标是先比较流程本身，建议第一版只做 Snapshot Mode。如果目标是研究长链工作流可靠性，可以把 Chain Mode 做成独立实验类型，但不能和 Snapshot Mode 的结果混合统计。

## 12. 修复优先级

| 优先级 | 问题 | 建议 |
|---|---|---|
| P0 | 动态依赖影响公平性 | 默认禁用 `depends_on` 动态读取，区分 Snapshot 和 Chain |
| P0 | 全局 ContextStore 状态污染 | 改为 per-task RunContext |
| P0 | 失败不写 JSONL | 失败也必须写入结果 |
| P1 | 成本公式错误 | 拆分输入和输出价格 |
| P1 | 并发无速率限制 | 默认串行，后续再加限流 |
| P1 | Reviewer 直接改共享答案 | 保存 draft/review/revised_answer |
| P2 | API key localStorage | 改为环境变量或本地 .env |
| P2 | Judge 输入不足 | 增加 reference 和 rubric |
