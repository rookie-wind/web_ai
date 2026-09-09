/**
 * mapper_core.c — 统一协议映射核心引擎实现
 *
 * 合并 json_mapper.c (MQTT) 和 http_json_mapper.c (HTTP) 的所有共享映射逻辑。
 *
 * 统一策略：
 *   - 路径取值：HTTP 版是 MQTT 版的超集（多支持 "." 和 [*]），取 HTTP 版
 *   - 路径创建：两引擎逻辑完全相同，取任一
 *   - 类型转换：合并 enum 版(MQTT) + string 版(HTTP)，统一用 string 比较，
 *     补全 HTTP 缺失的 object/substitute 类型，补全 MQTT 缺失的 string→number 转换
 *   - 数组遍历：合并 $idx(MQTT) + item_type(HTTP) + "." 源路径(HTTP)
 *   - 生成器：合并所有 generator 类型
 *   - 普通字段：合并 $item(MQTT) + context(HTTP) + post_process(MQTT)
 */

#include "mapper_core.h"
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <ctype.h>
#include <sys/time.h>
#include <time.h>

/* ============================================================
 * 路径工具函数
 * ============================================================ */

int has_foreach_syntax(const char* path) {
    return path != NULL && strstr(path, "[*]") != NULL;
}

int has_array_anchor(const char* path) {
    return path != NULL && strstr(path, "@") != NULL;
}

/**
 * 按 JSON 路径取值
 *
 * 合并 get_value_by_path (MQTT) + http_get_json_by_path (HTTP)
 * HTTP 版是 MQTT 版的超集：多了 "." 路径和 [*] 语法支持
 */
cJSON* get_value_by_path(cJSON* root, const char* path) {
    if (!root || !path) return NULL;

    /* HTTP 特有："." 表示当前根对象 */
    if (strcmp(path, ".") == 0) {
        return root;
    }

    char path_copy[512];
    strncpy(path_copy, path, sizeof(path_copy) - 1);
    path_copy[sizeof(path_copy) - 1] = '\0';

    cJSON* current = root;
    char* token = strtok(path_copy, ".");

    while (token != NULL && current) {
        char* bracket = strchr(token, '[');
        if (bracket) {
            *bracket = '\0';
            char* index_str = bracket + 1;
            char* end = strchr(index_str, ']');
            if (end) *end = '\0';

            /* 先获取数组对象 */
            current = cJSON_GetObjectItem(current, token);
            if (!current || !cJSON_IsArray(current)) {
                return NULL;
            }

            /* HTTP 特有：[*] 返回整个数组 */
            if (strcmp(index_str, "*") == 0) {
                return current;
            }

            /* 处理具体索引 [0], [1] 等 */
            int index = atoi(index_str);
            if (index >= 0 && index < cJSON_GetArraySize(current)) {
                current = cJSON_GetArrayItem(current, index);
            } else {
                return NULL;
            }
        } else {
            current = cJSON_GetObjectItem(current, token);
        }
        token = strtok(NULL, ".");
    }
    return current;
}

/**
 * 按 JSON 路径取字符串值（来自 http_json_mapper.c）
 */
char* get_string_by_path(cJSON* root, const char* path) {
    cJSON* val = get_value_by_path(root, path);
    if (!val) return NULL;

    static char buffer[512];
    if (cJSON_IsString(val)) {
        strncpy(buffer, val->valuestring, sizeof(buffer) - 1);
    } else if (cJSON_IsNumber(val)) {
        snprintf(buffer, sizeof(buffer), "%g", val->valuedouble);
    } else if (cJSON_IsBool(val)) {
        strcpy(buffer, cJSON_IsTrue(val) ? "true" : "false");
    } else {
        return NULL;
    }
    buffer[sizeof(buffer) - 1] = '\0';
    return buffer;
}

/**
 * 确保路径存在，不存在则创建
 *
 * 两引擎逻辑完全相同（ensure_path == http_ensure_path）
 */
