from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.architectures.debate import DebateArchitecture
from src.architectures.planner_executor import PlannerExecutorArchitecture
from src.architectures.planner_executor_reviewer import PlannerExecutorReviewerArchitecture
from src.architectures.single import SingleArchitecture
from src.evaluation.cost import estimate_cost
from src.evaluation.judge_eval import evaluate_with_judge
from src.evaluation.report import generate_summary_report
from src.llm.deepseek_client import DeepSeekClient
from src.storage.run_logger import RunLogger


ARCHITECTURE_REGISTRY = {
    "single": SingleArchitecture,
    "planner_executor": PlannerExecutorArchitecture,
    "planner_executor_reviewer": PlannerExecutorReviewerArchitecture,
    "debate": DebateArchitecture,
}

ProgressCallback = Callable[[Dict[str, Any]], None]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Agent Architecture Lab experiments.")
    parser.add_argument("--config", default=None, help="Experiment config yaml path.")
    parser.add_argument(
        "--architecture",
        choices=sorted(ARCHITECTURE_REGISTRY.keys()),
        default=None,
        help="Run one architecture and override configs/experiments.yaml architectures.",
    )
    parser.add_argument("--task-file", default=None, help="JSONL task file path.")
    parser.add_argument("--model-config", default=None, help="Model config yaml path.")
    parser.add_argument("--pricing-config", default=None, help="Pricing config yaml path.")
    parser.add_argument("--judge", action="store_true", help="Enable optional LLM-as-Judge scoring.")
    return parser.parse_args()


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def load_yaml(path: str) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("Missing dependency: pyyaml. Run `pip install -r requirements.txt`.") from exc

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def load_tasks(path: str) -> List[Dict[str, Any]]:
    task_path = Path(path)
    if not task_path.exists():
        raise FileNotFoundError(f"Task file not found: {task_path}")
    task_path = task_path.resolve()

    tasks: List[Dict[str, Any]] = []
    with task_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                task = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {task_path}:{line_number}: {exc}") from exc
            if "id" not in task or "input" not in task:
                raise ValueError(f"Task at {task_path}:{line_number} must include `id` and `input`.")
            material_file = str(task.get("material_file") or "").strip()
            if material_file:
                material_path = resolve_material_path(material_file, task_path)
                material_content = material_path.read_text(encoding="utf-8")
                task["material_file"] = material_file
                task["material_content"] = material_content
                task["material_sha256"] = hashlib.sha256(material_content.encode("utf-8")).hexdigest()
            tasks.append(task)
    return tasks


