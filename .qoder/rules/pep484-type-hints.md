---
trigger: always_on
---
# Python 类型注解规范

> 基于 PEP 484 裁剪，使用 Python 3.9+ 现代语法。
> 仅约束新增代码，推荐但不强制所有代码都标注。
> 适用文件：`.py`

---

## 1. 基本原则

- 类型注解是**推荐**的，不是强制的。
- **公共 API**（公共函数、类方法、模块级函数）**强烈建议**添加完整类型注解。
- 内部辅助函数（`_` 前缀）推荐添加，至少标注返回值。
- 类型检查器（mypy 等）是可选工具，不应影响运行时行为。
- 不使用 `# type: ignore` 除非确实无法避免，并附注释说明原因。

## 2. 函数注解

### 参数注解

- 格式：`param: Type`，冒号后**1 空格**。
- 有默认值且有注解时：`param: Type = default`，`=` 两侧各**1 空格**。

```python
# ✅
def query(brand: str, model: str = "", limit: int = 10) -> list[dict]:
    ...

# ❌ 冒号后无空格
def query(brand:str, model:str = "") -> list[dict]:
    ...

# ❌ 有注解时 = 两侧无空格
def query(brand: str, model: str="") -> list[dict]:
    ...
```

### 返回值注解

- **必须**标注返回值类型。
- 无返回值使用 `-> None`。

```python
# ✅
def get_token(self, ip: str) -> str:
    ...

def log_info(msg: str) -> None:
    ...

# ❌ 缺少返回值注解
def get_token(self, ip: str):
    ...
```

### 无注解参数

- 参数无注解且有默认值时，`=` 两侧**不空格**：

```python
# ✅ 无注解，= 两侧无空格
def complex(real, imag=0.0):
    ...

# ❌ 无注解但 = 两侧有空格
def complex(real, imag = 0.0):
    ...
```

## 3. 现代类型语法（Python 3.9+ / 3.10+）

使用内置泛型替代 `typing` 模块中的对应类型：

| 旧写法（typing） | 新写法（推荐） | Python 版本 |
|-------------------|----------------|-------------|
| `List[int]` | `list[int]` | 3.9+ |
| `Dict[str, int]` | `dict[str, int]` | 3.9+ |
| `Tuple[int, str]` | `tuple[int, str]` | 3.9+ |
| `Set[str]` | `set[str]` | 3.9+ |
| `FrozenSet[str]` | `frozenset[str]` | 3.9+ |
| `Type[X]` | `type[X]` | 3.9+ |
| `Optional[X]` | `X \| None` | 3.10+ |
| `Union[X, Y]` | `X \| Y` | 3.10+ |

```python
# ✅ 推荐 — 现代语法
def get_ips() -> list[str]:
    ...

def get_config() -> dict[str, str | None]:
    ...

def find_item(name: str) -> dict | None:
    ...

# ❌ 避免 — 旧式 typing 写法
from typing import List, Dict, Optional, Union

def get_ips() -> List[str]:
    ...

def get_config() -> Dict[str, Optional[str]]:
    ...
```

### 例外

以下场景仍使用 `typing` 模块：

- `TypeVar`、`ParamSpec`、`TypeAlias` 等无内置替代的符号。
- `Literal`、`Final`、`Annotated` 等（Python 3.10 中仍在 typing 中）。
- `TYPE_CHECKING` 常量用于条件导入避免循环依赖。

```python
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from some_module import SomeClass

T = TypeVar("T")
```

## 4. 变量注解

- 模块级变量、类属性**推荐**添加类型注解。
- 格式：`name: Type`，冒号后 1 空格，冒号前无空格。
- 有赋值时：`name: Type = value`，`=` 两侧各 1 空格。

```python
# ✅
MAX_RETRIES: int = 3
HOST: str
ip_tokens: dict[str, str] = {}

class Point:
    coords: tuple[int, int]
    label: str = "<unknown>"

# ❌
MAX_RETRIES:int = 3      # 冒号后无空格
HOST : str               # 冒号前有空格
ip_tokens: dict[str,str]= {}  # = 两侧无空格
```

- 局部变量类型注解仅在类型不明显时推荐添加。

```python
# ✅ 类型明显，不需要注解
name = "hello"
count = 0
items = []

# ✅ 类型不明显，推荐注解
result: dict[str, list[int]] = parse_data(raw)
```

## 5. 注解格式细节

- `->` 两侧各 1 空格：`def f() -> str:` ✅
- 多参数跨行时，每个参数独占一行并缩进：

```python
# ✅ 跨行注解
def long_function_name(
    var_one: str,
    var_two: int,
    var_three: dict[str, str] = {},
) -> tuple[bool, str]:
    ...
```

- 闭括号可对齐首参数或对齐首字符，保持一致即可。

## 6. 回调类型

使用 `Callable` 标注回调函数类型：

```python
from collections.abc import Callable

def register_handler(
    name: str,
    callback: Callable[[str, int], bool],
) -> None:
    ...
```

- `Callable[[ArgType1, ArgType2], ReturnType]`
- 参数类型列表为 `list`，返回类型为第二项。
- 不确定参数时使用 `Callable[..., ReturnType]`。

## 7. 泛型与 TypeVar

- TypeVar 使用 CapWords 短名：`T`, `T_co`, `KT_contra`。
- 协变加 `_co` 后缀，逆变加 `_contra` 后缀。

```python
from typing import TypeVar

T = TypeVar("T")
VT_co = TypeVar("VT_co", covariant=True)
KT_contra = TypeVar("KT_contra", contravariant=True)
```

## 8. 前向引用

- 当类型尚未定义时，使用字符串字面量或 `from __future__ import annotations`：

```python
# ✅ 方式一：from __future__（推荐，文件顶部添加）
from __future__ import annotations

class Node:
    def add_child(self, child: Node) -> None:
        ...

# ✅ 方式二：字符串字面量
class Node:
    def add_child(self, child: "Node") -> None:
        ...
```

## 9. 与 Docstring 的协作

- 类型信息通过注解表达，docstring 中**不重复**类型。
- 参见 `pep257-docstring.md` 第 8 节。

```python
# ✅ 注解表达类型，docstring 表达语义
def query(brand: str, limit: int = 10) -> list[dict]:
    """查询设备列表。

    Args:
        brand: 品牌名称。
        limit: 返回数量上限。

    Returns:
        设备信息字典列表。
    """
    ...
```

## 10. 渐进式标注策略

对于已有代码的渐进式标注，推荐优先级：

1. **最高**：新写的公共函数 / 方法 — 完整注解。
2. **次高**：修改已有函数时 — 补充注解。
3. **推荐**：内部辅助函数 — 至少标注返回值。
4. **可选**：局部变量 — 仅在类型复杂时。
