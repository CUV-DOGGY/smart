import json
import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PATH = (
    REPOSITORY_ROOT
    / "infra"
    / "grafana"
    / "dashboards"
    / "smartserve-overview.json"
)
ALERTS_PATH = (
    REPOSITORY_ROOT
    / "infra"
    / "grafana"
    / "provisioning"
    / "alerting"
    / "smartserve-alerts.yaml"
)
COMPOSE_PATH = REPOSITORY_ROOT / "infra" / "compose.dev.yml"


class GrafanaAssetsTests(unittest.TestCase):
    def test_overview_dashboard_contains_required_sections(self):
        dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))

        self.assertEqual(dashboard["uid"], "smartserve-overview")
        self.assertEqual(dashboard["title"], "SmartServe 全链路总览")
        titles = {panel.get("title") for panel in dashboard["panels"]}
        required_titles = {
            "API 请求量",
            "API 5 分钟错误率",
            "API 延迟 P50 / P95 / P99",
            "当前 SSE 连接数",
            "Agent 成功 / 超时 / 断连比例",
            "首 Token P50 / P95",
            "LLM 调用量",
            "LLM Token",
            "各 Tool 调用量",
            "各 Tool 成功率",
            "各 Tool P95",
            "写命令批准 / 拒绝",
            "恢复执行数量",
            "超过租约的写命令",
            "MongoDB 延迟",
            "Redis 延迟",
            "DeepSeek 延迟",
            "高德延迟",
            "Readiness",
            "告警状态",
        }
        self.assertTrue(required_titles <= titles)

    def test_first_alert_group_contains_all_required_rules(self):
        alerts = ALERTS_PATH.read_text(encoding="utf-8")
        rule_uids = set(
            re.findall(r"^\s{6}- uid: (\S+)\s*$", alerts, re.MULTILINE)
        )

        self.assertEqual(
            rule_uids,
            {
                "smartserve_api_error_rate",
                "smartserve_agent_timeout_rate",
                "smartserve_agent_p95",
                "smartserve_tool_failure_rate",
                "smartserve_write_command_overdue",
                "smartserve_readiness_failure",
            },
        )
        self.assertIn("params: [5]", alerts)
        self.assertIn("params: [2]", alerts)
        self.assertIn("params: [30]", alerts)
        self.assertIn("for: 1m", alerts)
        self.assertIn("for: 2m", alerts)

    def test_compose_mounts_dashboard_and_alert_provisioning(self):
        compose = COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertIn("./grafana/dashboards:", compose)
        self.assertIn(
            "./grafana/provisioning/dashboards/smartserve.yaml:",
            compose,
        )
        self.assertIn(
            "./grafana/provisioning/alerting/smartserve-alerts.yaml:",
            compose,
        )


if __name__ == "__main__":
    unittest.main()