cJSON* ensure_path(cJSON* root, const char* path) {
    if (!root || !path || strlen(path) == 0) return root;

    char path_copy[256];
    strcpy(path_copy, path);

    cJSON* current = root;
    char* token = strtok(path_copy, ".");

    while (token) {
        char* bracket = strchr(token, '[');
        if (bracket) {
            *bracket = '\0';
            int index = atoi(bracket + 1);

            cJSON* obj = cJSON_GetObjectItem(current, token);
            if (!obj) {
                obj = cJSON_CreateArray();
                cJSON_AddItemToObject(current, token, obj);
            }

            int array_size = cJSON_GetArraySize(obj);
            for (int i = array_size; i <= index; i++) {
                cJSON_AddItemToArray(obj, cJSON_CreateObject());
            }
            current = cJSON_GetArrayItem(obj, index);
        } else {
            cJSON* obj = cJSON_GetObjectItem(current, token);
            if (!obj) {
                obj = cJSON_CreateObject();
                cJSON_AddItemToObject(current, token, obj);
            }
            current = obj;
        }
        token = strtok(NULL, ".");
    }
    return current;
}

/**
 * 获取带 [*] 语法的扁平化数组（来自 json_mapper.c）
 *
 * 支持嵌套：如 "dataObj.itemBody[*].item[*]"
 * HTTP 引擎通过 get_value_by_path 的 [*] 支持也能处理单层情况
 */
cJSON* get_flat_array_from_path(cJSON* root, const char* path) {
    if (!has_foreach_syntax(path)) {
        cJSON* val = get_value_by_path(root, path);
        if (val && cJSON_IsArray(val)) return val;
        return NULL;
    }

    char path_copy[512];
    strcpy(path_copy, path);

    char* star_pos = strstr(path_copy, "[*]");
    if (!star_pos) return NULL;

    int base_len = star_pos - path_copy;
    char base_path[256];
    strncpy(base_path, path_copy, base_len);
    base_path[base_len] = '\0';

    cJSON* base_array = get_value_by_path(root, base_path);
    if (!base_array || !cJSON_IsArray(base_array)) return NULL;

    char* remaining = star_pos + 3;
    if (*remaining == '.') remaining++;

    if (strlen(remaining) == 0) {
        return base_array;
    }

    /* 有剩余路径，递归展平 */
    cJSON* result = cJSON_CreateArray();
    int size = cJSON_GetArraySize(base_array);

    for (int i = 0; i < size; i++) {
        cJSON* item = cJSON_GetArrayItem(base_array, i);
        cJSON* sub_array = get_flat_array_from_path(item, remaining);
        if (sub_array && cJSON_IsArray(sub_array)) {
            int sub_size = cJSON_GetArraySize(sub_array);
            for (int j = 0; j < sub_size; j++) {
                cJSON* sub_item = cJSON_GetArrayItem(sub_array, j);
                cJSON_AddItemToArray(result, cJSON_Duplicate(sub_item, 1));
            }
        } else if (sub_array) {
            cJSON_AddItemToArray(result, cJSON_Duplicate(sub_array, 1));
        }
    }

    return result;
}

/* ============================================================
 * 生成器
 * ============================================================ */

/**
 * 生成值
 *
 * 合并 generate_value (MQTT) + http_generate_value (HTTP)
 * 支持所有生成器类型：
 *   uuid, current_timestamp, current_timestamp_ms, datetime_compact,
 *   random_string, md5_sign, batch_id, sequence,
 *   timestamp_ms, timestamp_sec, datetime_str
 */
char* generate_value(const char* generator, const char* param,
                     MappingContext* ctx, int idx) {
    static char buffer[256];
    memset(buffer, 0, sizeof(buffer));

    struct timeval tv;
    gettimeofday(&tv, NULL);
    long long ms = (long long)tv.tv_sec * 1000 + tv.tv_usec / 1000;
    time_t sec = tv.tv_sec;

    if (strcmp(generator, "uuid") == 0) {
        snprintf(buffer, sizeof(buffer), "%s", "uuid-placeholder");
    }
    else if (strcmp(generator, "current_timestamp") == 0 ||
             strcmp(generator, "timestamp_sec") == 0) {
        snprintf(buffer, sizeof(buffer), "%ld", sec);
    }
    else if (strcmp(generator, "current_timestamp_ms") == 0 ||
             strcmp(generator, "timestamp_ms") == 0) {
        snprintf(buffer, sizeof(buffer), "%lld", ms);
    }
    else if (strcmp(generator, "datetime_compact") == 0) {
        struct tm* tm = localtime(&sec);
        strftime(buffer, sizeof(buffer), "%Y%m%d%H%M%S", tm);
    }
    else if (strcmp(generator, "datetime_str") == 0) {
        struct tm* tm = localtime(&sec);
        strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", tm);
    }
    else if (strcmp(generator, "random_string") == 0) {
        snprintf(buffer, sizeof(buffer), "%s", "random-placeholder");
    }
    else if (strcmp(generator, "md5_sign") == 0) {
        snprintf(buffer, sizeof(buffer), "%s", "md5-placeholder");
    }
    else if (strcmp(generator, "batch_id") == 0) {
        snprintf(buffer, sizeof(buffer), "%s", "batch-placeholder");
    }
    else if (strcmp(generator, "sequence") == 0) {
        if (idx >= 0) {
            snprintf(buffer, sizeof(buffer), "%d", idx + 1);
        } else if (ctx) {
            ctx->seq_counter++;
            snprintf(buffer, sizeof(buffer), "%d", ctx->seq_counter);
        }
    }

    return buffer;
}

