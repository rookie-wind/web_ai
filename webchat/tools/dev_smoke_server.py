"""开发冒烟服务：桩掉外网/mint/SDK 依赖，供浏览器端前端冒烟与演练。

仅用于本机验证（非生产入口）：账号 demo/demo-password-1，EchoHandle
回显文本并在含「写入」的消息上触发 gate_blocked 确认卡片；租约 TTL
刻意缩短（8s）以便演示「过期后发消息自动恢复」。

用法（webchat venv）：
    python webchat/tools/dev_smoke_server.py [--port 8800]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

import webchat.runtime as runtime_mod
from webchat.api import create_app
from webchat.config import Settings
from webchat.hashing import encode_password
from webchat.runtime import SessionRuntime
from webchat.sdk_runtime import WEvent

FAST_ITERATIONS = 1000
SMOKE_PASSWORD = "demo-password-1"


class EchoHandle:
    """回显句柄：文本回显；「写入」消息先经 gate 裁决触发确认卡片。"""

    def __init__(self, config, pat_env=None, gate=None):
        self.config = config
        self.gate = gate
        self.closed = False
        self.model = None

    async def list_models(self) -> list[dict]:
        """返回冒烟用模型清单。"""
        return [
            {"value": "smoke-model", "display_name": "Smoke Model",
             "is_enabled": True, "is_free": True, "price_factor": 1.0},
        ]

    async def set_model(self, model: str) -> None:
        """记录冒烟模型切换。"""
        self.model = model

    async def close(self):
        self.closed = True

    async def run_turn(self, prompt, **kwargs):
        # 慢轮次：命中「慢」停留 30 秒，供冒烟观察发送/停止切换态与重载恢复
        if "慢" in prompt:
            await asyncio.sleep(30)
        # 确认卡片：命中「写入」先经 gate 裁决产 gate_blocked（含 arg_summary）
        if "写入" in prompt and self.gate is not None:
            self.gate.decide(
                "mcp__xlpa__add_brand",
                {"brand": "南瑞", "model": "DSSD334", "token": "不该出现"},
            )
        # 工具折叠：命中「工具」产 tool_call + tool_result（含敏感键验证脱敏）
        if "工具" in prompt:
            yield WEvent(type="tool_call", payload={
                "id": "tu-smoke-1",
                "name": "mcp__xlpa__query_device_classes",
                "input": {"brand": "许继", "model": "DSSD", "token": "不该出现"},
            })
            yield WEvent(type="tool_result", payload={
                "tool_use_id": "tu-smoke-1",
                "content": [{"text": json.dumps(
                    {"total": 2, "token": "不该出现",
                     "items": ["许继A", "许继B"]}, ensure_ascii=False)}],
                "is_error": False,
            })
        # ask_user：命中「补充」产事件型提问
        if "补充" in prompt:
            yield WEvent(type="ask_user", payload={"message": "请补充设备型号与数量"})
        # 产物：命中「产物」落文件到 xlpa-output/，run_message 收尾扫描登记并产 artifact 事件
        if "产物" in prompt:
            out_dir = Path(self.config.cwd) / "xlpa-output"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "smoke_report.txt").write_text(
                "冒烟产物内容\nOK\n", encoding="utf-8",
            )
        # 富内容冒烟：命中关键词产 markdown 表格/代码块/mermaid/注入样例，
        # 分两次 text_delta 送达以覆盖前端节流渲染路径
        rich_lines = []
        if "表格" in prompt or "富" in prompt:
            rich_lines += [
                "| 寄存器 | 地址 | 类型 | 单位 |",
                "|---|---|---|---|",
                "| Ua | 0x00 | float | V |",
                "| Ub | 0x02 | float | V |",
                "",
            ]
        if "宽表格" in prompt:
            cols = [f"列{i}" for i in range(1, 16)]
            row = [f"值{i}" for i in range(1, 16)]
            rich_lines += [
                "| " + " | ".join(cols) + " |",
                "|" + "---|" * len(cols),
                "| " + " | ".join(row) + " |",
                "",
            ]
        if "代码" in prompt or "富" in prompt:
            rich_lines += ["```json", '{"points": [{"name": "Ua", "addr": 0}]}', "```", ""]
        if "大图" in prompt:
            # 多行 CJK 标签 + 边标签：复现“文字漂出节点框”的定位类缺陷
            rich_lines += [
                "```mermaid",
                "flowchart TB",
                '    A["监控端<br/>（电脑/XLPA）"] -->|"Modbus RTU 主动上报<br/>（短连接）"| B["网关机"]',
                '    B -->|"MQTT publish<br/>（内部 JSON → 平台格式）"| C["边缘后端(:7500)"]',
                '    C -->|"返回结果（rttCode=0）"| D["平台（MQTT）"]',
                "```",
                "",
            ]
        if "泳道图" in prompt:
            # 宽横向链路：自然宽 > 700px，验证阈值适配的横滚 + 提示条分支
            rich_lines += [
                "```mermaid",
                "flowchart LR",
                '    A["监控端（电脑/XLPA 客户端）"] -->|"Modbus RTU 主动上报/报警（短连接）"| B["网关机（Modbus 网关）"]',
                '    B -->|"MQTT publish（内部 JSON → 平台格式）"| C["边缘后端（:7500 服务）"]',
                '    C -->|"返回结果（rttCode=0）"| D["平台（MQTT 消息总线）"]',
                "```",
                "",
            ]
        if "流程图" in prompt or "富" in prompt:
            rich_lines += ["```mermaid", "flowchart LR; A[上传] --> B[提取]; B --> C[建档];", "```", ""]
        if "坏图" in prompt or "富" in prompt:
            rich_lines += ["```mermaid", "flowchart LR; A --> this is (bad", "```", ""]
        if "注入" in prompt or "富" in prompt:
            rich_lines += [
                "<script>window.__xss_executed=1</script>",
                '<img src=x onerror="window.__xss_img=1">',
                "[坏链接](javascript:alert(1))",
                "",
            ]
        if rich_lines:
            text = "\n".join(rich_lines)
            mid = max(1, len(text) // 2)
            yield WEvent(type="text_delta", payload={"text": text[:mid]})
            yield WEvent(type="text_delta", payload={"text": text[mid:]})
        yield WEvent(type="text_delta", payload={"text": f"[echo] {prompt}\n（冒烟桩实例）"})
        yield WEvent(type="turn_done", payload={})


async def _fake_platform_login(phone, code, base_url, transport=None):
    return {"userId": "55", "phone": phone, "token": "biz-smoke"}


async def _fake_mint(self, username, session_id):
    return f"tok-{username}-{session_id[:8]}"


async def _fake_revoke(self, token):
    return None


async def _fake_activate(mcp_url, token, phone, code):
    return {"success": True}


def build_app() -> tuple[object, Path]:
    """构造冒烟应用，返回 (app, 数据目录)。"""
    tmp = Path(tempfile.mkdtemp(prefix="webchat_smoke_"))
    (tmp / "accounts.json").write_text(
        json.dumps({
            "accounts": [{
                "username": "demo",
                "password_hash": encode_password(SMOKE_PASSWORD, FAST_ITERATIONS),
                "phone": "13900000000",
                "code": "9413",
                "enabled": True,
            }]
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp / "permissions.json").write_text(
        json.dumps({"superAccounts": {"userIds": ["55"], "phones": []}}),
        encoding="utf-8",
    )
    settings = Settings(
        session_ttl=3600,
        rate_window=60,
        rate_max_failures=1000,
        accounts_path=tmp / "accounts.json",
        permissions_path=tmp / "permissions.json",
        platform_base_url="https://platform.smoke",
        host="127.0.0.1",
        port=8800,
        mint_secret="smoke-mint-secret",
        mint_url="http://127.0.0.1:8765",
        max_instances=8,
        max_sessions_per_user=3,
        max_turns=25,
        workspaces_dir=tmp / "workspaces",
        events_dir=tmp / "events",
        lease_ttl=8,
        grant_ttl=300,
        gate_audit_path=tmp / "gate_audit.jsonl",
    )
    # 进程内替换外部依赖（开发桩，不改包代码）
    SessionRuntime._mint = _fake_mint
    SessionRuntime._revoke = _fake_revoke
    runtime_mod.call_login_tool = _fake_activate
    runtime_mod.AgentHandle = EchoHandle
    return create_app(settings, platform_login_impl=_fake_platform_login), tmp


def main() -> None:
    parser = argparse.ArgumentParser(description="webchat 开发冒烟服务")
    parser.add_argument("--port", type=int, default=8800)
    args = parser.parse_args()
    app, tmp = build_app()
    print(f"[smoke] data dir: {tmp}")
    print(f"[smoke] login: demo / {SMOKE_PASSWORD}  http://127.0.0.1:{args.port}/")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
