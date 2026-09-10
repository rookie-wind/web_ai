---
trigger: always_on
---
# Python 编码风格与命名规范

> 基于 PEP 8 裁剪，仅约束新增代码，存量代码不要求整改。
> 适用文件：`.py`

---

## 1. 缩进与行长度

- **缩进**：4 个空格，禁止 Tab。
- **代码行长度**：最大 99 字符。
- **注释 / Docstring 行长度**：最大 72 字符。
- 当行超长时，优先使用括号内隐式续行；避免反斜杠续行（`with` 多语句等例外）。
- 二元运算符换行时，推荐在运算符**前**断行（Knuth 风格）。

```python
# ✅ 推荐 — 运算符前断行
income = (gross_wages
          + taxable_interest
          + (dividends - qualified_dividends)
          - ira_deduction
          - student_loan_interest)

# ❌ 避免 — 运算符后断行
income = (gross_wages +
          taxable_interest +
          (dividends - qualified_dividends) -
          ira_deduction -
          student_loan_interest)
```

## 2. 空行

- 顶层函数 / 类定义之间：**2 空行**。
- 类内方法定义之间：**1 空行**。
- 函数内部可用空行分隔逻辑段落，但要**节制**。

## 3. 字符串

- 普通字符串和 docstring 统一使用**双引号** `"`。
- Docstring 统一使用 `"""三双引号"""`。
- 字符串内含单引号时用双引号包裹，反之亦然，避免反斜杠转义。

```python
# ✅
name = "protocol-converter"
msg = "it's a test"
doc = """Return the result."""

# ❌
name = 'protocol-converter'
msg = 'it\'s a test'
```

## 4. 空白使用

- 避免括号 / 方括号 / 花括号**内侧**的多余空白：`spam(ham[1], {eggs: 2})` ✅
- 逗号、分号、冒号**前**不空格。
- 函数调用 `(` 前不空格：`spam(1)` ✅
- 索引 `[` 前不空格：`dct['key']` ✅
- 赋值 `=` 两侧不空格（无注解参数）：`def f(real, imag=0.0)` ✅
- 有注解的参数，`=` 两侧空格：`def f(sep: str = None)` ✅
- 二元运算符两侧**一个空格**：`x = x + 1` ✅
- 禁止用多空格对齐赋值：

```python
# ✅
x = 1
y = 2
long_variable = 3

# ❌
x             = 1
y             = 2
long_variable = 3
```

- 禁止行尾空白。

## 5. 尾部逗号

- 多行列表 / 字典 / 参数列表**推荐**尾部逗号，便于 git diff 扩展。

```python
# ✅ 推荐
FILES = [
    "setup.cfg",
    "tox.ini",
]
```

- 单元素元组必须尾部逗号：`FILES = ("setup.cfg",)`

## 6. 复合语句

- **禁止**同行多语句（`if foo: do()` / `do(); do2()` 等）。
- `if` / `for` / `while` 即使体很短也不建议写在一行。

## 7. 注释

- 注释使用**中文**，标识符保持英文原样。
- 块注释与代码同级缩进，每行以 `# ` 开头。
- 行内注释**节制使用**，与语句至少隔 2 空格，以 `# ` 开头。
- 不要写"显而易见"的行内注释。
- 注释与代码矛盾比没有注释更糟 — 修改代码时**务必同步更新注释**。

## 8. Import

- 每个 import 独占一行：`import os` / `import sys` ✅（非 `import sys, os`）。
- 位于文件顶部，模块 docstring 之后、全局变量之前。
- 分组顺序（组间 1 空行）：
  1. 标准库
  2. 第三方库
  3. 本地 / 项目内
- 优先使用**绝对导入**。
- 禁止 `from module import *`。

## 9. 命名规范

| 对象类型 | 规则 | 示例 |
|----------|------|------|
| 模块 / 包 | 全小写，可用下划线 | `server.py`, `mapper_core.py` |
| 类 | CapWords（驼峰） | `TokenManager`, `AuthMiddleware` |
| 异常类 | CapWords + `Error` 后缀 | `AuthenticationError` |
| 函数 / 方法 | snake_case | `list_mcp_tools`, `get_token_info` |
| 变量 | snake_case | `access_level_var`, `token_manager` |
| 常量（模块级） | UPPER_CASE + 下划线 | `LOCALHOST_IPS`, `WRITE_TOOLS` |
| 内部函数 / 变量 | `_` 前缀 + snake_case | `_stub_response`, `_get_client_ip` |
| 实例方法首参 | `self` | — |
| 类方法首参 | `cls` | — |
| TypeVar | CapWords，短名 | `T`, `AnyStr` |

### 命名禁区

- 禁止使用 `l`（小写 L）、`O`（大写 O）、`I`（大写 i）作为单字符变量名。

### 继承设计

- 公开属性：无前缀。
- 非公开属性：单 `_` 前缀。
- 仅当需要避免子类名称冲突时使用 `__` 双前缀（name mangling）。

## 10. 编程建议

- `None` 比较必须使用 `is` / `is not`，禁止 `==`。
- 使用 `is not` 而非 `not ... is`。
- 使用 `def` 而非 `lambda` 赋值：`def f(x): return 2*x` ✅
- 异常继承自 `Exception` 而非 `BaseException`。
- `except` 子句尽量指定具体异常类型，避免裸 `except:`。
- `try` 块内只放可能抛出目标异常的最少代码。
- 资源管理优先使用 `with` 语句。
- `return` 保持一致：要么都返回值，要么显式 `return None`。
- 前缀 / 后缀检查使用 `str.startswith()` / `str.endswith()` 而非切片。
- 类型检查使用 `isinstance()` 而非 `type()` 比较。
- 空序列检查直接用真值测试：`if not seq:` ✅（非 `if not len(seq):`）。
- 禁止布尔值与 `True` / `False` 用 `==` 比较。

## 11. 模块级 Dunder

- `__all__`、`__version__`、`__author__` 等放在模块 docstring 之后、`import` 之前（`from __future__` 除外）。

```python
"""模块概述。"""

from __future__ import annotations

__all__ = ["MyClass"]
__version__ = "0.1.0"

import os
import sys
```