def resolve_material_path(material_file: str, task_path: Path) -> Path:
    material_path = Path(material_file)
    candidates = (
        [material_path]
        if material_path.is_absolute()
        else [
            Path.cwd() / material_path,
            task_path.parent / material_path,
            task_path.parent.parent / material_path,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"Material file not found: {material_file}. Searched: {searched}")


def resolve_runtime_config(args: argparse.Namespace) -> Dict[str, Any]:
    default_experiment_path = "configs/experiments.yaml"
    experiment_config: Dict[str, Any] = {}
    if args.config:
        experiment_config = load_yaml(args.config)
    elif Path(default_experiment_path).exists():
        experiment_config = load_yaml(default_experiment_path)

    architectures = (
        [args.architecture]
        if args.architecture
        else experiment_config.get("architectures", list(ARCHITECTURE_REGISTRY.keys()))
    )
    unknown = [name for name in architectures if name not in ARCHITECTURE_REGISTRY]
    if unknown:
        raise ValueError(f"Unknown architecture(s): {', '.join(unknown)}")

    return {
        "architectures": architectures,
        "max_concurrency": int(experiment_config.get("max_concurrency", 1)),
        "task_file": args.task_file or experiment_config.get("task_file", "tasks/sample_tasks.jsonl"),
        "output_dir": experiment_config.get("output_dir", "outputs/runs"),
        "model_config": args.model_config or experiment_config.get("model_config", "configs/model.yaml"),
        "pricing_config": args.pricing_config or experiment_config.get("pricing_config", "configs/pricing.yaml"),
        "report_file": experiment_config.get("report_file", "outputs/reports/summary.md"),
        "judge_enabled": args.judge,
    }


def build_error_record(
    run_id: str,
    task: Dict[str, Any],
    architecture: str,
    model: str,
    latency_seconds: float,
    error: Exception,
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "task_id": task.get("id"),
        "category": task.get("category", ""),
        "architecture": architecture,
        "model": model,
        "final_answer": "",
        "intermediate_outputs": {},
        "latency_seconds": round(latency_seconds, 3),
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost": 0.0,
        "num_model_calls": 0,
        "model_call_details": [],
        "hit_token_limit": False,
        "task_input": task.get("input", ""),
        "material_file": task.get("material_file", ""),
        "material_sha256": task.get("material_sha256", ""),
        "success": False,
        "error": str(error),
    }


def run_experiment(
    runtime_config: Dict[str, Any],
    model_config: Dict[str, Any],
    pricing_config: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    client = DeepSeekClient(model_config)
    logger = RunLogger(runtime_config["output_dir"])
    records: List[Dict[str, Any]] = []
    total_items = len(runtime_config["architectures"]) * len(tasks)
    completed_items = 0

    def notify(event: str, **payload: Any) -> None:
        if progress_callback:
            progress_callback(
                {
                    "event": event,
                    "run_id": logger.run_id,
                    "completed": completed_items,
                    "total": total_items,
                    **payload,
                }
            )

    notify("started", result_path=str(logger.output_path))

    for architecture_name in runtime_config["architectures"]:
        runner_cls = ARCHITECTURE_REGISTRY[architecture_name]
        runner = runner_cls(client)

        for task in tasks:
            notify("task_started", architecture=architecture_name, task_id=task.get("id"))
            started_at = time.perf_counter()
            try:
                architecture_result = runner.run(task)
                latency_seconds = time.perf_counter() - started_at
                prompt_tokens = architecture_result["prompt_tokens"]
                completion_tokens = architecture_result["completion_tokens"]
                total_tokens = architecture_result["total_tokens"]
                estimated_cost = estimate_cost(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    model=client.model,
                    pricing_config=pricing_config,
                )

                record: Dict[str, Any] = {
                    "run_id": logger.run_id,
                    "task_id": task.get("id"),
                    "category": task.get("category", ""),
                    "architecture": architecture_name,
                    "model": client.model,
                    "task_input": task.get("input", ""),
                    "material_file": task.get("material_file", ""),
                    "material_sha256": task.get("material_sha256", ""),
                    "final_answer": architecture_result["final_answer"],
                    "intermediate_outputs": architecture_result["intermediate_outputs"],
                    "latency_seconds": round(latency_seconds, 3),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "estimated_cost": estimated_cost,
                    "num_model_calls": architecture_result["num_model_calls"],
                    "model_call_details": architecture_result.get("model_call_details", []),
                    "hit_token_limit": architecture_result.get("hit_token_limit", False),
                    "success": True,
                    "error": "",
                }

                if runtime_config["judge_enabled"]:
                    try:
                        judge_eval, judge_usage = evaluate_with_judge(client, task, record["final_answer"])
                        record["judge_eval"] = judge_eval
                        record["judge_usage"] = judge_usage
                        record["judge_estimated_cost"] = estimate_cost(
                            prompt_tokens=judge_usage["prompt_tokens"],
                            completion_tokens=judge_usage["completion_tokens"],
                            model=client.model,
                            pricing_config=pricing_config,
                        )
                        record["judge_eval_error"] = ""
                    except Exception as judge_error:
                        record["judge_eval"] = None
                        record["judge_usage"] = {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                            "num_model_calls": 0,
                        }
                        record["judge_estimated_cost"] = 0.0
                        record["judge_eval_error"] = str(judge_error)

            except Exception as error:
                latency_seconds = time.perf_counter() - started_at
                record = build_error_record(
                    run_id=logger.run_id,
                    task=task,
                    architecture=architecture_name,
                    model=client.model,
                    latency_seconds=latency_seconds,
                    error=error,
                )

            logger.append(record)
            records.append(record)
            completed_items += 1
            notify(
                "task_finished",
                architecture=architecture_name,
                task_id=task.get("id"),
                success=record.get("success", False),
                error=record.get("error", ""),
                result_path=str(logger.output_path),
            )

    report_path = generate_summary_report(
        records=records,
        experiment_config=runtime_config,
        output_path=runtime_config["report_file"],
    )
    notify("completed", result_path=str(logger.output_path), report_path=str(report_path))
    return {
        "run_id": logger.run_id,
        "result_path": logger.output_path,
        "report_path": report_path,
        "records": records,
    }


def run() -> int:
    args = parse_args()
    load_dotenv_if_available()

    runtime_config = resolve_runtime_config(args)
    model_config = load_yaml(runtime_config["model_config"])
    pricing_config = load_yaml(runtime_config["pricing_config"])
    tasks = load_tasks(runtime_config["task_file"])

    print(f"tasks: {len(tasks)}")
    print(f"architectures: {', '.join(runtime_config['architectures'])}")
    if runtime_config["max_concurrency"] != 1:
        print("warning: this runner is sequential; max_concurrency is treated as 1.")

    def print_progress(event: Dict[str, Any]) -> None:
        if event["event"] == "started":
            print(f"run_id: {event['run_id']}")
        elif event["event"] == "task_started":
            print(f"[{event['architecture']}] running {event['task_id']}")

    result = run_experiment(
        runtime_config=runtime_config,
        model_config=model_config,
        pricing_config=pricing_config,
        tasks=tasks,
        progress_callback=print_progress,
    )

    print(f"results: {result['result_path']}")
    print(f"summary: {result['report_path']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        raise SystemExit(1)
