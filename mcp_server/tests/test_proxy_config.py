"""门户代理配置加载器单元测试。

覆盖 `edge_proxy_config.portal_proxy_api_url()` 的分支：
配置存在且有值 / 配置缺失 / 配置损坏 / 配置为空值 / env 回退 / env 覆盖路径。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from edge_proxy_config import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    _CONFIG_PATH_ENV,
    _LEGACY_ENV,
    _load_from_file,
    portal_proxy_api_url,
)


def _write(path: Path, obj) -> None:
    """写入 JSON 配置（含父子目录自动创建）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


class TestLoadFromFile:
    """_load_from_file：配置文件存在/损坏/缺失/空值的解析。"""

    def test_valid_url(self, tmp_path):
        p = tmp_path / "proxy_config.json"
        _write(p, {"proxy_api_url": "http://121.229.15.116:7500"})
        assert _load_from_file(p) == "http://121.229.15.116:7500"

    def test_invalid_json_returns_empty(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{ not json", encoding="utf-8")
        assert _load_from_file(p) == ""

    def test_non_dict_returns_empty(self, tmp_path):
        p = tmp_path / "list.json"
        _write(p, ["a", "b"])
        assert _load_from_file(p) == ""

    def test_empty_value_returns_empty(self, tmp_path):
        p = tmp_path / "empty.json"
        _write(p, {"proxy_api_url": "   "})
        assert _load_from_file(p) == ""

    def test_missing_file_returns_empty(self, tmp_path):
        assert _load_from_file(tmp_path / "nope.json") == ""


class TestPortalProxyApiUrl:
    """portal_proxy_api_url：配置文件优先，env 为回退，路径可 env 覆盖。"""

    def test_config_file_priority_over_env(self, tmp_path, monkeypatch):
        p = tmp_path / "c.json"
        _write(p, {"proxy_api_url": "http://cfg.example:7500"})
        monkeypatch.setenv(_CONFIG_PATH_ENV, str(p))
        monkeypatch.setenv(_LEGACY_ENV, "http://legacy.example:7500")
        assert portal_proxy_api_url() == "http://cfg.example:7500"

    def test_env_fallback_when_config_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv(_CONFIG_PATH_ENV, str(tmp_path / "missing.json"))
        monkeypatch.setenv(_LEGACY_ENV, "http://legacy.example:7500")
        assert portal_proxy_api_url() == "http://legacy.example:7500"

    def test_env_fallback_when_config_empty(self, tmp_path, monkeypatch):
        p = tmp_path / "c.json"
        _write(p, {"proxy_api_url": ""})
        monkeypatch.setenv(_CONFIG_PATH_ENV, str(p))
        monkeypatch.setenv(_LEGACY_ENV, "http://legacy.example:7500")
        assert portal_proxy_api_url() == "http://legacy.example:7500"

    def test_only_env_gives_value(self, monkeypatch):
        # 明确指向不存在的配置路径 → 走 env
        monkeypatch.setenv(_CONFIG_PATH_ENV, str(Path("/nonexistent/x.json")))
        monkeypatch.setenv(_LEGACY_ENV, "http://legacy.example:7500")
        assert portal_proxy_api_url() == "http://legacy.example:7500"

    def test_neither_configured_returns_empty(self, monkeypatch):
        monkeypatch.delenv(_CONFIG_PATH_ENV, raising=False)
        monkeypatch.setenv(_CONFIG_PATH_ENV, str(Path("/nonexistent/y.json")))
        monkeypatch.delenv(_LEGACY_ENV, raising=False)
        assert portal_proxy_api_url() == ""

    def test_repo_config_file_present_with_value(self):
        """仓库内 proxy_config.json 存在且非空（服务端开箱即用）。"""
        assert DEFAULT_CONFIG_PATH.exists()
        url = _load_from_file(DEFAULT_CONFIG_PATH)
        assert url == "http://121.229.15.116:7500"