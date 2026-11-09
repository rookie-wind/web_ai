"""C5 配置解析测试：上传上限、保留天数、OCR 开关与下载 grant TTL。"""

from __future__ import annotations

import pytest

from webchat.config import SettingsError, load_settings

MB = 1024 * 1024


def _base_env(**overrides) -> dict[str, str]:
    """最小可加载环境（仅 mint secret 为必填项）。"""
    env = {"WEBCHAT_MINT_SECRET": "test-secret"}
    env.update(overrides)
    return env


def test_artifact_settings_defaults():
    """未配置时取约定默认值：10/10/20 MB、30/30/30/7 天、OCR 开、grant 120s。"""
    settings = load_settings(_base_env())
    assert settings.upload_max_table_bytes == 10 * MB
    assert settings.upload_max_image_bytes == 10 * MB
    assert settings.upload_max_document_bytes == 20 * MB
    assert settings.retention_input_days == 30
    assert settings.retention_result_days == 30
    assert settings.retention_template_days == 30
    assert settings.retention_sensitive_temp_days == 7
    assert settings.retention_sweep_interval == 3600
    assert settings.ocr_enabled is True
    assert settings.ocr_provider == "rapidocr"
    assert settings.download_grant_ttl == 120


def test_capacity_settings_defaults():
    """容量与生命周期默认值：100 全局 / 5 单人 / 30min 空闲 / 16 并发轮次。"""
    settings = load_settings(_base_env())
    assert settings.max_instances == 100
    assert settings.max_sessions_per_user == 5
    assert settings.session_idle_ttl == 1800
    assert settings.idle_sweep_interval == 60
    assert settings.max_concurrent_turns == 16


def test_read_extra_roots_default_and_env_append(tmp_path):
    """Read 额外白名单默认含 CLI 落盘目录，环境变量继续追加（逗号/分号）。"""
    settings = load_settings(_base_env())
    defaults = {str(p).replace("/", "\\").lower() for p in settings.read_extra_roots}
    assert any("qoder-mcp-outputs" in p for p in defaults)
    assert any(".qoder-cn" in p and "tmp" in p for p in defaults)

    first = tmp_path / "extra-a"
    second = tmp_path / "extra-b"
    merged = load_settings(_base_env(
        WEBCHAT_READ_EXTRA_ROOTS=f"{first},{second}"
    ))
    assert first in merged.read_extra_roots
    assert second in merged.read_extra_roots
    assert len(merged.read_extra_roots) == len(settings.read_extra_roots) + 2


def test_agent_model_default_and_override():
    """CLI 模型默认 Qwen3.8-Flash，可经 WEBCHAT_AGENT_MODEL 覆盖/置空。"""
    settings = load_settings(_base_env())
    assert settings.agent_model == "Qwen3.8-Flash"
    overridden = load_settings(_base_env(WEBCHAT_AGENT_MODEL="other-model"))
    assert overridden.agent_model == "other-model"
    empty = load_settings(_base_env(WEBCHAT_AGENT_MODEL=""))
    assert empty.agent_model == ""


def test_artifact_settings_env_overrides():
    """环境变量可覆盖上限/保留/OCR/grant TTL。"""
    settings = load_settings(_base_env(
        WEBCHAT_UPLOAD_MAX_TABLE_MB="5",
        WEBCHAT_UPLOAD_MAX_IMAGE_MB="3",
        WEBCHAT_UPLOAD_MAX_DOC_MB="8",
        WEBCHAT_RETENTION_INPUT_DAYS="12",
        WEBCHAT_RETENTION_SENSITIVE_TEMP_DAYS="2",
        WEBCHAT_RETENTION_SWEEP_INTERVAL="60",
        WEBCHAT_OCR_ENABLED="0",
        WEBCHAT_OCR_PROVIDER="stub",
        WEBCHAT_DOWNLOAD_GRANT_TTL="30",
    ))
    assert settings.upload_max_table_bytes == 5 * MB
    assert settings.upload_max_image_bytes == 3 * MB
    assert settings.upload_max_document_bytes == 8 * MB
    assert settings.retention_input_days == 12
    assert settings.retention_sensitive_temp_days == 2
    assert settings.retention_sweep_interval == 60
    assert settings.ocr_enabled is False
    assert settings.ocr_provider == "stub"
    assert settings.download_grant_ttl == 30


@pytest.mark.parametrize(
    "key,value",
    [
        ("WEBCHAT_UPLOAD_MAX_TABLE_MB", "0"),
        ("WEBCHAT_UPLOAD_MAX_DOC_MB", "-1"),
        ("WEBCHAT_UPLOAD_MAX_IMAGE_MB", "abc"),
        ("WEBCHAT_RETENTION_INPUT_DAYS", "0"),
        ("WEBCHAT_RETENTION_SENSITIVE_TEMP_DAYS", "x"),
        ("WEBCHAT_RETENTION_SWEEP_INTERVAL", "0"),
        ("WEBCHAT_OCR_ENABLED", "maybe"),
        ("WEBCHAT_OCR_PROVIDER", "   "),
        ("WEBCHAT_DOWNLOAD_GRANT_TTL", "0"),
    ],
)
def test_artifact_settings_invalid_values_raise(key, value):
    """非法配置值一律抛 SettingsError（启动即失败，不带病运行）。"""
    with pytest.raises(SettingsError):
        load_settings(_base_env(**{key: value}))
