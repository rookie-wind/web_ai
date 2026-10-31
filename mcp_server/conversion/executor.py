"""沙箱执行调度：子进程 + 超时 + 大小上限 + 独立临时目录用后即清。

纪律（design D2）：
- 执行固定代码（runner + 分发源镜像引擎），输入仅作数据；
- 命令为参数列表（无 shell、无字符串拼接命令行）；
- 每次调用独立临时目录，结束即删（成功与失败路径均清理）；
- 超时 / 超限 / 非零退出显式返回失败原因，绝不静默跳过。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

# 上限（病态输入兜底，正常纯内存操作毫秒级完成）
MAX_REQUEST_BYTES = 1024 * 1024        # 请求体（config+input）1 MB
MAX_OUTPUT_BYTES = 2 * 1024 * 1024     # stdout 2 MB
CASE_TIMEOUT_SECONDS = 20.0            # 单 case 超时
ENGINE_MODULE = "protocol_converter.py"


class SandboxError(Exception):
    """沙箱执行错误（含失败原因，供工具层转为结构化返回）。"""


class Executor:
    """子进程沙箱执行器（固定 runner + 分发源引擎）。"""

    def __init__(self, engine_dir: str, runner_path: str | None = None):
        """初始化执行器。

        Args:
            engine_dir: 分发源引擎目录（含 protocol_converter.py）。
            runner_path: runner 脚本路径；缺省取本包 sandbox_runner.py。
        """
        self.engine_dir = engine_dir
        self.runner_path = runner_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "sandbox_runner.py"
        )

    def engine_available(self) -> bool:
        """引擎镜像文件是否可用（启动校验用）。"""
        return bool(self.engine_dir) and os.path.isfile(
            os.path.join(self.engine_dir, ENGINE_MODULE)
        )

    def run_case(self, mode: str, config: dict, source: dict) -> dict:
        """在沙箱中执行单条 case，返回 ``{ok, output?, error?}``。

        Raises:
            SandboxError: 输入超限 / 引擎缺失 / 超时 / 非零退出 / 输出超限 /
                结果解析失败。
        """
        if mode not in ("mqtt", "http"):
            raise SandboxError(f"未知执行模式: {mode}")
        if not self.engine_available():
            raise SandboxError("引擎不可用（镜像文件缺失）")

        request = {"mode": mode, "config": config, "input": source}
        raw = json.dumps(request, ensure_ascii=False).encode("utf-8")
        if len(raw) > MAX_REQUEST_BYTES:
            raise SandboxError(f"输入超过上限 {MAX_REQUEST_BYTES} 字节")

        sandbox_dir = tempfile.mkdtemp(prefix="conv_sandbox_")
        try:
            env = dict(os.environ)
            env["CONVERSION_ENGINE_DIR"] = self.engine_dir
            try:
                proc = subprocess.run(
                    [sys.executable, self.runner_path],
                    input=raw,
                    capture_output=True,
                    timeout=CASE_TIMEOUT_SECONDS,
                    cwd=sandbox_dir,
                    env=env,
                )
            except subprocess.TimeoutExpired as exc:
                raise SandboxError(
                    f"执行超时（>{CASE_TIMEOUT_SECONDS}s）"
                ) from exc
        finally:
            shutil.rmtree(sandbox_dir, ignore_errors=True)

        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", "replace").strip()
            raise SandboxError(
                f"执行失败（退出码 {proc.returncode}）: {stderr[:500]}"
            )
        stdout = proc.stdout
        if len(stdout) > MAX_OUTPUT_BYTES:
            raise SandboxError(f"输出超过上限 {MAX_OUTPUT_BYTES} 字节")
        try:
            return json.loads(stdout.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - 结果非 JSON
            raise SandboxError(f"执行结果解析失败: {exc}") from exc