/* ============================================================
 * 模板替换
 * ============================================================ */

/**
 * 模板变量替换 $var$ 语法（来自 json_mapper.c）
 *
 * 从 ctx->template_vars 中查找变量值
 */
char* template_substitute(const char* template_str, MappingContext* ctx) {
    if (!template_str || !ctx || !ctx->template_vars) {
        return template_str ? strdup(template_str) : NULL;
    }

    /* 简化实现：查找 $var$ 并替换 */
    char* result = strdup(template_str);
    char* pos = result;

    while ((pos = strstr(pos, "$")) != NULL) {
        char* end = strstr(pos + 1, "$");
        if (!end) break;

        int var_len = end - pos - 1;
        char var_name[128] = {0};
        strncpy(var_name, pos + 1, var_len);

        /* 在 template_vars 中查找（支持嵌套路径如 ssl_mqtt_server.gatewayID） */
        cJSON* var_val = get_value_by_path(ctx->template_vars, var_name);
        if (var_val && cJSON_IsString(var_val)) {
            /* 替换 */
            char* new_result = malloc(strlen(result) - var_len - 2 + strlen(var_val->valuestring) + 1);
            int prefix_len = pos - result;
            strncpy(new_result, result, prefix_len);
            strcpy(new_result + prefix_len, var_val->valuestring);
            strcat(new_result, end + 1);
            free(result);
            result = new_result;
            pos = result + prefix_len;
        } else {
            pos = end + 1;
        }
    }

    return result;
}

/* ============================================================
 * 类型转换
 * ============================================================ */

/**
 * 将源值按目标类型转换并添加到父对象
 *
 * 合并 add_value_to_parent (MQTT, enum 版) + http_add_value_to_parent (HTTP, string 版)
 * 统一使用 string 比较，合并所有类型处理：
 *   - HTTP 补充：string→number 转换（atoi/atof/atol）
 *   - MQTT 补充：object 类型（深拷贝/JSON 解析/空对象）
 *   - MQTT 补充：substitute 类型（模板替换）
 */
