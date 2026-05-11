# Agent Architecture Lab

Agent Architecture Lab 是一个多 Agent 架构对比实验项目。它不是面向某个具体业务场景的应用，而是一个可复现实验平台：用同一批任务比较不同 Agent 架构在输出质量、成本、延迟和稳定性上的差异。

第一版使用 Python 实现，LLM 后端使用 DeepSeek API，并通过 OpenAI-compatible SDK 调用。项目暂不引入 LangChain、AutoGen、CrewAI 等重型框架，核心目标是保留足够清晰的轻量编排逻辑，方便观察不同架构本身带来的差异。

## 为什么研究多 Agent 架构

多 Agent 系统经常被用来拆分复杂任务，但 Agent 数量增加并不必然带来更好的结果。实际效果通常受任务拆解方式、状态共享方式、审查机制、模型调用成本和错误传播路径影响。

本项目希望把这些因素放到同一套任务基准下做可复现实验。每次运行都会记录中间产物、token、耗时、成本估算和错误信息，便于后续做结构化分析。

## 支持的架构

### single

一个 Agent 直接完成任务。

```text
Task -> SingleAgent -> Final Answer
```

### planner_executor

Planner 先拆解任务，Executor 根据计划完成任务。

```text
Task -> Planner -> Executor -> Final Answer
```

### planner_executor_reviewer

Planner 拆解任务，Executor 生成草稿，Reviewer 审查并提出修改意见，Executor 根据审查意见生成最终答案。

```text
Task -> Planner -> Executor Draft -> Reviewer -> Executor Final -> Final Answer
```

### debate

两个 Agent 分别给出方案，一个 Judge 进行综合。

```text
Task -> Debater A + Debater B -> Judge -> Final Answer
```

## 配置 DeepSeek API key

API key 必须从环境变量 `DEEPSEEK_API_KEY` 读取，不能写入代码或配置文件。

```bash
cd /Users/ericpan/game_project/agent-architecture-lab
cp .env.example .env
```

然后编辑 `.env`：

```text
DEEPSEEK_API_KEY=your_real_key_here
```

`.gitignore` 已经忽略 `.env`。

## 安装依赖

```bash
cd /Users/ericpan/game_project/agent-architecture-lab
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 运行实验

运行配置文件中的全部架构：

```bash
cd /Users/ericpan/game_project/agent-architecture-lab
python -m src.main --config configs/experiments.yaml
```

只运行单 Agent 架构：

```bash
cd /Users/ericpan/game_project/agent-architecture-lab
python -m src.main --architecture single --task-file tasks/sample_tasks.jsonl
```

只运行 Planner + Executor 架构：

```bash
cd /Users/ericpan/game_project/agent-architecture-lab
python -m src.main --architecture planner_executor --task-file tasks/sample_tasks.jsonl
```

启用可选 LLM-as-Judge 评分：

```bash
cd /Users/ericpan/game_project/agent-architecture-lab
python -m src.main --config configs/experiments.yaml --judge
```

## 启动配置页面

项目内置一个轻量本地页面，用于查看任务、历史运行记录，并填写模型、实验、成本和本地 API key 配置。

```bash
cd /Users/ericpan/game_project/agent-architecture-lab
source .venv/bin/activate
python -m src.web.server --host 127.0.0.1 --port 8765
```

也可以直接运行项目里的启动脚本。脚本会优先使用本地 `.venv`，如果依赖不存在会先安装依赖：

```bash
cd /Users/ericpan/game_project/agent-architecture-lab
./start-ui.command
```

然后打开：

```text
http://127.0.0.1:8765
```

页面保存配置前会先生成 YAML 预览。`DEEPSEEK_API_KEY` 只会写入本地 `.env`，不会写入 YAML、代码或结果文件。

页面也支持直接启动实验：

- 在“运行实验”区域勾选要比较的架构。
- 勾选要运行的任务。
- 可选开启 LLM-as-Judge。
- 点击“启动实验”后，后端会串行运行任务，并在页面显示进度、结果 JSONL 路径和 summary 报告路径。
- 顶部导航分为“启动台 / 结果 / 配置”。启动台负责选择架构和任务，点击历史运行条目会进入结果页查看 JSONL 详情，配置页负责模型、实验、成本和密钥配置。
- 结果页会按 Markdown 渲染 `final_answer`，并把“结果文件”和“过程文件”拆成上下同级栏目。点击某个结果文件后，下方只显示该结果对应的 `intermediate_outputs` 过程文件，例如 Planner 计划、Reviewer 意见和 Debater 方案。

为了避免触发接口限流，Web 启动入口同一时间只允许一个实验任务运行，且运行器按 `max_concurrency: 1` 串行执行。

## 输出文件

每次实验会生成一个 run id，并把结果写入：

```text
outputs/runs/<run_id>.jsonl
```

每条 JSONL 记录包含：

- `run_id`
- `task_id`
- `category`
- `architecture`
- `model`
- `final_answer`
- `intermediate_outputs`
- `latency_seconds`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `estimated_cost`
- `num_model_calls`
- `success`
- `error`

如果启用了 `--judge`，还会追加 `judge_eval`、`judge_usage`、`judge_estimated_cost` 等字段。

## 理解 summary.md

实验结束后会生成：

```text
outputs/reports/summary.md
```

报告会按架构聚合：

- 运行任务数
- 成功数量
- 错误数量
- 平均耗时
- 平均 token
- 平均成本

第一版的结论区只是占位。它不会自动判断哪个架构最好，只提供基础统计，方便你结合具体任务输出继续分析。

## 配置说明

模型配置在：

```text
configs/model.yaml
```

成本配置在：

```text
configs/pricing.yaml
```

其中 token 单价不写死在代码中。当前已按 DeepSeek 配置为 CNY / 百万 tokens，并同时记录缓存命中输入价、缓存未命中输入价和输出价。由于当前实验日志还没有缓存命中 token 明细，`estimated_cost` 默认按缓存未命中输入价估算。

实验配置在：

```text
configs/experiments.yaml
```

可以控制要运行的架构、任务文件和输出目录。默认 `max_concurrency: 1`，当前运行器也是串行执行，并且 `configs/model.yaml` 中设置了 `min_request_interval_seconds`，用于避免连续请求太密。

## 后续扩展方向

- blackboard 共享黑板架构
- router-specialist 专家路由架构
- memory-based agent
- human evaluation UI
- 多模型对比
- 更严格的任务基准集
