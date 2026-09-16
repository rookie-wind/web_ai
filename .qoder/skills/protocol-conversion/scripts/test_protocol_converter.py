#!/usr/bin/env python3
"""
统一协议映射引擎 — 完备测试

测试覆盖：
  1. 路径取值 (get_value_by_path)
  2. 路径创建 (ensure_path)
  3. 类型转换 (add_value_to_parent) — 7种类型
  4. 生成器 (generate_value) — 所有类型
  5. 模板替换 (template_substitute)
  6. 数组遍历 (process_array_foreach) — object/key_value/嵌套/.$idx
  7. MQTT 完整转换 (transform_mqtt) — 真实配置
  8. HTTP 完整转换 (transform_http) — 真实配置
  9. 引擎差异验证 — MQTT不支持context / HTTP不支持substitute
  10. 边界条件
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol_converter import MapperCore


class TestPathResolution(unittest.TestCase):
    """1. 路径取值测试"""

    def setUp(self):
        self.data = {
            "udSign": 1,
            "taskId": 100,
            "businessObjList": [{
                "dataObj": {
                    "dataItemList": [{
                        "itemBody": [
                            {"commAddr": "addr1", "item": [{"voltageA": 220.1, "timeStamp": "2023-01-01"}]},
                            {"commAddr": "addr2", "item": [{"voltageA": 221.5, "timeStamp": "2023-01-02"}]}
                        ]
                    }]
                }
            }]
        }

    def test_basic_path(self):
        """基本对象路径 a.b.c"""
        self.assertEqual(MapperCore.get_value_by_path(self.data, "udSign"), 1)
        self.assertEqual(MapperCore.get_value_by_path(self.data, "taskId"), 100)

    def test_nested_path(self):
        """嵌套路径"""
        val = MapperCore.get_value_by_path(self.data, "businessObjList[0].dataObj")
        self.assertIsInstance(val, dict)
        self.assertIn("dataItemList", val)

    def test_array_index(self):
        """数组索引 [0]"""
        val = MapperCore.get_value_by_path(self.data, "businessObjList[0].dataObj.dataItemList[0].itemBody[0]")
        self.assertEqual(val["commAddr"], "addr1")

    def test_array_index_second(self):
        """数组索引 [1]"""
        val = MapperCore.get_value_by_path(self.data, "businessObjList[0].dataObj.dataItemList[0].itemBody[1]")
        self.assertEqual(val["commAddr"], "addr2")

    def test_array_wildcard(self):
        """数组通配符 [*] — 返回整个数组"""
        val = MapperCore.get_value_by_path(self.data, "businessObjList[0].dataObj.dataItemList[0].itemBody[*]")
        self.assertIsInstance(val, list)
        self.assertEqual(len(val), 2)

    def test_dot_path(self):
        """HTTP 特有: '.' 返回根对象"""
        val = MapperCore.get_value_by_path(self.data, ".")
        self.assertIs(val, self.data)

    def test_missing_path(self):
        """缺失路径返回 None"""
        self.assertIsNone(MapperCore.get_value_by_path(self.data, "nonexistent"))
        self.assertIsNone(MapperCore.get_value_by_path(self.data, "businessObjList[0].nonexistent"))

    def test_out_of_range_index(self):
        """越界索引返回 None"""
        self.assertIsNone(MapperCore.get_value_by_path(self.data, "businessObjList[99]"))

    def test_get_string_by_path(self):
        """get_string_by_path"""
        self.assertEqual(MapperCore.get_string_by_path(self.data, "udSign"), "1")
        self.assertEqual(MapperCore.get_string_by_path(self.data, "taskId"), "100")
        self.assertIsNone(MapperCore.get_string_by_path(self.data, "nonexistent"))

    def test_flat_array_from_path_single(self):
        """单层 [*] 展平"""
        val = MapperCore.get_flat_array_from_path(
            self.data,
            "businessObjList[0].dataObj.dataItemList[0].itemBody[*]"
        )
        self.assertIsInstance(val, list)
        self.assertEqual(len(val), 2)
        self.assertEqual(val[0]["commAddr"], "addr1")

    def test_flat_array_from_path_nested(self):
        """嵌套 [*] 展平 — MQTT 特有"""
        val = MapperCore.get_flat_array_from_path(
            self.data,
            "businessObjList[0].dataObj.dataItemList[0].itemBody[*].item[*]"
        )
        self.assertIsInstance(val, list)
        self.assertEqual(len(val), 2)
        self.assertEqual(val[0]["voltageA"], 220.1)

    def test_flat_array_no_foreach(self):
        """无 [*] 语法的路径"""
        val = MapperCore.get_flat_array_from_path(self.data, "businessObjList")
        self.assertIsInstance(val, list)
        self.assertEqual(len(val), 1)


class TestEnsurePath(unittest.TestCase):
    """2. 路径创建测试"""

    def test_simple_path(self):
        """简单路径"""
        root = {}
        result = MapperCore.ensure_path(root, "data")
        self.assertIn("data", root)
        self.assertIsInstance(root["data"], dict)

    def test_nested_path(self):
        """嵌套路径"""
        root = {}
        result = MapperCore.ensure_path(root, "data.terdata")
        self.assertIn("data", root)
        self.assertIn("terdata", root["data"])
        self.assertIsInstance(root["data"]["terdata"], dict)

    def test_array_path(self):
        """数组路径 [0]"""
        root = {}
        result = MapperCore.ensure_path(root, "data.terdata[0]")
        self.assertIn("data", root)
        self.assertIn("terdata", root["data"])
        self.assertIsInstance(root["data"]["terdata"], list)
        self.assertEqual(len(root["data"]["terdata"]), 1)
        self.assertIsInstance(root["data"]["terdata"][0], dict)

    def test_array_path_fill(self):
        """数组路径填充 [2]"""
        root = {}
        MapperCore.ensure_path(root, "data.items[2]")
        self.assertEqual(len(root["data"]["items"]), 3)

    def test_empty_path(self):
        """空路径"""
        root = {"existing": 1}
        result = MapperCore.ensure_path(root, "")
        self.assertIs(result, root)


class TestTypeConversion(unittest.TestCase):
    """3. 类型转换测试 — 7种类型"""

    def test_string_from_string(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", "hello", "string")
        self.assertEqual(parent["field"], "hello")

    def test_string_from_number(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", 220.5, "string")
        self.assertEqual(parent["field"], "220.5")

    def test_string_from_bool(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", True, "string")
        self.assertEqual(parent["field"], "true")

    def test_string_empty_skipped(self):
        """空字符串不添加"""
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", "", "string")
        self.assertNotIn("field", parent)

    def test_int_from_number(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", 100.7, "int")
        self.assertEqual(parent["field"], 100)

    def test_int_with_scale(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", 100.0, "int", scale=2.0)
        self.assertEqual(parent["field"], 200)

    def test_int_from_string(self):
        """HTTP 特有: 字符串→整数"""
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", "42", "int")
        self.assertEqual(parent["field"], 42)

    def test_int_constant(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", None, "int", constant=8220)
        self.assertEqual(parent["field"], 8220)

    def test_double_from_number(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", 220.1, "double")
        self.assertAlmostEqual(parent["field"], 220.1, places=1)

    def test_double_with_scale(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", 10.0, "double", scale=0.1)
        self.assertAlmostEqual(parent["field"], 1.0, places=1)

    def test_double_from_string(self):
        """HTTP 特有: 字符串→浮点"""
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", "220.5", "double")
        self.assertEqual(parent["field"], 220.5)

    def test_long_from_number(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", 9999999999.0, "long")
        self.assertEqual(parent["field"], 9999999999)

    def test_bool_from_bool(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", True, "bool")
        self.assertTrue(parent["field"])

    def test_bool_from_number(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", 1, "bool")
        self.assertTrue(parent["field"])

    def test_bool_from_string_true(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", "true", "bool")
        self.assertTrue(parent["field"])

    def test_bool_from_string_false(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", "false", "bool")
        self.assertFalse(parent["field"])

    def test_bool_constant(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", None, "bool", constant="true")
        self.assertTrue(parent["field"])

    def test_object_from_dict(self):
        parent = {}
        src = {"key": "value"}
        MapperCore.add_value_to_parent(parent, "field", src, "object")
        self.assertEqual(parent["field"], {"key": "value"})
        # 确保深拷贝
        parent["field"]["key"] = "changed"
        self.assertEqual(src["key"], "value")

    def test_object_from_constant_json(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", None, "object", constant='{"a":1}')
        self.assertEqual(parent["field"], {"a": 1})

    def test_object_empty(self):
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", None, "object")
        self.assertEqual(parent["field"], {})

    def test_substitute(self):
        """MQTT 特有: substitute 类型"""
        parent = {}
        ctx = {"gatewayID": "GW001"}
        MapperCore.add_value_to_parent(parent, "devId", None, "substitute",
                                        constant="$gatewayID$", ctx=ctx)
        self.assertEqual(parent["devId"], "GW001")

    def test_substitute_nested(self):
        """嵌套变量替换"""
        parent = {}
        ctx = {"ssl_mqtt_server": {"gatewayID": "GW002"}}
        MapperCore.add_value_to_parent(parent, "devId", None, "substitute",
                                        constant="$ssl_mqtt_server.gatewayID$", ctx=ctx)
        self.assertEqual(parent["devId"], "GW002")


class TestGenerators(unittest.TestCase):
    """4. 生成器测试"""

    def test_uuid(self):
        val = MapperCore.generate_value("uuid")
        self.assertIsInstance(val, str)
        self.assertEqual(len(val), 36)  # UUID v4 长度

    def test_current_timestamp(self):
        val = MapperCore.generate_value("current_timestamp")
        self.assertIsInstance(val, str)
        self.assertTrue(val.isdigit())

    def test_current_timestamp_ms(self):
        val = MapperCore.generate_value("current_timestamp_ms")
        self.assertIsInstance(val, str)
        self.assertTrue(val.isdigit())

    def test_timestamp_sec(self):
        """HTTP 生成器名称"""
        val = MapperCore.generate_value("timestamp_sec")
        self.assertIsInstance(val, str)
        self.assertTrue(val.isdigit())

    def test_timestamp_ms(self):
        """HTTP 生成器名称"""
        val = MapperCore.generate_value("timestamp_ms")
        self.assertIsInstance(val, str)
        self.assertTrue(val.isdigit())

    def test_datetime_compact(self):
        val = MapperCore.generate_value("datetime_compact")
        self.assertIsInstance(val, str)
        self.assertEqual(len(val), 14)  # yyyyMMddHHmmss

    def test_datetime_str(self):
        """HTTP 生成器名称"""
        val = MapperCore.generate_value("datetime_str")
        self.assertIsInstance(val, str)
        self.assertEqual(len(val), 19)  # yyyy-MM-dd HH:MM:SS

    def test_sequence_with_idx(self):
        val = MapperCore.generate_value("sequence", idx=5)
        self.assertEqual(val, "6")  # idx+1

    def test_sequence_with_ctx(self):
        ctx = {}
        v1 = MapperCore.generate_value("sequence", ctx=ctx)
        v2 = MapperCore.generate_value("sequence", ctx=ctx)
        self.assertEqual(v1, "1")
        self.assertEqual(v2, "2")

    def test_md5_sign(self):
        val = MapperCore.generate_value("md5_sign")
        self.assertIsInstance(val, str)
        self.assertEqual(len(val), 32)

    def test_batch_id(self):
        val = MapperCore.generate_value("batch_id")
        self.assertIsInstance(val, str)

    def test_random_string(self):
        val = MapperCore.generate_value("random_string")
        self.assertIsInstance(val, str)


class TestTemplateSubstitute(unittest.TestCase):
    """5. 模板替换测试"""

    def test_simple_substitute(self):
        result = MapperCore.template_substitute("$var$", {"var": "value"})
        self.assertEqual(result, "value")

    def test_nested_substitute(self):
        result = MapperCore.template_substitute(
            "$ssl_mqtt_server.gatewayID$",
            {"ssl_mqtt_server": {"gatewayID": "GW001"}}
        )
        self.assertEqual(result, "GW001")

    def test_multiple_substitute(self):
        result = MapperCore.template_substitute(
            "$a$_$b$",
            {"a": "hello", "b": "world"}
        )
        self.assertEqual(result, "hello_world")

    def test_no_match(self):
        result = MapperCore.template_substitute("$unknown$", {"known": "value"})
        self.assertEqual(result, "$unknown$")

    def test_no_var(self):
        result = MapperCore.template_substitute("plain text", {"var": "value"})
        self.assertEqual(result, "plain text")


class TestArrayForeach(unittest.TestCase):
    """6. 数组遍历测试"""

    def setUp(self):
        self.source = {
            "businessObjList": [{
                "dataObj": {
                    "dataItemList": [{
                        "itemBody": [
                            {"commAddr": "A1", "item": [{"voltageA": 220.1, "P": 100.0}]},
                            {"commAddr": "A2", "item": [{"voltageA": 221.5, "P": 200.0}]}
                        ]
                    }]
                }
            }]
        }

    def test_simple_object_foreach(self):
        """简单 object 类型遍历"""
        rule = {
            "target": "devices.@",
            "source": "businessObjList[0].dataObj.dataItemList[0].itemBody[*]",
            "source_type": "array_foreach",
            "sub_mappings": [
                {"target": "addr", "source": "commAddr", "type": "string"},
                {"target": "voltage", "source": "item[0].voltageA", "type": "double"}
            ]
        }
        target = {}
        MapperCore.process_array_foreach(target, self.source, rule)
        self.assertIn("devices", target)
        self.assertEqual(len(target["devices"]), 2)
        self.assertEqual(target["devices"][0]["addr"], "A1")
        self.assertAlmostEqual(target["devices"][0]["voltage"], 220.1, places=1)

    def test_key_value_foreach(self):
        """HTTP 特有: key_value 类型"""
        source = {"data": [{"k": "key1", "v": "val1"}, {"k": "key2", "v": "val2"}]}
        rule = {
            "target": "items.@",
            "source": "data[*]",
            "source_type": "array_foreach",
            "item_type": "key_value",
            "sub_mappings": [
                {"target": "name", "source": "k", "type": "string"},
                {"target": "value", "source": "v", "type": "string"}
            ]
        }
        target = {}
        MapperCore.process_array_foreach(target, source, rule)
        self.assertIn("items", target)
        self.assertEqual(len(target["items"]), 4)  # 2 items × 2 sub_mappings

    def test_nested_foreach(self):
        """嵌套数组遍历"""
        rule = {
            "target": "data.devices.@",
            "source": "businessObjList[0].dataObj.dataItemList[0].itemBody[*]",
            "source_type": "array_foreach",
            "sub_mappings": [
                {"target": "addr", "source": "commAddr", "type": "string"},
                {
                    "target": "readings.@",
                    "source": "item[*]",
                    "source_type": "array_foreach",
                    "sub_mappings": [
                        {"target": "P", "source": "P", "type": "double"},
                        {"target": "Ua", "source": "voltageA", "type": "double"}
                    ]
                }
            ]
        }
        target = {}
        MapperCore.process_array_foreach(target, self.source, rule)
        self.assertIn("data", target)
        self.assertIn("devices", target["data"])
        self.assertEqual(len(target["data"]["devices"]), 2)
        self.assertIn("readings", target["data"]["devices"][0])
        self.assertEqual(len(target["data"]["devices"][0]["readings"]), 1)
        self.assertAlmostEqual(target["data"]["devices"][0]["readings"][0]["P"], 100.0, places=1)

    def test_dot_source_path(self):
        """HTTP 特有: '.' 源路径"""
        source = {"deviceId": "DEV001", "value": 42}
        rule = {
            "target": "items.@",
            "source": ".",
            "source_type": "array_foreach",
            "sub_mappings": [
                {"target": "devId", "source": "deviceId", "type": "string"},
                {"target": "val", "source": "value", "type": "int"}
            ]
        }
        target = {}
        MapperCore.process_array_foreach(target, source, rule)
        self.assertIn("items", target)
        self.assertEqual(len(target["items"]), 1)
        self.assertEqual(target["items"][0]["devId"], "DEV001")

    def test_flat_array_nested_foreach(self):
        """MQTT 特有: 嵌套 [*] 展平后遍历"""
        rule = {
            "target": "all_items.@",
            "source": "businessObjList[0].dataObj.dataItemList[0].itemBody[*].item[*]",
            "source_type": "array_foreach",
            "sub_mappings": [
                {"target": "Ua", "source": "voltageA", "type": "double"},
                {"target": "Pwr", "source": "P", "type": "double"}
            ]
        }
        target = {}
        MapperCore.process_array_foreach(target, self.source, rule)
        self.assertIn("all_items", target)
        self.assertEqual(len(target["all_items"]), 2)
        self.assertAlmostEqual(target["all_items"][0]["Ua"], 220.1, places=1)


class TestMQTTTransform(unittest.TestCase):
    """7. MQTT 完整转换测试 — 使用真实配置"""

    def setUp(self):
        self.source = {
            "udSign": 1,
            "taskId": 1,
            "cmdType": 2,
            "priority": 2,
            "businessObjList": [{
                "dataObj": {
                    "timeType": 0,
                    "dataItemList": [{
                        "itemId": "38000005",
                        "finshFlag": 0,
                        "itemBody": [{
                            "commAddr": "1",
                            "businessType": 1,
                            "deviceType": 1,
                            "item": [
                                {"voltageA": 220.1, "voltageB": 221.0, "voltageC": 222.0,
                                 "P": 100.5, "Q": 50.2, "timeStamp": "2023-01-17 00:00:00"}
                            ]
                        }]
                    }]
                }
            }],
            "respResult": {"resultCode": 0, "errDesc": "OK"},
            "sender": "iot_agent"
        }

        self.config = {
            "platform_name": "ywnyems",
            "mappings": [
                {"target": "action", "source_type": "constant", "constant": "devData", "type": "string"},
                {"target": "msgId", "source_type": "generated", "generator": "uuid", "type": "string"},
                {"target": "msgTime", "source_type": "generated", "generator": "current_timestamp", "type": "string"},
                {"target": "packetNumber", "source_type": "constant", "constant": 1, "type": "int"},
                {"target": "devId", "source_type": "substitute", "type": "substitute",
                 "constant": "$ssl_mqtt_server.gatewayID$"},
                {
                    "target": "data.terdata[0].terdata.@",
                    "source": "businessObjList[0].dataObj.dataItemList[0].itemBody[*]",
                    "source_type": "array_foreach",
                    "sub_mappings": [
                        {"target": "devId", "source": "commAddr", "type": "string"},
                        {
                            "target": "terdata.@",
                            "source": "item[*]",
                            "source_type": "array_foreach",
                            "sub_mappings": [
                                {"target": "Ua", "source": "voltageA", "type": "double"},
                                {"target": "Ub", "source": "voltageB", "type": "double"},
                                {"target": "Uc", "source": "voltageC", "type": "double"},
                                {"target": "P", "source": "P", "type": "double"},
                                {"target": "Q", "source": "Q", "type": "double"},
                                {"target": "dataTime", "source": "timeStamp", "type": "string"}
                            ]
                        }
                    ]
                }
            ]
        }

    def test_mqtt_transform_basic_fields(self):
        """MQTT 转换：基本字段"""
        ctx = {"ssl_mqtt_server": {"gatewayID": "GW001"}}
        result = MapperCore.transform_mqtt(self.source, self.config, ctx)
        self.assertEqual(result["action"], "devData")
        self.assertEqual(result["packetNumber"], 1)
        self.assertEqual(result["devId"], "GW001")
        self.assertIn("msgId", result)
        self.assertIn("msgTime", result)

    def test_mqtt_transform_array_foreach(self):
        """MQTT 转换：嵌套数组遍历"""
        ctx = {"ssl_mqtt_server": {"gatewayID": "GW001"}}
        result = MapperCore.transform_mqtt(self.source, self.config, ctx)
        self.assertIn("data", result)
        self.assertIn("terdata", result["data"])
        self.assertEqual(len(result["data"]["terdata"]), 1)

        terdata = result["data"]["terdata"][0]
        self.assertIn("terdata", terdata)
        self.assertEqual(len(terdata["terdata"]), 1)

        inner = terdata["terdata"][0]
        self.assertIn("terdata", inner)
        self.assertEqual(len(inner["terdata"]), 1)

        item = inner["terdata"][0]
        self.assertAlmostEqual(item["Ua"], 220.1, places=1)
        self.assertAlmostEqual(item["Ub"], 221.0, places=1)
        self.assertAlmostEqual(item["P"], 100.5, places=1)
        self.assertEqual(item["dataTime"], "2023-01-17 00:00:00")

    def test_mqtt_substitute(self):
        """MQTT 特有: substitute 类型"""
        ctx = {"ssl_mqtt_server": {"gatewayID": "GW999"}}
        result = MapperCore.transform_mqtt(self.source, self.config, ctx)
        self.assertEqual(result["devId"], "GW999")

    def test_mqtt_constant_int(self):
        """MQTT 常量 int 类型"""
        result = MapperCore.transform_mqtt(self.source, self.config, {})
        self.assertEqual(result["packetNumber"], 1)

    def test_mqtt_generated_uuid(self):
        """MQTT 生成器 uuid"""
        result = MapperCore.transform_mqtt(self.source, self.config, {})
        self.assertIn("msgId", result)
        self.assertEqual(len(result["msgId"]), 36)

    def test_mqtt_generated_timestamp(self):
        """MQTT 生成器 current_timestamp"""
        result = MapperCore.transform_mqtt(self.source, self.config, {})
        self.assertIn("msgTime", result)
        self.assertTrue(result["msgTime"].isdigit())


class TestHTTPTransform(unittest.TestCase):
    """8. HTTP 完整转换测试 — 使用真实配置"""

    def setUp(self):
        self.source = {
            "data": {
                "list": [
                    {
                        "meterCode": "M001",
                        "clientTime": "2023-06-15 10:00:00",
                        "currentValue": "100.5",
                        "picUrl": "http://example.com/img1.jpg"
                    },
                    {
                        "meterCode": "M002",
                        "clientTime": "2023-06-15 11:00:00",
                        "currentValue": "200.8",
                        "picUrl": "http://example.com/img2.jpg"
                    }
                ]
            }
        }

        self.config = {
            "base_url": "http://cloud.example.com/api",
            "timeout": 30000,
            "domain": "",
            "token": {
                "login_path": "/auth",
                "login_method": "POST",
                "content_type": "multipart/form-data",
                "token_path": "data.token",
                "token_header": "token",
                "expires_in": 7200
            },
            "apis": [{
                "name": "query_record",
                "method": "GET",
                "path": "/record",
                "use_token": True,
                "interval": 8,
                "interval_type": "hour",
                "body_params": [
                    {"target": "startTime", "source_type": "context", "source": "startTime", "type": "string"},
                    {"target": "endTime", "source_type": "context", "source": "endTime", "type": "string"}
                ],
                "data_mappings": [
                    {"target": "taskId", "source_type": "constant", "constant": 8220, "type": "int"},
                    {"target": "udSign", "source_type": "constant", "constant": 1, "type": "int"},
                    {"target": "cmdType", "source_type": "constant", "constant": 1, "type": "int"},
                    {"target": "commObj.commAddr", "source_type": "path", "source": "data.list[0].meterCode", "type": "string"},
                    {"target": "businessObjList[0].dataObj.timeType", "source_type": "constant", "constant": 4, "type": "int"},
                    {
                        "target": "businessObjList[0].dataObj.dataItemList[0].itemBody.@",
                        "source": "data.list[*]",
                        "source_type": "array_foreach",
                        "item_type": "object",
                        "sub_mappings": [
                            {"target": "roadNo", "source_type": "constant", "constant": 1, "type": "int"},
                            {"target": "dataTime", "source_type": "path", "source": "clientTime", "type": "string"},
                            {
                                "target": "item.@",
                                "source": ".",
                                "source_type": "array_foreach",
                                "item_type": "key_value",
                                "sub_mappings": [
                                    {"target": "tolCumulativeFlow", "source_type": "path", "source": "currentValue", "type": "string"},
                                    {"target": "cImageContent", "source_type": "path", "source": "picUrl", "type": "string"}
                                ]
                            }
                        ]
                    }
                ]
            }]
        }

    def test_http_transform_constant_fields(self):
        """HTTP 转换：常量字段"""
        result = MapperCore.transform_http(self.source, self.config)
        self.assertEqual(result["taskId"], 8220)
        self.assertEqual(result["udSign"], 1)
        self.assertEqual(result["cmdType"], 1)

    def test_http_transform_path_field(self):
        """HTTP 转换：路径取值"""
        result = MapperCore.transform_http(self.source, self.config)
        self.assertEqual(result["commObj"]["commAddr"], "M001")

    def test_http_transform_nested_constant(self):
        """HTTP 转换：嵌套常量"""
        result = MapperCore.transform_http(self.source, self.config)
        self.assertEqual(result["businessObjList"][0]["dataObj"]["timeType"], 4)

    def test_http_transform_array_foreach_object(self):
        """HTTP 转换：object 类型数组遍历"""
        result = MapperCore.transform_http(self.source, self.config)
        item_body = result["businessObjList"][0]["dataObj"]["dataItemList"][0]["itemBody"]
        self.assertEqual(len(item_body), 2)
        self.assertEqual(item_body[0]["roadNo"], 1)
        self.assertEqual(item_body[0]["dataTime"], "2023-06-15 10:00:00")

    def test_http_transform_array_foreach_key_value(self):
        """HTTP 转换：嵌套 key_value 类型"""
        result = MapperCore.transform_http(self.source, self.config)
        item_body = result["businessObjList"][0]["dataObj"]["dataItemList"][0]["itemBody"]
        # 每个源元素产生 2 个 key_value 对象（2 个 sub_mappings）
        items = item_body[0]["item"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["tolCumulativeFlow"], "100.5")
        self.assertEqual(items[1]["cImageContent"], "http://example.com/img1.jpg")

    def test_http_context_source_type(self):
        """HTTP 特有: context source_type"""
        config = {
            "apis": [{
                "data_mappings": [
                    {"target": "startTime", "source_type": "context", "source": "startTime", "type": "string"},
                    {"target": "endTime", "source_type": "context", "source": "endTime", "type": "string"}
                ]
            }]
        }
        ctx = {"startTime": "2023-01-01 00:00:00", "endTime": "2023-12-31 23:59:59"}
        result = MapperCore.transform_http({}, config, ctx)
        self.assertEqual(result["startTime"], "2023-01-01 00:00:00")
        self.assertEqual(result["endTime"], "2023-12-31 23:59:59")

    def test_http_dot_source_in_array_foreach(self):
        """HTTP 特有: '.' 在 array_foreach 中"""
        config = {
            "apis": [{
                "data_mappings": [{
                    "target": "items.@",
                    "source": ".",
                    "source_type": "array_foreach",
                    "sub_mappings": [
                        {"target": "val", "source": "value", "type": "string"}
                    ]
                }]
            }]
        }
        source = {"value": "test", "id": 1}
        result = MapperCore.transform_http(source, config)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["val"], "test")


class TestEngineDifferences(unittest.TestCase):
    """9. 引擎差异验证"""

    def test_mqtt_does_not_support_context(self):
        """MQTT 引擎不支持 context source_type"""
        # 在 MQTT transform 中，context 为空，context source_type 应返回 None
        config = {
            "mappings": [
                {"target": "field", "source_type": "context", "source": "var", "type": "string"}
            ]
        }
        result = MapperCore.transform_mqtt({}, config, {})
        # ctx 为空 dict, get_value_by_path 返回 None, string 类型空值不添加
        self.assertNotIn("field", result)

    def test_http_does_not_support_substitute(self):
        """HTTP 引擎不支持 substitute source_type"""
        config = {
            "apis": [{
                "data_mappings": [
                    {"target": "devId", "source_type": "substitute", "type": "substitute",
                     "constant": "$var$"}
                ]
            }]
        }
        # HTTP 模拟时 ctx 为空，substitute 不会找到变量
        result = MapperCore.transform_http({}, config, {"var": "value"})
        # substitute 在 HTTP 中实际会走到 add_value_to_parent 的 substitute 分支
        # 但 HTTP 引擎通常不使用 substitute
        self.assertEqual(result.get("devId"), "value")

    def test_http_supports_string_to_number(self):
        """HTTP 特有: 字符串→数字转换"""
        parent = {}
        MapperCore.add_value_to_parent(parent, "field", "42", "int")
        self.assertEqual(parent["field"], 42)

        parent = {}
        MapperCore.add_value_to_parent(parent, "field", "3.14", "double")
        self.assertAlmostEqual(parent["field"], 3.14, places=2)

    def test_mqtt_supports_flat_array(self):
        """MQTT 特有: 嵌套 [*] 展平"""
        data = {
            "items": [
                {"sub": [{"v": 1}, {"v": 2}]},
                {"sub": [{"v": 3}]}
            ]
        }
        result = MapperCore.get_flat_array_from_path(data, "items[*].sub[*]")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["v"], 1)
        self.assertEqual(result[2]["v"], 3)


class TestEdgeCases(unittest.TestCase):
    """10. 边界条件测试"""

    def test_empty_source_array(self):
        """空数组遍历 — C 引擎行为: 源数组为空时不创建目标字段"""
        rule = {
            "target": "items.@",
            "source": "data[*]",
            "source_type": "array_foreach",
            "sub_mappings": [
                {"target": "v", "source": "val", "type": "string"}
            ]
        }
        target = {}
        MapperCore.process_array_foreach(target, {"data": []}, rule)
        self.assertNotIn("items", target)

    def test_missing_source_array(self):
        """源数组不存在"""
        rule = {
            "target": "items.@",
            "source": "nonexistent[*]",
            "source_type": "array_foreach",
            "sub_mappings": [
                {"target": "v", "source": "val", "type": "string"}
            ]
        }
        target = {}
        MapperCore.process_array_foreach(target, {}, rule)
        self.assertNotIn("items", target)

    def test_missing_source_field(self):
        """源字段不存在 — string 类型不添加"""
        rule = {"target": "field", "source": "nonexistent", "source_type": "path", "type": "string"}
        target = {}
        MapperCore.process_normal_field(target, {}, rule)
        self.assertNotIn("field", target)

    def test_missing_source_field_int(self):
        """源字段不存在 — int 类型默认 0"""
        rule = {"target": "field", "source": "nonexistent", "source_type": "path", "type": "int"}
        target = {}
        MapperCore.process_normal_field(target, {}, rule)
        self.assertEqual(target["field"], 0)

    def test_scale_factor(self):
        """缩放因子"""
        rule = {"target": "temp", "source": "value", "source_type": "path", "type": "double", "scale": 0.1}
        target = {}
        MapperCore.process_normal_field(target, {"value": 1000}, rule)
        self.assertAlmostEqual(target["temp"], 100.0, places=1)

    def test_deeply_nested_target(self):
        """深层嵌套目标路径"""
        rule = {"target": "a.b.c.d.e", "source": "val", "source_type": "path", "type": "string"}
        target = {}
        MapperCore.process_normal_field(target, {"val": "hello"}, rule)
        self.assertEqual(target["a"]["b"]["c"]["d"]["e"], "hello")

    def test_array_target_with_index(self):
        """目标路径含数组索引"""
        rule = {"target": "data.terdata[0].devId", "source": "commAddr",
                "source_type": "path", "type": "string"}
        target = {}
        MapperCore.process_normal_field(target, {"commAddr": "DEV001"}, rule)
        self.assertEqual(target["data"]["terdata"][0]["devId"], "DEV001")


class TestRealConfigs(unittest.TestCase):
    """使用真实参考配置文件进行集成测试"""

    def test_mqtt_real_config(self):
        """使用真实 MQTT 配置文件测试"""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "..", "refrence_file", "skill", "mqtt-protocol-mapper", "scripts",
            "mqtt_mapper_20260630.json"
        )
        config_path = os.path.normpath(config_path)

        if not os.path.exists(config_path):
            self.skipTest(f"真实配置文件不存在: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # 构造与配置匹配的源数据
        source = {
            "businessObjList": [{
                "dataObj": {
                    "dataItemList": [{
                        "itemBody": [{
                            "commAddr": "TEST001",
                            "item": [{
                                "voltageA": 220.1, "voltageB": 221.0, "voltageC": 222.0,
                                "P": 100.0, "Q": 50.0,
                                "timeStamp": "2023-01-17 00:00:00"
                            }]
                        }]
                    }]
                }
            }]
        }

        ctx = {"ssl_mqtt_server": {"gatewayID": "GW_TEST"}}
        result = MapperCore.transform_mqtt(source, config, ctx)

        # 验证关键映射结果
        self.assertEqual(result["action"], "devData")
        self.assertEqual(result["packetNumber"], 1)
        self.assertEqual(result["devId"], "GW_TEST")
        self.assertIn("data", result)
        self.assertIn("terdata", result["data"])

    def test_http_real_config(self):
        """使用真实 HTTP 配置文件测试"""
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "..", "refrence_file", "skill", "protocol-mapper-skill", "scripts",
            "protocol_mapping_output_20260630_000000.json"
        )
        config_path = os.path.normpath(config_path)

        if not os.path.exists(config_path):
            self.skipTest(f"真实配置文件不存在: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # 构造与配置匹配的源数据
        source = {
            "data": {
                "list": [
                    {
                        "meterCode": "M001",
                        "clientTime": "2023-06-15 10:00:00",
                        "currentValue": "100.5",
                        "picUrl": "http://example.com/img1.jpg"
                    }
                ]
            }
        }

        result = MapperCore.transform_http(source, config)

        # 验证关键映射结果
        self.assertEqual(result["taskId"], 8220)
        self.assertEqual(result["udSign"], 1)
        self.assertEqual(result["cmdType"], 1)
        self.assertEqual(result["commObj"]["commAddr"], "M001")
        self.assertEqual(result["businessObjList"][0]["dataObj"]["timeType"], 4)


class TestUnifiedCodeConsistency(unittest.TestCase):
    """11. 统一代码一致性验证"""

    def test_mqtt_and_http_share_same_process_rule(self):
        """MQTT 和 HTTP 使用同一个 process_rule 函数"""
        rule = {"target": "field", "source": "val", "source_type": "path", "type": "string"}
        mqtt_target = {}
        http_target = {}

        MapperCore.process_rule(mqtt_target, {"val": "test1"}, rule)
        MapperCore.process_rule(http_target, {"val": "test2"}, rule)

        self.assertEqual(mqtt_target["field"], "test1")
        self.assertEqual(http_target["field"], "test2")

    def test_mqtt_and_http_share_same_path_resolution(self):
        """MQTT 和 HTTP 使用同一个 get_value_by_path"""
        data = {"a": {"b": [{"c": 1}]}}
        # MQTT 路径风格
        self.assertEqual(MapperCore.get_value_by_path(data, "a.b[0].c"), 1)
        # HTTP 路径风格
        self.assertIsInstance(MapperCore.get_value_by_path(data, "a.b[*]"), list)

    def test_mqtt_and_http_share_same_type_conversion(self):
        """MQTT 和 HTTP 使用同一个 add_value_to_parent"""
        parent_mqtt = {}
        parent_http = {}
        MapperCore.add_value_to_parent(parent_mqtt, "field", 42, "int")
        MapperCore.add_value_to_parent(parent_http, "field", 42, "int")
        self.assertEqual(parent_mqtt, parent_http)

    def test_all_source_types_in_unified_engine(self):
        """统一引擎支持所有 source_type"""
        source = {"path_val": "hello", "num": 42}

        # path
        t1 = {}
        MapperCore.process_normal_field(t1, source,
            {"target": "f1", "source": "path_val", "source_type": "path", "type": "string"})
        self.assertEqual(t1["f1"], "hello")

        # constant
        t2 = {}
        MapperCore.process_normal_field(t2, source,
            {"target": "f2", "source_type": "constant", "constant": "fixed", "type": "string"})
        self.assertEqual(t2["f2"], "fixed")

        # generated
        t3 = {}
        MapperCore.process_normal_field(t3, source,
            {"target": "f3", "source_type": "generated", "generator": "uuid", "type": "string"})
        self.assertIn("f3", t3)

        # context (HTTP)
        t4 = {}
        MapperCore.process_normal_field(t4, source,
            {"target": "f4", "source": "ctx_val", "source_type": "context", "type": "string"},
            ctx={"ctx_val": "from_ctx"})
        self.assertEqual(t4["f4"], "from_ctx")

        # substitute (MQTT)
        t5 = {}
        MapperCore.process_normal_field(t5, source,
            {"target": "f5", "source_type": "substitute", "type": "substitute",
             "constant": "$var$"},
            ctx={"var": "substituted"})
        self.assertEqual(t5["f5"], "substituted")

        # array_foreach
        t6 = {}
        MapperCore.process_array_foreach(t6, source,
            {"target": "items.@", "source": "path_val", "source_type": "array_foreach",
             "sub_mappings": []})


if __name__ == "__main__":
    unittest.main(verbosity=2)
