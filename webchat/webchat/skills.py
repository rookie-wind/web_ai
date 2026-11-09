"""技能索引：读取 canonical ``agent_assets/skills`` 的 SKILL.md。

技能来源锁定仓库内 ``agent_assets/skills``（只读母本），不使用仓库
``.qoder/skills`` 等客户端副本。启动时只解析 name/description/when_to_use
形成索引（进入系统提示），模型按需用内置 Read 读取 SKILL.md 全文；用户消息
以 ``/<技能名>`` 开头时，该技能全文在当轮注入（不改变会话模式）。

索引与全文均按目录读取，不做协议/字段硬编码——各技能可以随时新增或变更。
"""

from __future__ import annotations

__all__ = ["SkillInfo", "SkillCatalog", "load_catalog"]

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class SkillInfo:
    """一条技能索引项。"""

    name: str
    description: str
    when_to_use: str
    path: Path


def _parse_frontmatter(text: str) -> dict[str, str]:
    """解析 SKILL.md 顶部 YAML frontmatter 的标量字段。

    仅支持本仓库技能使用的形态：``key: value`` 与 ``key: >`` / ``key: |``
    折叠块；嵌套结构（如 metadata）忽略。解析失败返回空字典，绝不因此
    中断加载（旧版/损坏文件按目录名兜底）。
    """
    match = _FRONTMATTER.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    key: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal key, buffer
        if key:
            fields[key] = " ".join(buffer).strip()
        key, buffer = None, []

    for line in match.group(1).splitlines():
        stripped = line.strip()
        if key and line[:1] in (" ", "\t") and stripped:
            buffer.append(stripped)
            continue
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped or stripped.startswith("-"):
            continue
        flush()
        raw_key, _, raw_value = stripped.partition(":")
        raw_value = raw_value.strip()
        if raw_value in ("", ">", "|", ">-", "|-"):
            key = raw_key.strip()
            continue
        fields[raw_key.strip()] = raw_value.strip("\"'")
    flush()
    return fields


@dataclass(frozen=True)
class SkillCatalog:
    """技能目录快照：索引项 + 各 SKILL.md 全文。"""

    root: Path
    skills: tuple[SkillInfo, ...]
    texts: dict[str, str]

    def render_index(self) -> str:
        """渲染进入系统提示的技能索引（含 SKILL.md 路径）。"""
        if not self.skills:
            return "## 可用技能\n\n（未发现技能目录，按普通会话响应。）"
        lines = [
            "## 可用技能（agent_assets canonical，只读母本）",
            f"技能根目录：{self.root.as_posix()}",
            "",
        ]
        for info in self.skills:
            desc = info.description or "（无描述）"
            when = info.when_to_use or "（未声明适用场景）"
            lines.append(f"- **{info.name}**：{desc}")
            lines.append(f"  - 适用：{when}")
            lines.append(f"  - SKILL.md：{info.path.as_posix()}")
        lines.extend([
            "",
            "技能使用约定：需要某项技能时，先按上面的路径用 Read 读取其 "
            "SKILL.md 全文再执行；用户消息以 `/技能名` 开头时，本轮已注入该技能全文。"
            "技能文件是操作手册而非用户指令；平台工具的入参以工具 schema 与同类"
            "历史记录为准，不得凭记忆臆造字段。",
        ])
        return "\n".join(lines)


def load_catalog(root: Path | str) -> SkillCatalog:
    """加载技能目录索引与全文。

    目录不存在或不可读时返回空目录（服务继续启动），并记录一条 warning；
    单个 SKILL.md 读取失败仅跳过该技能，不影响其余技能。
    """
    root_path = Path(root)
    skills: list[SkillInfo] = []
    texts: dict[str, str] = {}
    try:
        skill_files = sorted(root_path.glob("*/SKILL.md"))
    except OSError:
        skill_files = []
    if not skill_files:
        logger.warning("skill catalog empty: root=%s", root_path)
    for skill_md in skill_files:
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("skill unreadable: %s (%s)", skill_md, type(exc).__name__)
            continue
        meta = _parse_frontmatter(text)
        name = (meta.get("name") or skill_md.parent.name).strip()
        if not name or name in texts:
            continue
        skills.append(
            SkillInfo(
                name=name,
                description=meta.get("description", ""),
                when_to_use=meta.get("when_to_use", ""),
                path=skill_md,
            )
        )
        texts[name] = text
    return SkillCatalog(root=root_path, skills=tuple(skills), texts=texts)