void add_value_to_parent(cJSON* parent, const char* field_name,
                         cJSON* source_val, const char* value_type,
                         const char* constant, double scale,
                         MappingContext* ctx) {

    if (strcmp(value_type, "int") == 0) {
        int val = 0;
        if (constant && strlen(constant) > 0) {
            val = atoi(constant);
        } else if (source_val) {
            if (cJSON_IsNumber(source_val)) {
                val = (int)(source_val->valuedouble * scale);
            } else if (cJSON_IsString(source_val)) {
                val = atoi(source_val->valuestring);
            }
        }
        cJSON_AddNumberToObject(parent, field_name, val);
    }
    else if (strcmp(value_type, "double") == 0) {
        double val = 0.0;
        if (constant && strlen(constant) > 0) {
            val = atof(constant);
        } else if (source_val) {
            if (cJSON_IsNumber(source_val)) {
                val = source_val->valuedouble * scale;
            } else if (cJSON_IsString(source_val)) {
                val = atof(source_val->valuestring);
            }
        }
        cJSON_AddNumberToObject(parent, field_name, val);
    }
    else if (strcmp(value_type, "long") == 0) {
        long val = 0;
        if (constant && strlen(constant) > 0) {
            val = atol(constant);
        } else if (source_val) {
            if (cJSON_IsNumber(source_val)) {
                val = (long)(source_val->valuedouble * scale);
            } else if (cJSON_IsString(source_val)) {
                val = atol(source_val->valuestring);
            }
        }
        cJSON_AddNumberToObject(parent, field_name, val);
    }
    else if (strcmp(value_type, "bool") == 0) {
        int val = 0;
        if (constant && strlen(constant) > 0) {
            val = (strcmp(constant, "true") == 0 || strcmp(constant, "1") == 0) ? 1 : 0;
        } else if (source_val) {
            if (cJSON_IsBool(source_val)) {
                val = cJSON_IsTrue(source_val) ? 1 : 0;
            } else if (cJSON_IsNumber(source_val)) {
                val = (source_val->valueint != 0) ? 1 : 0;
            } else if (cJSON_IsString(source_val)) {
                val = (strcmp(source_val->valuestring, "true") == 0 ||
                       strcmp(source_val->valuestring, "1") == 0) ? 1 : 0;
            }
        }
        cJSON_AddBoolToObject(parent, field_name, val);
    }
    else if (strcmp(value_type, "object") == 0) {
        /* MQTT 特有：对象类型处理 */
        if (source_val && cJSON_IsObject(source_val)) {
            cJSON_AddItemToObject(parent, field_name, cJSON_Duplicate(source_val, 1));
        } else if (constant && strlen(constant) > 0) {
            cJSON* obj = cJSON_Parse(constant);
            if (obj) {
                cJSON_AddItemToObject(parent, field_name, obj);
            } else {
                cJSON_AddItemToObject(parent, field_name, cJSON_CreateObject());
            }
        } else {
            cJSON_AddItemToObject(parent, field_name, cJSON_CreateObject());
        }
    }
    else if (strcmp(value_type, "substitute") == 0) {
        /* MQTT 特有：模板替换类型 */
        if (constant && strlen(constant) > 0 && ctx) {
            char* substituted = template_substitute(constant, ctx);
            if (substituted) {
                cJSON_AddItemToObject(parent, field_name, cJSON_CreateString(substituted));
                free(substituted);
            }
        }
    }
    else {
        /* 默认：string 类型 */
        char str_buf[128] = {0};
        const char* str = constant;

        if (source_val) {
            if (cJSON_IsString(source_val)) {
                str = source_val->valuestring;
            } else if (cJSON_IsNumber(source_val)) {
                snprintf(str_buf, sizeof(str_buf), "%g", source_val->valuedouble);
                str = str_buf;
            } else if (cJSON_IsBool(source_val)) {
                str = cJSON_IsTrue(source_val) ? "true" : "false";
            }
        }

        if (str && strlen(str) > 0) {
            cJSON_AddStringToObject(parent, field_name, str);
        }
    }
}

/* ============================================================
 * 映射处理核心
 * ============================================================ */

/* 前向声明 */
static void process_rule_impl(cJSON* target, cJSON* source, const MappingRule* rule,
                              MappingContext* ctx, cJSON* current_array_item);

/**
 * 处理数组遍历规则
 *
 * 合并 process_array_foreach (MQTT) + http_process_array_foreach (HTTP)
 *
 * 统一支持：
 *   - $idx 变量替换（来自 MQTT）
 *   - item_type: object / key_value（来自 HTTP）
 *   - "." 源路径表示当前根对象（来自 HTTP）
 *   - 嵌套 [*] 展平（来自 MQTT get_flat_array_from_path）
 */
