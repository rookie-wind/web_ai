"""免模板下发：从档案组装 20200002 itemBody 的单元测试。

字段来源对齐 profile；commAddr 必需、authParam 归一、可选留空不虚构。
"""

from __future__ import annotations

import pytest

import edge_tools as tools
from archiving.converter import validate_device_address
from edge_client import EdgeApiError


def _record(**over) -> dict:
    rec = {
        "deviceAddress": "003899001899",
        "agentNum": "1",
        "measuredPointNum": "1",
        "protocolNumber": "200",
        "proxyCommPort": "40",
        "collectorAddress": "24e124538f389724",
        "extInfos": [
            {"propertyCode": "authParam", "propertyValue": "192,168,23,150,21883"},
            {"propertyCode": "decimalNum", "propertyValue": "418"},
            {"propertyCode": "userBigNo", "propertyValue": "18"},
            {"propertyCode": "userSmallNo", "propertyValue": "1"},
            {"propertyCode": "feeNum", "propertyValue": ""},
        ],
    }
    rec.update(over)
    return rec


def test_build_from_archive_maps_fields(monkeypatch) -> None:
    """档案现值→itemBody：commAddr/roadNo/authParam(hex)/integerNum 默认 6。"""
    monkeypatch.setattr(tools, "_read_device_record", lambda s, d: _record())
    body = tools._build_deploy_body_from_archive(object(), "DEV")
    assert body["commAddr"] == validate_device_address("003899001899")
    assert body["roadNo"] == 1 and body["measurNo"] == 1
    assert body["protocolCode"] == 200 and body["comPort"] == 40
    assert body["decimalNum"] == 418 and body["userBigNo"] == 18 and body["userSmallNo"] == 1
    assert body["integerNum"] == 6
    assert body["authParam"] == "c0a81796557b"  # 192.168.23.150:21883
    assert body["collCommAddr"] == "24e124538f389724"
    assert body["feeNum"] == 1  # 档案 feeNum 空→对齐页面默认 1（避免 RTU DENY）
    assert "deviceId" not in body


def test_build_from_archive_missing_commaddr_raises(monkeypatch) -> None:
    """commAddr 缺失时抛错，交调用方跳过该台。"""
    monkeypatch.setattr(
        tools, "_read_device_record", lambda s, d: _record(deviceAddress=""),
    )
    with pytest.raises(EdgeApiError):
        tools._build_deploy_body_from_archive(object(), "DEV")


def test_build_from_archive_optional_defaults(monkeypatch) -> None:
    """collectorAddress 空→collCommAddr 占位；无 authParam→占位全 E。"""
    rec = _record(collectorAddress="", extInfos=[])
    monkeypatch.setattr(tools, "_read_device_record", lambda s, d: rec)
    body = tools._build_deploy_body_from_archive(object(), "DEV")
    assert body["collCommAddr"] == "000000000000"
    assert body["authParam"] == "EEEEEEEEEEEE"
    assert body["feeNum"] == 1
