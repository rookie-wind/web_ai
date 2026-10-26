/**
 * mapper_core.h — 统一协议映射核心引擎
 *
 * 合并 json_mapper.c (MQTT) 和 http_json_mapper.c (HTTP) 的共享映射逻辑。
 * 两个引擎调用同一套映射函数，差异仅在配置外层结构。
 *
 * 引擎归属：
 *   MQTT → config_loader.c 加载配置 → mapper_core 执行映射 → json_mapper.c 入口
 *   HTTP → vpp_http_config.load.c 加载配置 → mapper_core 执行映射 → http_json_mapper.c 入口
 *
 * 统一点：
 *   1. 路径取值 get_value_by_path (合并 get_value_by_path + http_get_json_by_path)
 *   2. 路径创建 ensure_path (两引擎逻辑完全相同)
 *   3. 类型转换 add_value_to_parent (合并 enum 版 + string 版)
 *   4. 数组遍历 process_array_foreach (合并 $idx + item_type + "." 路径)
 *   5. 生成器 generate_value (合并所有 generator 类型)
 *   6. 普通字段 process_normal_field (合并 $item + context + post_process)
 *   7. 规则分发 process_rule (统一入口)
 */

#ifndef MAPPER_CORE_H
#define MAPPER_CORE_H

#include "cJSON.h"

/* ============================================================
 * 统一映射规则结构 — MQTT 和 HTTP 共用
 * ============================================================ */

/**
 * 统一映射规则
 *
 * 使用字符串字段（而非 enum），使 MQTT/HTTP 引擎无需各自定义枚举。
 * 对应 JSON 配置中的单个 mapping 对象。
 */
typedef struct MappingRule {
    char                target_path[256];    /* 目标 JSON 路径 */
    char                source_path[256];    /* 源 JSON 路径 */
    char                source_type[32];     /* path / constant / generated / array_foreach / context */
    char                value_type[16];      /* string / int / double / long / bool / object / substitute */
    char                constant_value[256]; /* 常量值 */
    char                generator[64];      /* 生成器名称 */
    char                generator_param[128];/* 生成器参数 */
    double              scale_factor;       /* 数值缩放因子，默认 1.0 */
    char                post_process[64];   /* 字段级后处理函数名 */
    char                preprocess[64];     /* 预处理函数名（HTTP: url_to_base64 等） */
    char                item_type[16];      /* array_foreach 时：object / key_value */
    int                 is_array_foreach;   /* 是否为数组遍历（0=否, 1=是） */
    struct MappingRule* sub_mappings;       /* 子映射规则数组 */
    int                 sub_mapping_count;  /* 子映射数量 */
} MappingRule;

/**
 * 映射上下文
 *
 * 持有生成器状态和 HTTP 链式调用的上下文数据。
 * MQTT 引擎仅使用 seq_counter。
 * HTTP 引擎额外使用 context（API 响应传递）。
 */
typedef struct {
    int     seq_counter;       /* sequence 生成器计数器 */
    cJSON*  context;           /* HTTP 链式调用上下文（MQTT 时为 NULL） */
    cJSON*  template_vars;     /* substitute 模板变量表（MQTT 时使用） */
} MappingContext;

/* ============================================================
 * 公开函数声明
 * ============================================================ */

/* --- 路径工具 --- */

/**
 * 按 JSON 路径取值（合并 get_value_by_path + http_get_json_by_path）
 *
 * 支持语法：
 *   a.b.c        — 对象属性访问
 *   a[0]         — 数组索引
 *   a[*]         — 返回整个数组
 *   "."          — 返回根对象本身（HTTP 特有）
 */
cJSON* get_value_by_path(cJSON* root, const char* path);

/**
 * 按 JSON 路径取字符串值
 */
char* get_string_by_path(cJSON* root, const char* path);

/**
 * 确保目标路径存在，不存在则创建（两引擎逻辑完全相同）
 */
cJSON* ensure_path(cJSON* root, const char* path);

/**
 * 获取带 [*] 语法的扁平化数组（MQTT 特有：支持嵌套 [*] 展平）
 */
cJSON* get_flat_array_from_path(cJSON* root, const char* path);

/* --- 类型转换 --- */

/**
 * 将源值按目标类型转换并添加到父对象
 * （合并 add_value_to_parent + http_add_value_to_parent）
 *
 * 支持 string/int/double/long/bool/object/substitute 七种类型
 */
void add_value_to_parent(cJSON* parent, const char* field_name,
                         cJSON* source_val, const char* value_type,
                         const char* constant, double scale,
                         MappingContext* ctx);

/* --- 生成器 --- */

/**
 * 生成值（合并 generate_value + http_generate_value）
 *
 * 支持：uuid, current_timestamp, current_timestamp_ms, datetime_compact,
 *       random_string, md5_sign, batch_id, sequence,
 *       timestamp_ms, timestamp_sec, datetime_str
 */
char* generate_value(const char* generator, const char* param,
                     MappingContext* ctx, int idx);

/* --- 映射处理 --- */

/**
 * 处理单条映射规则（统一入口，合并 process_rule + http_process_rule）
 */
void process_rule(cJSON* target, cJSON* source, const MappingRule* rule,
                  MappingContext* ctx, cJSON* current_array_item);

/**
 * 处理数组遍历规则（合并 process_array_foreach + http_process_array_foreach）
 *
 * 支持：$idx 变量替换（通用）、item_type object/key_value（通用）、"." 源路径（通用）
 */
void process_array_foreach(cJSON* target, cJSON* source, const MappingRule* rule,
                           MappingContext* ctx);

/**
 * 处理普通字段规则（合并 process_normal_field + http_process_normal_field）
 *
 * 支持：$item 替换（通用）、context source_type（通用）、post_process（通用，待实现）、preprocess（通用，待实现）
 */
void process_normal_field(cJSON* target, cJSON* source, const MappingRule* rule,
                          MappingContext* ctx, cJSON* current_array_item);

/* --- 模板替换 --- */

/**
 * 模板变量替换 $var$ 语法（MQTT substitute 特有）
 */
char* template_substitute(const char* template_str, MappingContext* ctx);

/* --- 工具函数 --- */

/**
 * 检查路径是否包含 [*] 语法
 */
int has_foreach_syntax(const char* path);

/**
 * 检查路径是否包含 @ 锚点
 */
int has_array_anchor(const char* path);

#endif /* MAPPER_CORE_H */
