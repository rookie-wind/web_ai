"""固定参考环境配置（阶段一模板生成的字典来源）。

参考环境与现场目标环境完全隔离：本模块只读取管理员显式提供的参考来源，
**不预置** 175 / 23 等任何地址、账号、密码，也不从上传工作簿或用户会话
推导参考地址（design §1）。

云端沿用 ``PCA_API_BASE_URL`` 与现有系统 Token 管理器；参考边缘采用独立
``XLPA_REFERENCE_EDGE_*`` 三件套，签名登录，与现场连接互不补位。
"""

from __future__ import annotations

__all__ = [
    "ReferenceConfig",
    "ReferenceConfigError",
    "load_reference_config",
]

import os
from dataclasses import dataclass

from api_client import API_BASE_URL

from .models import REDACTED


class ReferenceConfigError(Exception):
    """参考环境配置缺失或不完整。"""


@dataclass
class ReferenceConfig:
    """固定参考环境来源配置。

    Attributes:
        reference_edge_url: 参考边缘后端基地址（如 ``http://host:7500``）。
        reference_edge_login_name: 参考边缘登录账号。
        reference_edge_password: 参考边缘登录密码（敏感，不外泄）。
        cloud_base_url: 云端规约平台基地址（沿用 ``PCA_API_BASE_URL``）。
    """

    reference_edge_url: str = ""
    reference_edge_login_name: str = ""
    reference_edge_password: str = ""
    cloud_base_url: str = ""

    def edge_ready(self) -> bool:
        """参考边缘三件套是否齐备。"""
        return bool(
            self.reference_edge_url
            and self.reference_edge_login_name
            and self.reference_edge_password
        )

    def cloud_ready(self) -> bool:
        """云端基地址是否已配置。"""
        return bool(self.cloud_base_url)

    def require_edge(self) -> None:
        """校验参考边缘配置，缺失即报错（不补现场连接）。

        Raises:
            ReferenceConfigError: 参考边缘三件套不完整。
        """
        if not self.edge_ready():
            raise ReferenceConfigError(
                "参考边缘配置不完整：需 XLPA_REFERENCE_EDGE_URL / "
                "XLPA_REFERENCE_EDGE_LOGIN_NAME / XLPA_REFERENCE_EDGE_PASSWORD；"
                "系统不预置任何现场地址，也不以现场连接补位"
            )

    def require_cloud(self) -> None:
        """校验云端配置，缺失即报错。

        Raises:
            ReferenceConfigError: 云端基地址未配置。
        """
        if not self.cloud_ready():
            raise ReferenceConfigError(
                "参考云端配置不完整：需 PCA_API_BASE_URL"
            )

    def redacted(self) -> dict:
        """返回脱敏后的配置字典（密码掩码），供日志与报告。

        Returns:
            含各来源字段与掩码密码的字典。
        """
        return {
            "reference_edge_url": self.reference_edge_url,
            "reference_edge_login_name": self.reference_edge_login_name,
            "reference_edge_password": (
                REDACTED if self.reference_edge_password else ""
            ),
            "cloud_base_url": self.cloud_base_url,
        }


def load_reference_config(env: dict | None = None) -> ReferenceConfig:
    """从环境变量加载参考环境配置。

    Args:
        env: 显式环境映射（测试注入用）；为 None 时读 ``os.environ``。

    Returns:
        ReferenceConfig 实例。密码保留原文（不 strip），其余去空白。
    """
    src = os.environ if env is None else env
    cloud = str(src.get("PCA_API_BASE_URL", "") or "").strip() or API_BASE_URL
    return ReferenceConfig(
        reference_edge_url=str(
            src.get("XLPA_REFERENCE_EDGE_URL", "") or ""
        ).strip(),
        reference_edge_login_name=str(
            src.get("XLPA_REFERENCE_EDGE_LOGIN_NAME", "") or ""
        ).strip(),
        reference_edge_password=str(
            src.get("XLPA_REFERENCE_EDGE_PASSWORD", "") or ""
        ),
        cloud_base_url=cloud,
    )
