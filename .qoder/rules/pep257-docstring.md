---
trigger: always_on
---
# Python Docstring 规范

> 基于 PEP 257 + Google 风格，仅约束新增代码。
> 适用文件：`.py`

---

## 1. 基本规则

- 所有**公共**模块、函数、类、方法**必须**有 docstring。
- 非公共方法推荐有 docstring 或行内注释。
- 统一使用 `"""三双引号"""`。
- 若 docstring 含反斜杠，使用 `r"""raw triple double quotes"""`。
- 注释和 docstring 使用**中文**编写，标识符保持英文。

## 2. 单行 Docstring

- 适用于简短、显而易见的场景。
- 闭合引号与开头引号**同行**。
- 前后**无空行**。
- 以句号结尾，使用**祈使语气**（命令式）。
- **不要**重复函数签名（参数可通过内省获得）。

```python
# ✅
def get_token(self, ip: str) -> str:
    """为指定 IP 获取 Token。"""
    ...

# ❌ 不要重复签名
def get_token(self, ip: str) -> str:
    """get_token(ip: str) -> str"""
    ...

# ❌ 不要用描述式语气
def get_token(self, ip: str) -> str:
    """Returns the token for the given IP."""
    ...
```

## 3. 多行 Docstring

- 第一行：**摘要行**（同单行 docstring 规则）。
- 摘要行后接**1 空行**，再写详细描述。
- 闭合引号**独占一行**。
- 摘要行可以紧跟开头引号，也可以另起一行。

```python
def create_skills_zip() -> bytes:
    """将 Skills 目录打包为 ZIP 格式。

    遍历 .trae/skills/ 目录，跳过 __pycache__ 等临时目录，
    在内存中生成 ZIP 文件，无需手动压缩。
    返回 ZIP 文件的字节数据。
    """
    ...
```

## 4. Google 风格参数文档

使用 `Args:` / `Returns:` / `Raises:` / `Yields:` / `Note:` 等段落标签。
每个段落标签后缩进 4 空格描述参数。

### 函数 / 方法

```python
def add_device_class(brand: str, model: str, info: str = "") -> dict:
    """写入运维平台品牌、型号数据。

    Args:
        brand: 品牌名称（必填）。
        model: 型号名称（必填）。
        info: 附加信息（可选）。

    Returns:
        包含状态信息的字典。写入成功时返回结果字典，
        权限不足时返回错误字典。

    Raises:
        ValueError: 当 brand 或 model 为空时。
    """
    ...
```

### 段落标签一览

| 标签 | 用途 | 必需 |
|------|------|------|
| `Args:` | 参数说明 | 有参数时推荐 |
| `Returns:` | 返回值说明 | 有返回值时推荐 |
| `Yields:` | 生成器产出 | 生成器函数使用 |
| `Raises:` | 异常说明 | 可能抛出异常时推荐 |
| `Note:` | 补充说明 | 可选 |
| `Example:` | 使用示例 | 可选 |
| `Warning:` | 警告信息 | 可选 |

## 5. 类 Docstring

- 在 `class` 层级写**概述**，描述类的职责和行为。
- 列出公共属性和方法。
- 构造参数写在 `__init__` 的 docstring 中（或类 docstring 的 `Args:` 段）。
- 类 docstring 后接**1 空行**再写第一个方法。
- 如果类 intended 被继承，说明子类接口。

```python
class TokenManager:
    """管理 Token 的生成、验证和 IP 关联。

    - localhost: 使用管理员 Token（MCP_AUTH_TOKEN），系统级权限。
    - 非 localhost: 自动生成 Token，用户级权限（只读）。
    - Token 存储在内存中，服务器重启后重新生成。
    """

    def __init__(self, admin_token: str = ""):
        """初始化 Token 管理器。

        Args:
            admin_token: 管理员 Token，为空则所有 IP 自动生成。
        """
        ...
```

## 6. 模块 Docstring

- 每个 `.py` 文件顶部**必须**有模块 docstring。
- 概述模块的功能和职责。
- 可列出模块导出的主要类 / 函数 / 异常。

```python
"""协议转换 MCP Server。

基于 FastMCP 实现，提供工具注册、鉴权中间件和接入页面。
"""
```

## 7. 包 Docstring

- 包的 `__init__.py` 中写包级 docstring。
- 列出包导出的模块和子包。

## 8. 格式细节

- 段落之间用**1 空行**分隔。
- 参数名使用**实际参数名**（不要用大写或别的名字）。
- 可选参数标注默认值。
- 类型信息通过类型注解表达，docstring 中**不重复**类型（Google 风格不要求 `:type` 标记）。

```python
# ✅ 类型由注解表达，docstring 只写说明
def query(name: str, limit: int = 10) -> list[dict]:
    """查询设备列表。

    Args:
        name: 设备名称。
        limit: 返回数量上限。

    Returns:
        设备信息字典列表。
    """
    ...
```

## 9. 特殊场景

### 属性 Docstring

- 简单属性不需要 docstring。
- 复杂属性可在赋值后紧跟字符串字面量作为"属性 docstring"。

### 覆写方法

- 子类覆写方法时，docstring 应说明与父类的差异。
- 使用"覆写"表示不调用父类方法，"扩展"表示在父类基础上增加行为。

### 桩函数 / 待实现

- 桩函数 docstring 应标注状态为 `stub` 或说明待实现。

```python
def query_device_classes(brand: str = "", model: str = "", tag: str = "") -> dict:
    """查询运维平台品牌、型号、原子标签。

    .. status:: stub

    Args:
        brand: 品牌名称（可选，为空则查全部）。
        model: 型号名称（可选，为空则查全部）。
        tag: 原子标签（可选，为空则查全部）。
    """
    ...
```
