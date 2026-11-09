"""本地 OCR 可插拔 provider（默认 rapidocr + onnxruntime）。

纪律（design D2）：
- 模型**首次使用时懒加载**，不在 create_app 时加载（启动快、不白占内存）；
- 识别失败或行列结构无法保留（``structure_ok=False``）→ 抛显式异常，上传端点
  转 4xx 提示，**不静默以猜测内容继续**；
- 依赖缺失/加载失败 → 抛 ``OcrUnavailable``，截图通道降级提示，不崩溃主服务。

provider 可经 ``WEBCHAT_OCR_PROVIDER`` 切换，为二期照片通道与 V8' 质量不达标
时的引擎替换预留接口。
"""

from __future__ import annotations

__all__ = [
    "OcrFailed",
    "OcrResult",
    "OcrUnavailable",
    "OCRProvider",
    "RapidOcrProvider",
    "get_ocr_provider",
]

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

# 行列结构保留的置信度经验阈值（实现期定，V8' 基线可复核调整）。
DEFAULT_MIN_CONFIDENCE = 0.6


class OcrUnavailable(RuntimeError):
    """OCR 依赖缺失或引擎加载失败（截图通道降级，不崩溃服务）。"""


class OcrFailed(RuntimeError):
    """识别失败或行列结构无法保留（必须显式提示，不得静默猜测）。"""


@dataclass
class OcrResult:
    """一次识别的结果。"""

    text: str
    structure_ok: bool
    confidence: float
    lines: list[str] = field(default_factory=list)


@runtime_checkable
class OCRProvider(Protocol):
    """OCR provider 协议：图片字节 → 识别结果。"""

    def recognize(self, image_bytes: bytes) -> OcrResult:
        """识别图片；失败抛 ``OcrUnavailable`` / ``OcrFailed``。"""
        ...


def _load_engine():
    """导入并构造 RapidOCR 引擎（独立函数便于测试注入懒加载观察）。"""
    # RapidOCR 的 INFO 日志会写 stdout，压低到 ERROR 避免污染服务日志。
    logging.getLogger("RapidOCR").setLevel(logging.ERROR)
    from rapidocr import RapidOCR  # 延迟导入：未使用截图通道时不加载重依赖

    return RapidOCR()


class RapidOcrProvider:
    """默认实现：rapidocr（onnxruntime 后端，离线 CPU）。"""

    def __init__(self, min_confidence: float = DEFAULT_MIN_CONFIDENCE):
        """初始化 provider（不加载模型）。

        Args:
            min_confidence: 行列结构保留的置信度阈值。
        """
        self._min_confidence = min_confidence
        self._engine = None

    def _engine_or_load(self):
        """懒加载引擎；依赖缺失/加载失败统一转 ``OcrUnavailable``。"""
        if self._engine is None:
            try:
                self._engine = _load_engine()
            except Exception as exc:  # noqa: BLE001 - 依赖缺失/模型加载失败
                raise OcrUnavailable(
                    f"OCR 引擎不可用: {type(exc).__name__}"
                ) from exc
        return self._engine

    def recognize(self, image_bytes: bytes) -> OcrResult:
        """识别图片字节。

        Raises:
            OcrUnavailable: 引擎不可用（依赖缺失/加载失败）。
            OcrFailed: 未识别到文字或行列结构无法保留。
        """
        engine = self._engine_or_load()
        path = ""
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".png", delete=False
            ) as tmp:
                tmp.write(image_bytes)
                path = tmp.name
            try:
                raw = engine(path)
            except Exception as exc:  # noqa: BLE001 - 引擎执行失败
                raise OcrFailed(f"OCR 识别失败: {type(exc).__name__}") from exc
        finally:
            if path:
                Path(path).unlink(missing_ok=True)

        lines = [str(t) for t in (getattr(raw, "txts", None) or ()) if str(t).strip()]
        scores = [float(s) for s in (getattr(raw, "scores", None) or ())]
        if not lines:
            raise OcrFailed("OCR 未识别到文字，请改用文本或表格上传")
        confidence = sum(scores) / len(scores) if scores else 0.0
        structure_ok = confidence >= self._min_confidence
        if not structure_ok:
            raise OcrFailed(
                "OCR 识别置信度过低，行列结构无法保留，请改用文本或表格上传"
            )
        return OcrResult(
            text="\n".join(lines),
            structure_ok=structure_ok,
            confidence=confidence,
            lines=lines,
        )


# provider 注册表（可插拔；新增引擎在此登记）。
PROVIDER_FACTORIES = {
    "rapidocr": RapidOcrProvider,
}


def get_ocr_provider(
    enabled: bool, provider_name: str
) -> OCRProvider | None:
    """按配置取 provider；关闭或未知 provider 返回 None（截图通道降级）。"""
    if not enabled:
        return None
    factory = PROVIDER_FACTORIES.get(provider_name)
    if factory is None:
        return None
    return factory()
