"""OCR provider 测试：懒加载、成功识别、失败显式抛错、配置降级。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from webchat import ocr as ocr_module
from webchat.ocr import (
    OcrFailed,
    OcrResult,
    OcrUnavailable,
    RapidOcrProvider,
    get_ocr_provider,
)


class _FakeEngine:
    """伪造引擎：记录被调用，返回固化结果。"""

    def __init__(self, txts=("hello",), scores=(0.9,)):
        self.txts = txts
        self.scores = scores
        self.calls = 0

    def __call__(self, path):
        self.calls += 1
        return SimpleNamespace(txts=self.txts, scores=self.scores)


def test_engine_is_lazy_loaded(monkeypatch):
    """构造 provider 不加载模型；首次 recognize 才加载。"""
    engine = _FakeEngine()
    loads: list[int] = []

    def fake_load():
        loads.append(1)
        return engine

    monkeypatch.setattr(ocr_module, "_load_engine", fake_load)
    provider = RapidOcrProvider()
    assert provider._engine is None
    assert loads == []  # 构造不加载

    result = provider.recognize(b"png-bytes")
    assert loads == [1]  # 首次调用才加载
    assert result.text == "hello"
    assert result.structure_ok is True
    assert result.confidence == pytest.approx(0.9)

    # 二次调用复用已加载引擎，不再重复加载
    provider.recognize(b"png-bytes")
    assert loads == [1]
    assert engine.calls == 2


def test_engine_load_failure_degrades(monkeypatch):
    """依赖缺失/加载失败 → OcrUnavailable（截图通道降级，不崩溃）。"""

    def broken_load():
        raise ImportError("onnxruntime missing")

    monkeypatch.setattr(ocr_module, "_load_engine", broken_load)
    with pytest.raises(OcrUnavailable):
        RapidOcrProvider().recognize(b"png-bytes")


def test_no_text_raises_explicit_failure(monkeypatch):
    """未识别到文字 → OcrFailed（显式失败，不静默猜测）。"""
    monkeypatch.setattr(ocr_module, "_load_engine", lambda: _FakeEngine(txts=()))
    with pytest.raises(OcrFailed):
        RapidOcrProvider().recognize(b"png-bytes")


def test_low_confidence_raises_structure_failure(monkeypatch):
    """置信度低于阈值 → OcrFailed，提示行列结构无法保留。"""
    monkeypatch.setattr(
        ocr_module, "_load_engine", lambda: _FakeEngine(scores=(0.2,))
    )
    with pytest.raises(OcrFailed) as exc:
        RapidOcrProvider().recognize(b"png-bytes")
    assert "行列结构" in str(exc.value)


def test_provider_factory_respects_config():
    """OCR 关闭或未知 provider → None（通道降级）。"""
    assert get_ocr_provider(False, "rapidocr") is None
    assert get_ocr_provider(True, "unknown") is None
    provider = get_ocr_provider(True, "rapidocr")
    assert isinstance(provider, RapidOcrProvider)


def test_provider_protocol_accepts_stub():
    """实现 recognize 的对象满足 OCRProvider 协议（可插拔）。"""

    class StubProvider:
        def recognize(self, image_bytes: bytes) -> OcrResult:
            return OcrResult(text="stub", structure_ok=True, confidence=1.0)

    assert isinstance(StubProvider(), ocr_module.OCRProvider)
