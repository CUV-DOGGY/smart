#!/usr/bin/env python3
"""Live SmartServe observability acceptance checks.

Run this with ``backend/.venv/Scripts/python.exe`` while the development API
and LGTM stack are running. The output intentionally excludes credentials,
prompt text, customer fields, token text and model responses.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import math
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from pymongo import MongoClient


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.services.write_command_service import WriteCommandService  # noqa: E402


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[index], 3)


class AcceptanceFailure(RuntimeError):
    pass


class AcceptanceRun:
    def __init__(
        self,
        *,
        api_base_url: str,
        grafana_base_url: str,
        run_id: str,
        username: str,
        password: str,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.grafana_base_url = grafana_base_url.rstrip("/")
        self.run_id = run_id
        self.username = username
        self.password = password
        self.shop_id = f"obs-shop-{run_id}"
        self.food_id = f"obs-food-{run_id}"
        self.address_id = f"obs-address-{run_id}"
        self.prompt_canary = f"PROMPT_PRIVATE_{run_id}"
        self.address_canary = f"验收隐私路{run_id}号"
        self.phone_canary = f"139{int(run_id[-8:]):08d}"[-11:]
        self.client = httpx.Client(
            base_url=self.api_base_url,
            timeout=httpx.Timeout(120, connect=10),
            trust_env=False,
        )
        self.mongo = MongoClient(
            settings.MONGODB_URL,
            serverSelectionTimeoutMS=3000,
        )
        self.db = self.mongo[settings.MONGODB_DB_NAME]
        self.token = ""
        self.user_id = ""
        self.report: dict[str, Any] = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "api_base_url": self.api_base_url,
            "scenarios": {},
            "trace_validation": {},
            "privacy_validation": {},
        }

    def close(self) -> None:
        self.client.close()
        self.mongo.close()

    def prepare(self) -> None:
        self._ensure_seed_data()
        login = self.client.post(
            "/auth/login",
            data={"username": self.username, "password": self.password},
            headers={"X-Request-ID": self._request_id("login")},
        )
        if login.status_code == 401:
            response = self.client.post(
                "/auth/register",
                json={"username": self.username, "password": self.password},
                headers={"X-Request-ID": self._request_id("register")},
            )
            if response.status_code not in {201, 409}:
                raise AcceptanceFailure(
                    f"registration returned HTTP {response.status_code}"
                )
            login = self.client.post(
                "/auth/login",
                data={"username": self.username, "password": self.password},
                headers={"X-Request-ID": self._request_id("login")},
            )
        if login.status_code != 200:
            raise AcceptanceFailure(f"login returned HTTP {login.status_code}")
        self.token = login.json()["access_token"]
        self.client.headers["Authorization"] = f"Bearer {self.token}"
        me = self.client.get(
            "/auth/me",
            headers={"X-Request-ID": self._request_id("me")},
        )
        if me.status_code != 200:
            raise AcceptanceFailure(f"/auth/me returned HTTP {me.status_code}")
        self.user_id = me.json()["user_id"]
        self._ensure_address()
        self.report["scenarios"]["login_and_list"] = {
            "status": "passed",
            "login_status": login.status_code,
            "me_status": me.status_code,
            "catalog_status": self.client.get("/catalog/shops").status_code,
            "conversation_list_status": self.client.get(
                "/conversations"
            ).status_code,
        }

    def run_business_scenarios(self) -> None:
        pure = self.stream(
            "pure_model",
            "/chat/stream",
            {
                "message": (
                    "不要调用工具，只用一句简短中文确认服务可用。"
                    f"内部标记 {self.prompt_canary} 不要复述。"
                )
            },
        )
        self._require_events(pure, "meta", "token", "done")

        read_tool = self.stream(
            "read_tool",
            "/chat/stream",
            {
                "message": (
                    "请调用 list_products 工具查询店铺ID "
                    f"{self.shop_id} 的可售商品，只查询不要修改。"
                )
            },
        )
        self._require_events(read_tool, "meta", "token", "done")

        rejected = self._create_order_confirmation("write_reject")
        rejected_resume = self.stream(
            "write_reject_resume",
            "/chat/resume",
            {
                "conversation_id": rejected["conversation_id"],
                "interrupt_id": rejected["command_id"],
                "decision": "reject",
            },
            extra_headers={"Idempotency-Key": f"e2e-reject-{self.run_id}"},
        )
        self._require_events(rejected_resume, "meta", "done")
        rejected_document = self.db.write_commands.find_one(
            {"command_id": rejected["command_id"]},
            {"_id": 0, "status": 1},
        )
        if not rejected_document or rejected_document["status"] != "rejected":
            raise AcceptanceFailure("rejected command did not reach rejected")
        self.report["scenarios"]["write_reject"]["command_status"] = (
            "rejected"
        )

        approved = self._create_order_confirmation("write_approve")
        approved_resume = self.stream(
            "write_approve_resume",
            "/chat/resume",
            {
                "conversation_id": approved["conversation_id"],
                "interrupt_id": approved["command_id"],
                "decision": "approve",
            },
            extra_headers={"Idempotency-Key": f"e2e-approve-{self.run_id}"},
        )
        self._require_events(approved_resume, "meta", "done")
        approved_document = self.db.write_commands.find_one(
            {"command_id": approved["command_id"]},
            {"_id": 0, "status": 1, "result.ok": 1},
        )
        if not approved_document or approved_document["status"] != "succeeded":
            raise AcceptanceFailure("approved command did not reach succeeded")
        self.report["scenarios"]["write_approve"]["command_status"] = (
            "succeeded"
        )

        disconnected = self.stream(
            "sse_disconnect",
            "/chat/stream",
            {"message": "用一句话说明当前服务状态，不要调用工具。"},
            disconnect_after=1,
        )
        if disconnected["event_counts"].get("meta") != 1:
            raise AcceptanceFailure("disconnect scenario did not receive meta")

        recovery = self._create_order_confirmation("worker_recovery")
        now = datetime.now(timezone.utc)
        decision_key = f"e2e-recovery-{self.run_id}"
        updated = self.db.write_commands.update_one(
            {
                "command_id": recovery["command_id"],
                "status": "awaiting_confirmation",
            },
            {
                "$set": {
                    "status": "approved",
                    "decision": "approve",
                    "decision_idempotency_key": decision_key,
                    "decision_request_hash": WriteCommandService.decision_hash(
                        recovery["command_id"], "approve"
                    ),
                    "decided_at": now - timedelta(seconds=30),
                    "next_attempt_at": now - timedelta(seconds=30),
                    "updated_at": now - timedelta(seconds=30),
                },
                "$inc": {"version": 1},
            },
        )
        if updated.modified_count != 1:
            raise AcceptanceFailure("could not stage worker recovery command")
        deadline = time.monotonic() + 35
        status = "approved"
        while time.monotonic() < deadline:
            document = self.db.write_commands.find_one(
                {"command_id": recovery["command_id"]},
                {"_id": 0, "status": 1},
            )
            status = document["status"] if document else "missing"
            if status in {"succeeded", "conflict", "failed"}:
                break
            time.sleep(1)
        if status != "succeeded":
            raise AcceptanceFailure(
                f"worker recovery reached unexpected status {status}"
            )
        recovery_document = self.db.write_commands.find_one(
            {"command_id": recovery["command_id"]},
            {"_id": 0, "trace_context": 1},
        )
        self.report["scenarios"]["worker_recovery"].update(
            {
                "command_status": status,
                "original_trace_id": self._trace_id_from_context(
                    recovery_document.get("trace_context")
                    if recovery_document
                    else None
                ),
            }
        )

    def stream(
        self,
        name: str,
        path: str,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
        disconnect_after: int | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            "X-Request-ID": self._request_id(name),
            **(extra_headers or {}),
        }
        started = time.perf_counter()
        first_token_ms: float | None = None
        events: list[dict[str, Any]] = []
        client = self.client
        temporary_client = None
        if base_url:
            temporary_client = httpx.Client(
                base_url=base_url.rstrip("/"),
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=httpx.Timeout(120, connect=10),
                trust_env=False,
            )
            client = temporary_client
        try:
            with client.stream(
                "POST",
                path,
                json=payload,
                headers=headers,
            ) as response:
                headers_ms = (time.perf_counter() - started) * 1000
                if response.status_code != 200:
                    raise AcceptanceFailure(
                        f"{name} returned HTTP {response.status_code}"
                    )
                request_id = response.headers.get("X-Request-ID")
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:].lstrip())
                    events.append(event)
                    if event.get("type") == "token" and first_token_ms is None:
                        first_token_ms = (
                            time.perf_counter() - started
                        ) * 1000
                    if disconnect_after and len(events) >= disconnect_after:
                        break
        finally:
            if temporary_client is not None:
                temporary_client.close()
        total_ms = (time.perf_counter() - started) * 1000
        counts = Counter(str(event.get("type") or "unknown") for event in events)
        result = {
            "status": "passed",
            "request_id": request_id,
            "response_headers_ms": round(headers_ms, 3),
            "first_token_ms": (
                round(first_token_ms, 3) if first_token_ms is not None else None
            ),
            "total_ms": round(total_ms, 3),
            "event_counts": dict(counts),
            "disconnected_by_client": bool(disconnect_after),
        }
        self.report["scenarios"][name] = result
        return {**result, "events": events}

    def run_model_failure(self, fault_api_base_url: str) -> None:
        failure = self.stream(
            "model_failure",
            "/chat/stream",
            {"message": "只回复服务状态，不要调用工具。"},
            base_url=fault_api_base_url,
        )
        self._require_events(failure, "meta", "error")

    def validate_traces(self) -> None:
        time.sleep(8)
        read_request_id = self.report["scenarios"]["read_tool"]["request_id"]
        read_trace_id = self._find_trace_id(
            f'{{ span.app.request_id = "{read_request_id}" }}'
        )
        read_trace = self._get_trace(read_trace_id)
        span_names = sorted(set(self._span_names(read_trace)))
        required = {
            "POST /chat/stream",
            "agent.run",
            "agent.graph",
            "agent.model",
            "agent.tool.list_products",
        }
        missing = sorted(required - set(span_names))
        if missing:
            raise AcceptanceFailure(f"read tool trace misses spans: {missing}")
        has_mongo = any(
            name.startswith(f"{settings.MONGODB_DB_NAME}.")
            for name in span_names
        )
        has_redis = any(
            name.upper() in {"GET", "SET", "SETEX", "DEL", "EVAL", "PING"}
            for name in span_names
        )
        if not has_mongo or not has_redis:
            raise AcceptanceFailure(
                f"dependency spans missing mongo={has_mongo} redis={has_redis}"
            )

        recovery_command = self._command_id_for("worker_recovery")
        recovery_trace_id = self._find_trace_id(
            f'{{ span.app.command_id = "{recovery_command}" '
            '&& name = "write_command.recovery" }'
        )
        recovery_trace = self._get_trace(recovery_trace_id)
        original_trace_id = self.report["scenarios"]["worker_recovery"][
            "original_trace_id"
        ]
        linked_trace_ids = set(self._link_trace_ids(recovery_trace))
        if original_trace_id not in linked_trace_ids:
            raise AcceptanceFailure(
                "worker recovery span does not link to the originating trace"
            )

        log_found = self._request_id_in_loki(read_request_id)
        if not log_found:
            raise AcceptanceFailure("request_id was not found in Loki logs")

        sensitive_values = [
            self.prompt_canary,
            self.address_canary,
            self.phone_canary,
            self.password,
            self.token,
            settings.DEEPSEEK_API_KEY,
            settings.AMAP_WEB_SERVICE_KEY.get_secret_value(),
        ]
        serialized_traces = json.dumps(
            [read_trace, recovery_trace],
            ensure_ascii=False,
        )
        leaks = [
            self._sensitive_category(value)
            for value in sensitive_values
            if value and value in serialized_traces
        ]
        if leaks:
            raise AcceptanceFailure(
                f"sensitive values appeared in traces: {sorted(set(leaks))}"
            )
        self.report["trace_validation"] = {
            "status": "passed",
            "read_tool_trace_id": read_trace_id,
            "span_names": span_names,
            "has_mongodb": has_mongo,
            "has_redis": has_redis,
            "request_id_log_correlation": True,
            "recovery_trace_id": recovery_trace_id,
            "recovery_linked_to_original": True,
        }
        self.report["privacy_validation"] = {
            "status": "passed",
            "checked_categories": [
                "api_key",
                "jwt",
                "password",
                "prompt",
                "address",
                "phone",
            ],
            "leak_count": 0,
        }

    def record_dependency_faults(
        self,
        *,
        redis_request_id: str,
        mongodb_request_id: str,
    ) -> None:
        results: dict[str, Any] = {}
        for dependency, request_id in (
            ("redis", redis_request_id),
            ("mongodb", mongodb_request_id),
        ):
            trace_id = self._find_trace_id(
                f'{{ span.app.request_id = "{request_id}" }}'
            )
            trace = self._get_trace(trace_id)
            span_names = sorted(set(self._span_names(trace)))
            expected = "PING" if dependency == "redis" else "admin.ping"
            if not any(
                name.upper() == expected.upper() or name.endswith(".ping")
                for name in span_names
            ):
                raise AcceptanceFailure(
                    f"{dependency} failure trace misses dependency ping span"
                )
            results[dependency] = {
                "failure_status": 503,
                "recovered_status": 200,
                "request_id": request_id,
                "trace_id": trace_id,
                "span_names": span_names,
            }
        self.report["dependency_faults"] = {
            "status": "passed",
            **results,
        }

    def validate_browser_trace(self) -> None:
        traceql = (
            '{ resource.service.name = "smartserve-web" '
            '&& name = "chat.stream" }'
        )
        deadline = time.monotonic() + 35
        required = {
            "chat.stream",
            "POST /chat/stream",
            "agent.run",
            "agent.graph",
            "agent.model",
            "agent.tool.list_products",
        }
        selected: tuple[str, dict[str, Any], list[str]] | None = None
        while time.monotonic() < deadline and selected is None:
            result = self._grafana_get(
                "/api/datasources/proxy/uid/tempo/api/search",
                params={"q": traceql, "limit": 20},
            )
            for summary in result.get("traces") or []:
                trace_id = summary["traceID"]
                trace = self._get_trace(trace_id)
                names = sorted(set(self._span_names(trace)))
                if required <= set(names):
                    selected = (trace_id, trace, names)
                    break
            if selected is None:
                time.sleep(2)
        if selected is None:
            raise AcceptanceFailure(
                "no browser chat trace contained the complete backend tool chain"
            )
        trace_id, trace, names = selected
        has_mongo = any(
            name.startswith(f"{settings.MONGODB_DB_NAME}.") for name in names
        )
        has_redis = any(
            name.upper() in {"GET", "SET", "SETEX", "DEL", "EVAL", "PING"}
            for name in names
        )
        if not has_mongo or not has_redis:
            raise AcceptanceFailure(
                "browser trace does not contain both MongoDB and Redis spans"
            )
        serialized = json.dumps(trace, ensure_ascii=False)
        sensitive_values = [
            self.password,
            self.token,
            settings.DEEPSEEK_API_KEY,
            settings.AMAP_WEB_SERVICE_KEY.get_secret_value(),
        ]
        if any(value and value in serialized for value in sensitive_values):
            raise AcceptanceFailure("browser trace contains a credential value")
        self.report["browser_trace"] = {
            "status": "passed",
            "trace_id": trace_id,
            "span_names": names,
            "has_mongodb": True,
            "has_redis": True,
        }

    def measure_endpoint(self, base_url: str, *, iterations: int) -> dict[str, Any]:
        samples: list[float] = []
        with httpx.Client(
            base_url=base_url,
            timeout=10,
            trust_env=False,
            headers={"Connection": "close"},
        ) as client:
            for _ in range(10):
                response = client.get("/health/ready")
                if response.status_code != 200:
                    raise AcceptanceFailure(
                        f"performance endpoint returned HTTP {response.status_code}"
                    )
            for _ in range(iterations):
                started = time.perf_counter()
                response = client.get("/health/ready")
                elapsed = (time.perf_counter() - started) * 1000
                if response.status_code != 200:
                    raise AcceptanceFailure(
                        f"performance endpoint returned HTTP {response.status_code}"
                    )
                samples.append(elapsed)
        return {
            "iterations": iterations,
            "mean_ms": round(statistics.fmean(samples), 3),
            "p50_ms": percentile(samples, 0.5),
            "p95_ms": percentile(samples, 0.95),
            "max_ms": round(max(samples), 3),
        }

    def measure_paired_endpoints(
        self,
        disabled_api_base_url: str,
        *,
        iterations: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        samples = {"enabled": [], "disabled": []}
        clients = {
            "enabled": httpx.Client(
                base_url=self.api_base_url,
                timeout=10,
                trust_env=False,
                headers={"Connection": "close"},
            ),
            "disabled": httpx.Client(
                base_url=disabled_api_base_url,
                timeout=10,
                trust_env=False,
                headers={"Connection": "close"},
            ),
        }
        try:
            for client in clients.values():
                for _ in range(10):
                    response = client.get("/health/ready")
                    if response.status_code != 200:
                        raise AcceptanceFailure(
                            "performance warm-up endpoint was not ready"
                        )
            for index in range(iterations):
                order = (
                    ("enabled", "disabled")
                    if index % 2 == 0
                    else ("disabled", "enabled")
                )
                for mode in order:
                    started = time.perf_counter()
                    response = clients[mode].get("/health/ready")
                    elapsed = (time.perf_counter() - started) * 1000
                    if response.status_code != 200:
                        raise AcceptanceFailure(
                            f"{mode} performance endpoint returned "
                            f"HTTP {response.status_code}"
                        )
                    samples[mode].append(elapsed)
        finally:
            for client in clients.values():
                client.close()

        def summary(values: list[float]) -> dict[str, Any]:
            return {
                "iterations": len(values),
                "mean_ms": round(statistics.fmean(values), 3),
                "p50_ms": percentile(values, 0.5),
                "p95_ms": percentile(values, 0.95),
                "max_ms": round(max(values), 3),
            }

        return summary(samples["enabled"]), summary(samples["disabled"])

    def compare_observability_overhead(
        self,
        disabled_api_base_url: str,
        *,
        iterations: int,
    ) -> None:
        existing_disabled = self.report.get("observability_disabled", {})
        if existing_disabled.get("chat_event_counts"):
            disabled_chat = {
                "event_counts": existing_disabled["chat_event_counts"]
            }
        else:
            disabled_chat = self.stream(
                "observability_disabled_chat",
                "/chat/stream",
                {"message": "不要调用工具，只用一句简短中文确认服务可用。"},
                base_url=disabled_api_base_url,
            )
            self._require_events(disabled_chat, "meta", "token", "done")
        enabled, disabled = self.measure_paired_endpoints(
            disabled_api_base_url,
            iterations=iterations,
        )
        baseline = disabled["p95_ms"] or 0
        overhead = (
            ((enabled["p95_ms"] - baseline) / baseline) * 100
            if baseline > 0
            else None
        )
        self.report["observability_disabled"] = {
            "status": "passed",
            "health_ready_status": httpx.get(
                f"{disabled_api_base_url.rstrip('/')}/health/ready",
                timeout=10,
                trust_env=False,
            ).status_code,
            "chat_event_counts": disabled_chat["event_counts"],
        }
        self.report["performance"] = {
            "enabled": enabled,
            "disabled": disabled,
            "p95_overhead_percent": (
                round(overhead, 2) if overhead is not None else None
            ),
            "target_percent": 10,
            "within_target": overhead is not None and overhead <= 10,
        }

    def cleanup(self) -> None:
        conversation_ids = [
            item["conversation_id"]
            for item in self.db.conversations.find(
                {"user_id": self.user_id},
                {"_id": 0, "conversation_id": 1},
            )
        ]
        thread_ids = [
            f"{self.user_id}:{conversation_id}"
            for conversation_id in conversation_ids
        ]
        order_ids = [
            item["order_id"]
            for item in self.db.orders.find(
                {"user_id": self.user_id},
                {"_id": 0, "order_id": 1},
            )
        ]
        self.db.orders.delete_many({"order_id": {"$in": order_ids}})
        self.db.write_commands.delete_many({"user_id": self.user_id})
        self.db.conversation_messages.delete_many({"user_id": self.user_id})
        self.db.conversations.delete_many({"user_id": self.user_id})
        if thread_ids:
            self.db.agent_checkpoint_writes.delete_many(
                {"thread_id": {"$in": thread_ids}}
            )
            self.db.agent_checkpoints.delete_many(
                {"thread_id": {"$in": thread_ids}}
            )
        self.db.user_addresses.delete_many({"user_id": self.user_id})
        self.db.users.delete_one({"user_id": self.user_id})
        self.db.products.delete_many({"food_id": self.food_id})
        self.db.shops.delete_many({"shop_id": self.shop_id})

    def write_report(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _ensure_seed_data(self) -> None:
        now = datetime.now(timezone.utc)
        self.db.shops.update_one(
            {"shop_id": self.shop_id},
            {
                "$set": {
                    "shop_id": self.shop_id,
                    "shop_name": "观测验收店铺",
                    "is_active": True,
                    "is_accepting_orders": True,
                    "timezone": "Asia/Shanghai",
                    "business_hours": [
                        {
                            "day_of_week": day,
                            "open_time": "00:00:00",
                            "close_time": "23:59:59",
                        }
                        for day in range(7)
                    ],
                    "minimum_order_amount": 0.0,
                    "delivery_fee": 0.0,
                    "longitude": 121.4737,
                    "latitude": 31.2304,
                    "adcode": "310101",
                    "formatted_address": "上海市验收区域",
                    "delivery_radius_meters": 10_000,
                    "location_updated_at": now,
                }
            },
            upsert=True,
        )
        self.db.products.update_one(
            {"food_id": self.food_id, "shop_id": self.shop_id},
            {
                "$set": {
                    "food_id": self.food_id,
                    "shop_id": self.shop_id,
                    "food_name": "观测验收商品",
                    "price": 12.5,
                    "stock": 20,
                    "reserved_stock": 0,
                    "is_listed": True,
                    "is_available": True,
                }
            },
            upsert=True,
        )

    def _ensure_address(self) -> None:
        now = datetime.now(timezone.utc)
        self.db.user_addresses.update_one(
            {"address_id": self.address_id, "user_id": self.user_id},
            {
                "$set": {
                    "address_id": self.address_id,
                    "user_id": self.user_id,
                    "receiver_name": "验收用户",
                    "receiver_phone": self.phone_canary,
                    "province": "上海市",
                    "city": "上海市",
                    "district": "黄浦区",
                    "detail_address": self.address_canary,
                    "longitude": 121.4737,
                    "latitude": 31.2304,
                    "formatted_address": "上海市黄浦区验收区域",
                    "adcode": "310101",
                    "location_source": "map_pick",
                    "verification_status": "verified",
                    "is_default": True,
                    "version": 1,
                    "is_deleted": False,
                    "create_time": now,
                    "update_time": now,
                }
            },
            upsert=True,
        )

    def _create_order_confirmation(self, name: str) -> dict[str, str]:
        result = self.stream(
            name,
            "/chat/stream",
            {
                "message": (
                    "请调用 create_order 创建订单：店铺ID "
                    f"{self.shop_id}，地址ID {self.address_id}，商品ID "
                    f"{self.food_id}，数量1。只准备确认，不要跳过确认。"
                )
            },
        )
        confirmation = next(
            (
                event
                for event in result["events"]
                if event.get("type") == "confirmation_required"
            ),
            None,
        )
        meta = next(
            (event for event in result["events"] if event.get("type") == "meta"),
            None,
        )
        if not confirmation or not meta:
            raise AcceptanceFailure(f"{name} did not produce confirmation")
        self._require_events(result, "meta", "confirmation_required", "done")
        self.report["scenarios"][name]["command_id"] = confirmation[
            "command_id"
        ]
        return {
            "command_id": confirmation["command_id"],
            "conversation_id": meta["conversation_id"],
        }

    def _require_events(self, result: dict[str, Any], *event_types: str) -> None:
        missing = [
            event_type
            for event_type in event_types
            if not result["event_counts"].get(event_type)
        ]
        if missing:
            raise AcceptanceFailure(
                f"stream missed event types {missing}: {result['event_counts']}"
            )

    def _request_id(self, name: str) -> str:
        return f"e2e-{self.run_id}-{name}"[:128]

    def _command_id_for(self, scenario: str) -> str:
        value = self.report["scenarios"][scenario].get("command_id")
        if not value:
            raise AcceptanceFailure(f"missing command id for {scenario}")
        return str(value)

    @staticmethod
    def _trace_id_from_context(context: Any) -> str | None:
        if not isinstance(context, dict):
            return None
        traceparent = context.get("traceparent")
        if not isinstance(traceparent, str):
            return None
        parts = traceparent.split("-")
        return parts[1] if len(parts) >= 4 else None

    def _grafana_get(self, path: str, *, params: dict[str, Any] | None = None):
        response = httpx.get(
            f"{self.grafana_base_url}{path}",
            params=params,
            auth=("admin", "admin"),
            timeout=30,
            trust_env=False,
        )
        response.raise_for_status()
        return response.json()

    def _find_trace_id(self, traceql: str) -> str:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = self._grafana_get(
                "/api/datasources/proxy/uid/tempo/api/search",
                params={"q": traceql, "limit": 20},
            )
            traces = result.get("traces") or []
            if traces:
                return traces[0]["traceID"]
            time.sleep(2)
        raise AcceptanceFailure(f"Tempo query returned no trace: {traceql}")

    def _get_trace(self, trace_id: str) -> dict[str, Any]:
        return self._grafana_get(
            f"/api/datasources/proxy/uid/tempo/api/traces/{quote(trace_id)}"
        )

    @staticmethod
    def _span_names(value: Any) -> list[str]:
        names: list[str] = []
        if isinstance(value, dict):
            if isinstance(value.get("name"), str) and (
                "spanId" in value or "spanID" in value
            ):
                names.append(value["name"])
            for child in value.values():
                names.extend(AcceptanceRun._span_names(child))
        elif isinstance(value, list):
            for child in value:
                names.extend(AcceptanceRun._span_names(child))
        return names

    @staticmethod
    def _link_trace_ids(value: Any) -> list[str]:
        trace_ids: list[str] = []
        if isinstance(value, dict):
            links = value.get("links")
            if isinstance(links, list):
                for link in links:
                    if not isinstance(link, dict):
                        continue
                    trace_id = link.get("traceId") or link.get("traceID")
                    if isinstance(trace_id, str):
                        normalized = trace_id.lower()
                        if len(normalized) != 32:
                            try:
                                normalized = base64.b64decode(trace_id).hex()
                            except (ValueError, TypeError):
                                pass
                        trace_ids.append(normalized)
            for child in value.values():
                trace_ids.extend(AcceptanceRun._link_trace_ids(child))
        elif isinstance(value, list):
            for child in value:
                trace_ids.extend(AcceptanceRun._link_trace_ids(child))
        return trace_ids

    def _request_id_in_loki(self, request_id: str) -> bool:
        now_ns = int(time.time() * 1_000_000_000)
        result = self._grafana_get(
            "/api/datasources/proxy/uid/loki/loki/api/v1/query_range",
            params={
                "query": f'{{service_name="smartserve-backend"}} |= "{request_id}"',
                "start": now_ns - 3_600_000_000_000,
                "end": now_ns,
                "limit": 100,
                "direction": "backward",
            },
        )
        return bool(result.get("data", {}).get("result"))

    def _sensitive_category(self, value: str) -> str:
        if value == self.prompt_canary:
            return "prompt"
        if value == self.address_canary:
            return "address"
        if value == self.phone_canary:
            return "phone"
        if value == self.password:
            return "password"
        if value == self.token:
            return "jwt"
        return "api_key"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--grafana-base-url", default="http://127.0.0.1:3000")
    parser.add_argument("--fault-api-base-url")
    parser.add_argument("--disabled-api-base-url")
    parser.add_argument("--redis-failure-request-id")
    parser.add_argument("--mongodb-failure-request-id")
    parser.add_argument("--validate-browser-trace", action="store_true")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / ".runtime-logs" / "observability-e2e.json",
    )
    parser.add_argument("--performance-iterations", type=int, default=80)
    parser.add_argument("--skip-business", action="store_true")
    parser.add_argument("--skip-traces", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    password = (
        args.password
        or os.getenv("OBSERVABILITY_E2E_PASSWORD")
        or getpass.getpass("E2E test account password: ")
    )
    run = AcceptanceRun(
        api_base_url=args.api_base_url,
        grafana_base_url=args.grafana_base_url,
        run_id=args.run_id,
        username=args.username,
        password=password,
    )
    try:
        if args.skip_business and args.output.exists():
            run.report = json.loads(args.output.read_text(encoding="utf-8"))
        run.prepare()
        if not args.skip_business:
            run.run_business_scenarios()
        if args.fault_api_base_url:
            run.run_model_failure(args.fault_api_base_url)
        if args.disabled_api_base_url:
            run.compare_observability_overhead(
                args.disabled_api_base_url,
                iterations=args.performance_iterations,
            )
        if args.redis_failure_request_id and args.mongodb_failure_request_id:
            run.record_dependency_faults(
                redis_request_id=args.redis_failure_request_id,
                mongodb_request_id=args.mongodb_failure_request_id,
            )
        if args.validate_browser_trace:
            run.validate_browser_trace()
        if not args.skip_traces:
            run.validate_traces()
        run.report["status"] = "passed"
        if args.cleanup:
            run.cleanup()
            run.report["cleanup"] = "completed"
        run.write_report(args.output)
        print(
            json.dumps(
                {
                    "status": "passed",
                    "output": str(args.output),
                    "scenarios": sorted(run.report["scenarios"]),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        run.report["status"] = "failed"
        run.report["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        run.write_report(args.output)
        print(
            json.dumps(
                {
                    "status": "failed",
                    "output": str(args.output),
                    "failure_type": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        run.close()


if __name__ == "__main__":
    raise SystemExit(main())
