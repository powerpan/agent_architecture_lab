from __future__ import annotations

import argparse
import json
import os
import threading
import traceback
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import yaml

from src.main import ARCHITECTURE_REGISTRY, load_dotenv_if_available, load_tasks, load_yaml, run_experiment


ROOT_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
MODEL_CONFIG_PATH = ROOT_DIR / "configs" / "model.yaml"
PRICING_CONFIG_PATH = ROOT_DIR / "configs" / "pricing.yaml"
EXPERIMENTS_CONFIG_PATH = ROOT_DIR / "configs" / "experiments.yaml"
ENV_PATH = ROOT_DIR / ".env"
JOB_LOCK = threading.Lock()
CURRENT_JOB: Dict[str, Any] | None = None


class LabWebHandler(BaseHTTPRequestHandler):
    server_version = "AgentArchitectureLabWeb/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_static_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/api/state":
            self._send_json(build_state())
            return
        if parsed.path == "/api/job":
            self._send_json({"ok": True, "job": get_job_snapshot()})
            return
        if parsed.path == "/api/run-result":
            self._handle_run_result(parsed.query)
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/preview", "/api/save", "/api/start"}:
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        try:
            payload = self._read_json()
            if parsed.path == "/api/start":
                self._handle_start(payload)
                return

            model_config, pricing_config, experiments_config, errors = normalize_payload(payload)
            if errors:
                self._send_json({"ok": False, "errors": errors}, status=HTTPStatus.BAD_REQUEST)
                return

            if parsed.path == "/api/preview":
                self._send_json(
                    {
                        "ok": True,
                        "previews": {
                            "configs/model.yaml": dump_yaml(model_config),
                            "configs/pricing.yaml": dump_yaml(pricing_config),
                            "configs/experiments.yaml": dump_yaml(experiments_config),
                            ".env": build_env_preview(payload),
                        },
                    }
                )
                return

            if not payload.get("confirmed"):
                self._send_json(
                    {"ok": False, "errors": ["save requires confirmed=true"]},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            write_yaml(MODEL_CONFIG_PATH, model_config)
            write_yaml(PRICING_CONFIG_PATH, pricing_config)
            write_yaml(EXPERIMENTS_CONFIG_PATH, experiments_config)
            api_key = str(payload.get("api_key") or "").strip()
            if api_key:
                write_env_api_key(api_key)
            self._send_json({"ok": True, "state": build_state()})
        except Exception as exc:
            self._send_json({"ok": False, "errors": [str(exc)]}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)

    def _send_json(self, data: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"ok": False, "errors": [message]}, status=status)

    def _handle_start(self, payload: Dict[str, Any]) -> None:
        try:
            run_request = build_run_request(payload)
        except ValueError as exc:
            self._send_json({"ok": False, "errors": [str(exc)]}, status=HTTPStatus.BAD_REQUEST)
            return

        with JOB_LOCK:
            active = CURRENT_JOB and CURRENT_JOB.get("status") in {"queued", "running"}
            if active:
                self._send_json(
                    {"ok": False, "errors": ["已有实验正在运行，请等待结束后再启动。"], "job": CURRENT_JOB},
                    status=HTTPStatus.CONFLICT,
                )
                return

            job_id = f"web_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
            set_current_job_locked(
                {
                    "id": job_id,
                    "status": "queued",
                    "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "finished_at": "",
                    "architectures": run_request["runtime_config"]["architectures"],
                    "task_ids": [task["id"] for task in run_request["tasks"]],
                    "judge_enabled": run_request["runtime_config"]["judge_enabled"],
                    "completed": 0,
                    "total": len(run_request["runtime_config"]["architectures"]) * len(run_request["tasks"]),
                    "current": None,
                    "result_path": "",
                    "report_path": "",
                    "error": "",
                    "events": [],
                }
            )

        thread = threading.Thread(target=run_job, args=(job_id, run_request), daemon=True)
        thread.start()
        self._send_json({"ok": True, "job": get_job_snapshot()})

    def _handle_run_result(self, query: str) -> None:
        params = parse_qs(query)
        file_value = (params.get("file") or [""])[0]
        if not file_value:
            self._send_json({"ok": False, "errors": ["file is required"]}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            self._send_json({"ok": True, "result": read_run_result(file_value)})
        except Exception as exc:
            self._send_json({"ok": False, "errors": [str(exc)]}, status=HTTPStatus.BAD_REQUEST)


def get_job_snapshot() -> Dict[str, Any] | None:
    with JOB_LOCK:
        if CURRENT_JOB is None:
            return None
        return json.loads(json.dumps(CURRENT_JOB, ensure_ascii=False))


def set_current_job_locked(job: Dict[str, Any]) -> None:
    global CURRENT_JOB
    CURRENT_JOB = job


def update_job(job_id: str, **changes: Any) -> None:
    with JOB_LOCK:
        if CURRENT_JOB is None or CURRENT_JOB.get("id") != job_id:
            return
        CURRENT_JOB.update(changes)


def append_job_event(job_id: str, message: str) -> None:
    with JOB_LOCK:
        if CURRENT_JOB is None or CURRENT_JOB.get("id") != job_id:
            return
        events = CURRENT_JOB.setdefault("events", [])
        events.append({"time": datetime.now().strftime("%H:%M:%S"), "message": message})
        del events[:-80]


def build_run_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    load_dotenv_if_available()
    dotenv_key = read_dotenv_api_key_value()
    if not os.getenv("DEEPSEEK_API_KEY") and dotenv_key:
        os.environ["DEEPSEEK_API_KEY"] = dotenv_key
    if not read_env_status()["effective_has_deepseek_api_key"]:
        raise ValueError("DEEPSEEK_API_KEY 未配置，请先在“密钥”页填写并保存。")

    experiments_config = load_yaml(str(EXPERIMENTS_CONFIG_PATH))
    model_config = load_yaml(str(MODEL_CONFIG_PATH))
    pricing_config = load_yaml(str(PRICING_CONFIG_PATH))

    selected_architectures = payload.get("architectures") or experiments_config.get("architectures") or []
    if not isinstance(selected_architectures, list):
        raise ValueError("architectures must be a list")
    selected_architectures = [str(name) for name in selected_architectures]
    unknown_architectures = [name for name in selected_architectures if name not in ARCHITECTURE_REGISTRY]
    if unknown_architectures:
        raise ValueError(f"未知架构：{', '.join(unknown_architectures)}")
    if not selected_architectures:
        raise ValueError("请至少选择一个架构。")

    task_file = str(experiments_config.get("task_file") or "tasks/sample_tasks.jsonl")
    all_tasks = load_tasks(str(resolve_repo_path(task_file)))
    selected_task_ids = payload.get("task_ids") or [task["id"] for task in all_tasks]
    if not isinstance(selected_task_ids, list):
        raise ValueError("task_ids must be a list")
    selected_task_ids = [str(task_id) for task_id in selected_task_ids]
    if not selected_task_ids:
        raise ValueError("请至少选择一个任务。")

    task_by_id = {str(task["id"]): task for task in all_tasks}
    unknown_task_ids = [task_id for task_id in selected_task_ids if task_id not in task_by_id]
    if unknown_task_ids:
        raise ValueError(f"未知任务：{', '.join(unknown_task_ids)}")
    selected_tasks = [task_by_id[task_id] for task_id in selected_task_ids]

    runtime_config = {
        "architectures": selected_architectures,
        "max_concurrency": 1,
        "task_file": task_file,
        "output_dir": str(experiments_config.get("output_dir") or "outputs/runs"),
        "model_config": str(experiments_config.get("model_config") or "configs/model.yaml"),
        "pricing_config": str(experiments_config.get("pricing_config") or "configs/pricing.yaml"),
        "report_file": str(experiments_config.get("report_file") or "outputs/reports/summary.md"),
        "judge_enabled": bool(payload.get("judge_enabled")),
    }

    return {
        "runtime_config": runtime_config,
        "model_config": model_config,
        "pricing_config": pricing_config,
        "tasks": selected_tasks,
    }


def run_job(job_id: str, run_request: Dict[str, Any]) -> None:
    update_job(job_id, status="running")
    append_job_event(job_id, "实验开始，串行执行，max_concurrency=1。")

    def progress(event: Dict[str, Any]) -> None:
        if event["event"] == "started":
            update_job(job_id, result_path=relative_or_abs(event.get("result_path", "")))
            append_job_event(job_id, f"run_id: {event['run_id']}")
        elif event["event"] == "task_started":
            update_job(
                job_id,
                current={"architecture": event.get("architecture"), "task_id": event.get("task_id")},
                completed=event.get("completed", 0),
                total=event.get("total", 0),
            )
            append_job_event(job_id, f"[{event.get('architecture')}] 开始 {event.get('task_id')}")
        elif event["event"] == "task_finished":
            update_job(
                job_id,
                completed=event.get("completed", 0),
                total=event.get("total", 0),
                result_path=relative_or_abs(event.get("result_path", "")),
            )
            status_text = "成功" if event.get("success") else f"失败：{event.get('error')}"
            append_job_event(job_id, f"[{event.get('architecture')}] {event.get('task_id')} {status_text}")
        elif event["event"] == "completed":
            update_job(
                job_id,
                completed=event.get("total", 0),
                total=event.get("total", 0),
                result_path=relative_or_abs(event.get("result_path", "")),
                report_path=relative_or_abs(event.get("report_path", "")),
            )
            append_job_event(job_id, "实验完成。")

    try:
        result = run_experiment(
            runtime_config=run_request["runtime_config"],
            model_config=run_request["model_config"],
            pricing_config=run_request["pricing_config"],
            tasks=run_request["tasks"],
            progress_callback=progress,
        )
        update_job(
            job_id,
            status="completed",
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            completed=len(result["records"]),
            total=len(result["records"]),
            result_path=relative_or_abs(str(result["result_path"])),
            report_path=relative_or_abs(str(result["report_path"])),
            current=None,
        )
    except Exception as exc:
        update_job(
            job_id,
            status="failed",
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error=str(exc),
            current=None,
        )
        append_job_event(job_id, f"实验异常终止：{exc}")
        append_job_event(job_id, traceback.format_exc().splitlines()[-1])


def relative_or_abs(path_value: str) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except Exception:
        return path_value


def build_state() -> Dict[str, Any]:
    model_config = load_yaml(str(MODEL_CONFIG_PATH))
    pricing_config = load_yaml(str(PRICING_CONFIG_PATH))
    experiments_config = load_yaml(str(EXPERIMENTS_CONFIG_PATH))
    task_file = str(experiments_config.get("task_file") or "tasks/sample_tasks.jsonl")
    tasks, task_error = read_tasks_for_state(task_file)
    return {
        "ok": True,
        "paths": {
            "root": str(ROOT_DIR),
            "model_config": "configs/model.yaml",
            "pricing_config": "configs/pricing.yaml",
            "experiments_config": "configs/experiments.yaml",
            "env": ".env",
        },
        "allowed_architectures": list(ARCHITECTURE_REGISTRY.keys()),
        "configs": {
            "model": model_config,
            "pricing": pricing_config,
            "experiments": experiments_config,
        },
        "env": read_env_status(),
        "tasks": {
            "task_file": task_file,
            "count": len(tasks),
            "items": tasks,
            "error": task_error,
        },
        "runs": read_run_summaries(),
        "job": get_job_snapshot(),
    }


def read_tasks_for_state(task_file: str) -> Tuple[List[Dict[str, Any]], str]:
    try:
        task_path = resolve_repo_path(task_file)
        tasks = load_tasks(str(task_path))
        return [summarize_task_for_state(task) for task in tasks], ""
    except Exception as exc:
        return [], str(exc)


def summarize_task_for_state(task: Dict[str, Any]) -> Dict[str, Any]:
    summarized = {key: value for key, value in task.items() if key != "material_content"}
    if task.get("material_content"):
        summarized["material_chars"] = len(str(task.get("material_content") or ""))
    return summarized


def read_env_status() -> Dict[str, bool]:
    dotenv_has_key = bool(read_dotenv_api_key_value())
    return {
        "process_has_deepseek_api_key": bool(os.getenv("DEEPSEEK_API_KEY")),
        "dotenv_has_deepseek_api_key": dotenv_has_key,
        "effective_has_deepseek_api_key": bool(os.getenv("DEEPSEEK_API_KEY")) or dotenv_has_key,
    }


def read_dotenv_api_key_value() -> str:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("DEEPSEEK_API_KEY=") and stripped.split("=", 1)[1].strip():
                return stripped.split("=", 1)[1].strip()
    return ""


def read_run_summaries() -> List[Dict[str, Any]]:
    run_dir = ROOT_DIR / "outputs" / "runs"
    if not run_dir.exists():
        return []

    summaries: List[Dict[str, Any]] = []
    for path in sorted(run_dir.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)[:10]:
        records = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                stripped = line.strip()
                if stripped:
                    records.append(json.loads(stripped))
        success_count = sum(1 for record in records if record.get("success"))
        architectures = sorted({str(record.get("architecture")) for record in records if record.get("architecture")})
        summaries.append(
            {
                "file": str(path.relative_to(ROOT_DIR)),
                "run_id": path.stem,
                "records": len(records),
                "success": success_count,
                "errors": len(records) - success_count,
                "architectures": architectures,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return summaries


def read_run_result(file_value: str) -> Dict[str, Any]:
    result_path = resolve_repo_path(file_value)
    run_dir = (ROOT_DIR / "outputs" / "runs").resolve()
    if not result_path.is_file() or result_path.suffix != ".jsonl":
        raise ValueError("result file must be a JSONL file")
    if not result_path.resolve().is_relative_to(run_dir):
        raise ValueError("result file must be under outputs/runs")

    records: List[Dict[str, Any]] = []
    with result_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at line {line_number}: {exc}") from exc

    success_count = sum(1 for record in records if record.get("success"))
    architectures = sorted({str(record.get("architecture")) for record in records if record.get("architecture")})
    task_ids = sorted({str(record.get("task_id")) for record in records if record.get("task_id")})
    return {
        "file": str(result_path.relative_to(ROOT_DIR)),
        "run_id": result_path.stem,
        "records": records,
        "summary": {
            "record_count": len(records),
            "success_count": success_count,
            "error_count": len(records) - success_count,
            "architectures": architectures,
            "task_ids": task_ids,
            "total_tokens": sum(int(record.get("total_tokens") or 0) for record in records),
            "estimated_cost": round(sum(float(record.get("estimated_cost") or 0) for record in records), 8),
            "modified_at": datetime.fromtimestamp(result_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        },
    }


def normalize_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[str]]:
    errors: List[str] = []
    model_config = normalize_model_config(payload.get("model_config") or {}, errors)
    experiments_config = normalize_experiments_config(payload.get("experiments_config") or {}, errors)
    pricing_config = normalize_pricing_config(payload.get("pricing_config") or {}, model_config, errors)
    return model_config, pricing_config, experiments_config, errors


def normalize_model_config(raw: Dict[str, Any], errors: List[str]) -> Dict[str, Any]:
    config = load_yaml(str(MODEL_CONFIG_PATH)) if MODEL_CONFIG_PATH.exists() else {}
    provider = clean_string(raw.get("provider"), "provider", errors)
    base_url = clean_string(raw.get("base_url"), "base_url", errors)
    model = clean_string(raw.get("model"), "model", errors)
    config.update(
        {
        "provider": provider,
        "base_url": base_url,
        "anthropic_base_url": str(raw.get("anthropic_base_url") or config.get("anthropic_base_url") or "").strip(),
        "model": model,
        "model_version": str(raw.get("model_version") or config.get("model_version") or "").strip(),
        "reasoning_mode": str(raw.get("reasoning_mode") or config.get("reasoning_mode") or "default").strip(),
        "temperature": read_float(raw.get("temperature"), "temperature", errors, min_value=0.0),
        "max_tokens": read_int(raw.get("max_tokens"), "max_tokens", errors, min_value=1),
        "context_length_tokens": read_int(
            raw.get("context_length_tokens") or config.get("context_length_tokens"),
            "context_length_tokens",
            errors,
            min_value=1,
        ),
        "max_output_tokens_supported": read_int(
            raw.get("max_output_tokens_supported") or config.get("max_output_tokens_supported"),
            "max_output_tokens_supported",
            errors,
            min_value=1,
        ),
        "timeout_seconds": read_float(raw.get("timeout_seconds"), "timeout_seconds", errors, min_value=1.0),
        "max_retries": read_int(raw.get("max_retries"), "max_retries", errors, min_value=0),
        "retry_backoff_seconds": read_float(
            raw.get("retry_backoff_seconds"), "retry_backoff_seconds", errors, min_value=0.0
        ),
        "min_request_interval_seconds": read_float(
            raw.get("min_request_interval_seconds") or config.get("min_request_interval_seconds"),
            "min_request_interval_seconds",
            errors,
            min_value=0.0,
        ),
        }
    )
    return config


def normalize_pricing_config(
    raw: Dict[str, Any],
    model_config: Dict[str, Any],
    errors: List[str],
) -> Dict[str, Any]:
    config = load_yaml(str(PRICING_CONFIG_PATH)) if PRICING_CONFIG_PATH.exists() else {}
    currency = str(raw.get("currency") or "USD").strip() or "USD"
    model = str(raw.get("model") or model_config.get("model") or "").strip()
    if not model:
        errors.append("pricing model is required")
    models = dict(config.get("models", {}))
    models[model] = {
        "cached_input_per_1m_tokens": read_float(
            raw.get("cached_input_per_1m_tokens"), "cached_input_per_1m_tokens", errors, min_value=0.0
        ),
        "input_per_1m_tokens": read_float(
            raw.get("input_per_1m_tokens"), "input_per_1m_tokens", errors, min_value=0.0
        ),
        "output_per_1m_tokens": read_float(
            raw.get("output_per_1m_tokens"), "output_per_1m_tokens", errors, min_value=0.0
        ),
    }
    config.update({
        "currency": currency,
        "unit": str(raw.get("unit") or config.get("unit") or "per_1m_tokens").strip(),
        "models": models,
    })
    return config


def normalize_experiments_config(raw: Dict[str, Any], errors: List[str]) -> Dict[str, Any]:
    allowed = set(ARCHITECTURE_REGISTRY.keys())
    architectures = raw.get("architectures") or []
    if not isinstance(architectures, list):
        errors.append("architectures must be a list")
        architectures = []
    selected = [item for item in architectures if item in allowed]
    unknown = [str(item) for item in architectures if item not in allowed]
    if unknown:
        errors.append(f"unknown architecture(s): {', '.join(unknown)}")
    if not selected:
        errors.append("at least one architecture must be selected")

    return {
        "architectures": selected,
        "max_concurrency": read_int(raw.get("max_concurrency") or 1, "max_concurrency", errors, min_value=1),
        "task_file": clean_repo_path(raw.get("task_file"), "task_file", errors),
        "output_dir": clean_repo_path(raw.get("output_dir"), "output_dir", errors),
        "model_config": clean_repo_path(raw.get("model_config"), "model_config", errors),
        "pricing_config": clean_repo_path(raw.get("pricing_config"), "pricing_config", errors),
        "report_file": clean_repo_path(raw.get("report_file"), "report_file", errors),
    }


def clean_string(value: Any, field: str, errors: List[str]) -> str:
    text = str(value or "").strip()
    if not text:
        errors.append(f"{field} is required")
    return text


def clean_repo_path(value: Any, field: str, errors: List[str]) -> str:
    text = clean_string(value, field, errors)
    if text:
        try:
            resolve_repo_path(text)
        except Exception as exc:
            errors.append(f"{field}: {exc}")
    return text


def read_float(value: Any, field: str, errors: List[str], min_value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{field} must be a number")
        return min_value
    if number < min_value:
        errors.append(f"{field} must be >= {min_value}")
    return number


def read_int(value: Any, field: str, errors: List[str], min_value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append(f"{field} must be an integer")
        return min_value
    if number < min_value:
        errors.append(f"{field} must be >= {min_value}")
    return number


def resolve_repo_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (ROOT_DIR / path).resolve()
    if not resolved.is_relative_to(ROOT_DIR):
        raise ValueError("path must stay inside project root")
    return resolved


def dump_yaml(data: Dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(data), encoding="utf-8")


def build_env_preview(payload: Dict[str, Any]) -> str:
    api_key = str(payload.get("api_key") or "").strip()
    if not api_key:
        return "DEEPSEEK_API_KEY=<unchanged>"
    return "DEEPSEEK_API_KEY=<updated, hidden>"


def write_env_api_key(api_key: str) -> None:
    lines: List[str] = []
    replaced = False
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    new_lines: List[str] = []
    for line in lines:
        if line.strip().startswith("DEEPSEEK_API_KEY="):
            new_lines.append(f"DEEPSEEK_API_KEY={api_key}")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f"DEEPSEEK_API_KEY={api_key}")
    ENV_PATH.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    os.environ["DEEPSEEK_API_KEY"] = api_key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start Agent Architecture Lab local web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> int:
    load_dotenv_if_available()
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), LabWebHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Agent Architecture Lab UI: {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Agent Architecture Lab UI")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