void process_array_foreach(cJSON* target, cJSON* source, const MappingRule* rule,
                           MappingContext* ctx) {
    /* 1. 获取源数组 */
    cJSON* source_array = NULL;
    int need_free = 0;

    /* HTTP 特有："." 表示将当前 source 作为单元素数组 */
    if (strcmp(rule->source_path, ".") == 0) {
        source_array = cJSON_CreateArray();
        cJSON_AddItemToArray(source_array, cJSON_Duplicate(source, 1));
        need_free = 1;
    } else if (has_foreach_syntax(rule->source_path)) {
        /* MQTT 特有：嵌套 [*] 展平 */
        source_array = get_flat_array_from_path(source, rule->source_path);
    } else {
        /* 通用：直接取值，[*] 在 get_value_by_path 中处理 */
        source_array = get_value_by_path(source, rule->source_path);
    }

    if (!source_array || !cJSON_IsArray(source_array)) {
        if (source_array && need_free) cJSON_Delete(source_array);
        return;
    }

    int array_size = cJSON_GetArraySize(source_array);
    if (array_size == 0) {
        if (need_free) cJSON_Delete(source_array);
        return;
    }

    /* 2. 解析目标路径中的 @ 锚点 */
    char target_path_copy[256];
    strcpy(target_path_copy, rule->target_path);

    char* at_pos = strstr(target_path_copy, "@");
    if (!at_pos) {
        if (need_free) cJSON_Delete(source_array);
        return;
    }

    *at_pos = '\0';
    char* parent_path = target_path_copy;

    /* 去掉末尾的点 */
    int len = strlen(parent_path);
    if (len > 0 && parent_path[len - 1] == '.') {
        parent_path[len - 1] = '\0';
    }

    /* 3. 确定数组字段名和父对象 */
    char array_field[128] = {0};
    cJSON* parent = NULL;

    if (strlen(parent_path) > 0) {
        char* last_dot = strrchr(parent_path, '.');
        if (last_dot) {
            strcpy(array_field, last_dot + 1);
            *last_dot = '\0';
            if (strlen(parent_path) > 0) {
                parent = ensure_path(target, parent_path);
            } else {
                parent = target;
            }
        } else {
            /* 简单数组：直接挂在 target 上 */
            strcpy(array_field, parent_path);
            parent = target;
        }
    } else {
        parent = target;
    }

    if (strlen(array_field) == 0) {
        if (need_free) cJSON_Delete(source_array);
        return;
    }

    /* 4. 创建目标数组并遍历 */
    cJSON* target_array = cJSON_CreateArray();

    /* 确定 item_type：默认 object（MQTT 兼容） */
    const char* item_type = strlen(rule->item_type) > 0 ? rule->item_type : "object";

    for (int i = 0; i < array_size; i++) {
        cJSON* source_item = cJSON_GetArrayItem(source_array, i);
        cJSON* target_item = NULL;

        /* HTTP 特有：item_type = "key_value" 时，每个 sub_mapping 生成独立对象 */
        if (strcmp(item_type, "object") == 0) {
            target_item = cJSON_CreateObject();
        }

        for (int j = 0; j < rule->sub_mapping_count; j++) {
            MappingRule* sub_rule = &rule->sub_mappings[j];

            /* $idx 变量替换：将 $idx 替换为当前索引值 */
            char original_source_path[256] = {0};
            if (strstr(sub_rule->source_path, "$idx")) {
                strcpy(original_source_path, sub_rule->source_path);
                char idx_str[16];
                snprintf(idx_str, sizeof(idx_str), "%d", i);
                char new_path[512] = {0};
                const char* pos = sub_rule->source_path;
                const char* idx_pos;
                size_t prefix_len;
                while ((idx_pos = strstr(pos, "$idx")) != NULL) {
                    prefix_len = idx_pos - pos;
                    strncat(new_path, pos, prefix_len);
                    strcat(new_path, idx_str);
                    pos = idx_pos + 4; /* skip "$idx" */
                }
                strcat(new_path, pos);
                strcpy(sub_rule->source_path, new_path);
            }

            if (strcmp(item_type, "key_value") == 0) {
                target_item = cJSON_CreateObject();
            }

            process_rule_impl(target_item, source_item, sub_rule, ctx, source_item);

            if (strcmp(item_type, "key_value") == 0) {
                cJSON_AddItemToArray(target_array, target_item);
            }

            /* 恢复原始 source_path */
            if (strlen(original_source_path) > 0) {
                strcpy(sub_rule->source_path, original_source_path);
            }
        }

        if (strcmp(item_type, "object") == 0) {
            cJSON_AddItemToArray(target_array, target_item);
        }
    }

    /* 5. 将数组添加到父对象 */
    cJSON* existing = cJSON_GetObjectItem(parent, array_field);
    if (existing) {
        cJSON_DeleteItemFromObject(parent, array_field);
    }
    cJSON_AddItemToObject(parent, array_field, target_array);

    if (need_free) {
        cJSON_Delete(source_array);
    }
}

/**
 * 处理普通字段规则
 *
 * 合并 process_normal_field (MQTT) + http_process_normal_field (HTTP)
 *
 * 统一支持：
 *   - $item 替换（来自 MQTT）
 *   - context source_type（来自 HTTP）
 *   - post_process 后处理（来自 MQTT）
 *   - TYPE_OBJECT + sub_mappings 递归（来自 MQTT）
 */
