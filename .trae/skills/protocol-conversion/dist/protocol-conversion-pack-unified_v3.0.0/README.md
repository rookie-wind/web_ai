# 统一协议映射引擎 v3.0.0

## 概述

将 MQTT 引擎 (`json_mapper.c`) 和 HTTP 引擎 (`http_json_mapper.c`) 的协议映射代码合并为一份共享代码 `mapper_core.c`。

## 包内容

```
protocol-conversion-pack-unified_v3.0.0/
├── protocol-conversion/
│   ├── SKILL.md                          ← 共享映射核心定义
│   ├── agents/openai.yaml
│   ├── defaults/internal_mqtt_protocol.json
│   └── scripts/
│       ├── mapper_core.h                 ← 统一 C 映射引擎头文件
│       ├── mapper_core.c                 ← 统一 C 映射引擎实现
│       ├── protocol_converter.py         ← Python 镜像（测试用）
│       ├── test_protocol_converter.py    ← 完备测试套件（91 项）
│       ├── gen_test_report.py            ← 测试报告生成器
│       └── test_report.json              ← 测试结果报告
├── mqtt-conversion/
│   ├── SKILL.md                          ← MQTT 特有逻辑
│   └── agents/openai.yaml
├── http-conversion/
│   ├── SKILL.md                          ← HTTP 特有逻辑
│   └── agents/openai.yaml
├── pc/
│   ├── SKILL.md                          ← 路由入口
│   └── agents/openai.yaml
├── mapping_report.md                     ← 映射设计报告
├── manifest.json                         ← 包清单（含校验和）
└── README.md                             ← 本文件
```

## 引擎架构

```
MQTT: config_loader.c (加载) → mapper_core.c (映射) → 输出平台MQTT消息
HTTP: vpp_http_config.load.c (加载) → mapper_core.c (映射) → 输出内部MQTT消息
```

两种协议共用 `mapper_core.c` 作为映射执行引擎，差异仅在配置加载层。

## 安装

### 1. 复制 Skill 文件

将 `protocol-conversion/`、`mqtt-conversion/`、`http-conversion/`、`pc/` 目录复制到 `.trae/skills/` 下。

### 2. 复制 C 引擎文件

将 `mapper_core.h` 和 `mapper_core.c` 复制到 C 项目中，替代原有的 `json_mapper.c` 和 `http_json_mapper.c`。

### 3. 更新引用

- MQTT 项目中：`#include "json_mapper.h"` → `#include "mapper_core.h"`
- HTTP 项目中：`#include "json_mapper.h"` → `#include "mapper_core.h"`

### 4. 运行测试

```bash
cd protocol-conversion/scripts
python -m unittest test_protocol_converter -v
```

## 测试结果

- 测试时间：2026-08-20T00:00:00Z
- 通过：89/91
- 跳过：2（真实配置文件路径不存在）
- 状态：**PASSED**

## 统一的 9 个核心函数

| 函数 | 说明 |
|------|------|
| `get_value_by_path` | 按 JSON 路径取值（支持 `.`/`[index]`/`[*]`/`.`根对象） |
| `ensure_path` | 确保目标路径存在 |
| `add_value_to_parent` | 类型转换并添加到父对象（7种类型+scale） |
| `generate_value` | 调用生成器（uuid/timestamp/datetime/md5等） |
| `template_substitute` | 模板变量替换（MQTT特有） |
| `process_rule` | 统一规则处理入口 |
| `process_array_foreach` | 数组遍历处理（object+key_value） |
| `process_normal_field` | 普通字段处理 |
| `get_flat_array_from_path` | 嵌套[*]展平（MQTT特有） |

## Skill 职责分配

| Skill | 职责 |
|-------|------|
| protocol-conversion | 共享映射规则（路径语法、类型系统、数组遍历、生成器） |
| mqtt-conversion | MQTT 特有（substitute/$item/$idx/嵌套[*]/post_process） |
| http-conversion | HTTP 特有（context/key_value/"."源路径/preprocess/链式调用） |
| pc | 路由入口，分发到对应 skill |

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 3.0.0 | 2026-08-20 | 统一映射引擎，合并 MQTT+HTTP 映射代码 |