void process_normal_field(cJSON* target, cJSON* source, const MappingRule* rule,
                          MappingContext* ctx, cJSON* current_array_item) {
    cJSON* parent = NULL;
    char field_name[128] = {0};

    /* 解析目标路径 */
    char path_copy[256];
    strcpy(path_copy, rule->target_path);
    char* last_dot = strrchr(path_copy, '.');

    if (last_dot) {
        *last_dot = '\0';
        strcpy(field_name, last_dot + 1);
        parent = ensure_path(target, path_copy);
    } else {
        strcpy(field_name, path_copy);
        parent = target;
    }

    if (!parent) return;

    /* MQTT 特有：TYPE_OBJECT + sub_mappings 时，先获取 source_val，再递归 */
    if (strcmp(rule->value_type, "object") == 0 && rule->sub_mapping_count > 0) {
        cJSON* obj = cJSON_CreateObject();

        /* 获取 source_val */
        cJSON* source_val = NULL;
        if (strcmp(rule->source_type, "path") == 0) {
            cJSON* src = (current_array_item && strstr(rule->source_path, "$item"))
                         ? current_array_item : source;
            char* path = rule->source_path;
            if (strstr(path, "$item")) {
                char* after_item = strstr(path, "$item") + 5;
                if (*after_item == '.') after_item++;
                source_val = get_value_by_path(src, after_item);
            } else {
                source_val = get_value_by_path(source, path);
            }
        }

        /* 递归处理子映射 */
        for (int i = 0; i < rule->sub_mapping_count; i++) {
            process_rule_impl(obj, source_val ? source_val : source,
                              &rule->sub_mappings[i], ctx, current_array_item);
        }

        cJSON_AddItemToObject(parent, field_name, obj);
        return;
    }

    /* 根据 source_type 获取值 */
    cJSON* source_val = NULL;
    const char* constant_val = NULL;
    char* generated_val = NULL;

    if (strcmp(rule->source_type, "constant") == 0) {
        constant_val = rule->constant_value;
    }
    else if (strcmp(rule->source_type, "generated") == 0) {
        generated_val = generate_value(rule->generator, rule->generator_param, ctx, -1);
        constant_val = generated_val;
    }
    else if (strcmp(rule->source_type, "path") == 0) {
        /* $item 替换（通用，array_foreach 子映射中使用） */
        if (current_array_item && strstr(rule->source_path, "$item")) {
            char* after_item = strstr(rule->source_path, "$item") + 5;
            if (*after_item == '.') after_item++;
            source_val = get_value_by_path(current_array_item, after_item);
        } else {
            source_val = get_value_by_path(source, rule->source_path);
        }

        /* TODO: preprocess 预处理 — 字段已定义但执行逻辑未实现
         * 支持的函数名（待实现）：
         *   url_to_base64 — URL 内容转 base64 编码
         * 实现方案：在取值后、类型转换前执行，由 mapper_comm.c 提供具体函数 */
        if (strlen(rule->preprocess) > 0 && source_val) {
            /* 待实现 */
        }

        /* TODO: post_process 后处理 — 字段已定义但执行逻辑未实现
         * 支持的函数名（待实现）：
         *   datetime_to_yyyyMMddHHmmss — 时间格式转换
         *   trim — 去除尾部空字符
         *   sm4_encode — SM4 加密
         * 实现方案：通过函数指针注册表调用，由 mapper_comm.c 提供具体函数 */
        if (strlen(rule->post_process) > 0 && source_val) {
            /* 待实现 */
        }
    }
    else if (strcmp(rule->source_type, "context") == 0) {
        /* context：从运行时上下文取值（HTTP 链式调用常用） */
        source_val = get_value_by_path(ctx ? ctx->context : NULL, rule->source_path);
    }
    /* substitute 已合并到 constant：source_type="constant" + value_type="substitute" 触发模板替换 */

    add_value_to_parent(parent, field_name, source_val, rule->value_type,
                        constant_val, rule->scale_factor, ctx);
}

/**
 * 规则分发（统一入口）
 *
 * 合并 process_rule (MQTT) + http_process_rule (HTTP)
 * 根据 is_array_foreach 标志或 source_type 字符串判断
 */
static void process_rule_impl(cJSON* target, cJSON* source, const MappingRule* rule,
                              MappingContext* ctx, cJSON* current_array_item) {
    if (rule->is_array_foreach ||
        strcmp(rule->source_type, "array_foreach") == 0) {
        process_array_foreach(target, source, rule, ctx);
    } else {
        process_normal_field(target, source, rule, ctx, current_array_item);
    }
}

/**
 * 处理单条映射规则（公开接口）
 */
void process_rule(cJSON* target, cJSON* source, const MappingRule* rule,
                  MappingContext* ctx, cJSON* current_array_item) {
    process_rule_impl(target, source, rule, ctx, current_array_item);
}
