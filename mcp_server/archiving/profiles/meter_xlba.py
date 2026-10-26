"""XLBA 电表 profile。

XLBA 电表叶子建档使用 deviceTypeId=100019，通讯地址 identifier 通常
直接等于 deviceAddress（不走网关条码转换）。下发数据项 itemId=20200002
（抄表参数），仅编码用户填写或可追溯派生的字段，不补历史样本默认值。

码值映射统一来自 field_contract.py（单一事实源），本模块不再维护重复映射。
"""

from __future__ import annotations

__all__ = ["MeterXlbaProfile"]

from ..converter import AddressConversionError, validate_device_address
from .base import (
    METER_DEPLOY_ITEM_ID,
    METER_XLBA_TYPE_ID,
    DeviceProfile,
    ProfileResult,
    AUTH_PARAM_PLACEHOLDER,
    assemble_auth_param,
    encode_auth_param_hex,
    normalize_auth_param_for_deploy,
)

# 监测点明细声明支持的列（按名称关联，中文表头已由 reader 翻译为 propertyCode）
_DECLARED_COLUMNS = {
    "deviceBarcode", "roadNo", "commAddr", "protocolCode", "measurNo", "comPort",
    "baudRate", "feeNum", "integerNum", "decimalNum", "authParam",
    "collCommAddr", "userBigNo", "userSmallNo", "aCommAddr",
    # 档案顶层通信字段（v6 模板新增列）
    "stopDigit", "checkDigit", "dataDigit", "protocolNumber", "proxyCommPort",
    # 品牌/型号（友好名列，映射到 extInfos.brand / extInfos.decimalNum code）
    "brand", "model",
    "agentNum", "measuredPointNum", "collectorAddress",
    # extInfos 扩展字段（变比/品牌/型号等）
    "cT", "pT", "brand", "brandName", "decimalNumName", "collCycle",
    "lineType", "ratedCurrent", "ratedVoltage", "dsTypeId",
    "interval", "ipAddress", "ipPort", "proxyCommType", "deviceName",
}
# itemBody 中应为整数的字段
_INT_FIELDS = {
    "roadNo", "protocolCode", "measurNo", "comPort", "feeNum",
    "integerNum", "decimalNum", "userBigNo", "userSmallNo",
}
_COMM_ADDR_REPETITION = "2"

# 下拉友好名 -> 后端码值映射（用户大分类号）
_USER_BIG_NO_MAP = {"电表类": "11"}
# extInfos 输出顺序（对齐监测点3 回读顺序，便于逐字段比对）
_EXT_INFO_KEYS = (
    "brand", "brandName", "decimalNum", "decimalNumName", "userBigNo",
    "userSmallNo", "collCycle", "dsTypeId", "cT", "pT", "feeNum",
    "integerNum", "authParam", "aCommAddr", "lineType", "ratedCurrent",
    "ratedVoltage",
)


def _text(value: object) -> str:
    """保留零值并将工程输入规范为文本。"""
    return "" if value is None else str(value).strip()


def _map_code(raw, mapping: dict[str, str], default: str = "") -> str:
    """将下拉友好名翻译为后端码值。

    空值取显式默认；只接受映射名称或映射中已有的码值。

    Args:
        raw: 模板原始值（友好名或码值）。
        mapping: 友好名到码值的映射。
        default: 空值时的默认码值。

    Returns:
        翻译后的码值字符串。
    """
    text = _text(raw)
    if not text:
        return default
    normalized = {str(key): _text(value) for key, value in mapping.items()}
    if text in normalized and normalized[text]:
        return normalized[text]
    if text in normalized.values():
        return text
    raise ValueError(f"未知名称或码值: {text!r}")


def _to_int(value, default: int) -> int:
    """将值安全转换为整数，失败时返回默认值。

    Args:
        value: 待转换值。
        default: 转换失败时的默认值。

    Returns:
        整数结果。
    """
    if value in (None, ""):
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _compute_fee_num(baud_code: str, stop_code: str, check_code: str, data_code: str) -> int:
    """计算 feeNum 串口位域。

    design §6：feeNum = (baud << 5) | (stop << 4) | (check << 2) | data
    例如 115200/1位/无校验/8位 = (1<<5)|(0<<4)|(0<<2)|3 = 35

    Args:
        baud_code: 波特率码值（0-7）。
        stop_code: 停止位码值（0-1）。
        check_code: 校验位码值（0-3）。
        data_code: 数据位码值（0-3）。

    Returns:
        feeNum 位域值；任一参数无效时返回 0。
    """
    try:
        baud = int(baud_code)
        stop = int(stop_code)
        check = int(check_code)
        data = int(data_code)
    except (TypeError, ValueError):
        return 0
    return (baud << 5) | (stop << 4) | (check << 2) | data


class MeterXlbaProfile(DeviceProfile):
    """XLBA 电表（deviceTypeId=100019）建档与下发 profile。"""

    device_type = "XLBA电表"
    device_type_id = METER_XLBA_TYPE_ID
    profile_name = "meter_xlba"
    is_gateway = False
    #: 下发数据项 ID
    deploy_item_id = METER_DEPLOY_ITEM_ID

    def resolve(self, node, task_config, detail: dict) -> ProfileResult:
        """解析电表节点，生成建档 payload 与下发 itemBody。

        Args:
            node: 拓扑节点。
            task_config: 任务配置。
            detail: XLBA 电表明细行字段。

        Returns:
            ProfileResult，含 base_payload、deploy_item_body 与错误/提示。
        """
        # 懒加载 field_contract 码值映射（避免循环导入）
        from ..field_contract import (
            COMM_PORT_CODE_MAP,
            IP_PORTS,
            _BAUD_RATE_CODE_MAP,
            _CHECK_DIGIT_CODE_MAP,
            _DATA_DIGIT_CODE_MAP,
            _INTERVAL_CODE_MAP,
            _PROTOCOL_NUMBER_CODE_MAP,
            _STOP_DIGIT_CODE_MAP,
        )

        result = ProfileResult()
        detail = dict(detail or {})
        for col in self._undeclared_columns(detail, _DECLARED_COLUMNS):
            if _text(detail[col]):
                result.errors.append(f"XLBA 明细列 {col!r} 未声明落点，禁止忽略已填值")

        # 兼容已有字段名，但同一语义的两份输入冲突时不静默选取。
        aliases = {
            "userSmallNo": ("interval",),
            "protocolNumber": ("protocolCode",),
            "proxyCommPort": ("comPort",),
            "roadNo": ("agentNum",),
            "measurNo": ("measuredPointNum",),
            "collectorAddress": ("collCommAddr",),
        }
        mappings = {
            "userBigNo": (
                getattr(task_config, "user_big_no_name_to_code", None)
                or _USER_BIG_NO_MAP
            ),
            "userSmallNo": _INTERVAL_CODE_MAP,
            "protocolNumber": _PROTOCOL_NUMBER_CODE_MAP,
            "baudRate": _BAUD_RATE_CODE_MAP,
            "stopDigit": _STOP_DIGIT_CODE_MAP,
            "checkDigit": _CHECK_DIGIT_CODE_MAP,
            "dataDigit": _DATA_DIGIT_CODE_MAP,
        }
        for key in set(aliases) | set(mappings):
            values = [_text(detail.get(name)) for name in (key, *aliases.get(key, ()))]
            values = [value for value in values if value]
            try:
                if key == "proxyCommPort":
                    # 只增加友好名转换，原数字输入仍交给原有整数校验。
                    values = [COMM_PORT_CODE_MAP.get(value, value) for value in values]
                if key in mappings:
                    values = [_map_code(value, mappings[key]) for value in values]
                if len(set(values)) > 1:
                    raise ValueError("同一字段的输入不一致")
                detail[key] = values[0] if values else ""
            except ValueError as exc:
                result.errors.append(f"{key}: {exc}")
                detail[key] = ""
        for names in aliases.values():
            for name in names:
                detail.pop(name, None)
        for key in _INT_FIELDS | {"agentNum", "measuredPointNum", "proxyCommPort"}:
            value = _text(detail.get(key))
            if value:
                try:
                    if isinstance(detail[key], bool) or int(value) < 0:
                        raise ValueError
                    detail[key] = str(int(value))
                except ValueError:
                    result.errors.append(f"{key} 必须为非负整数，实际为 {value!r}")
        fee_num = _text(detail.get("feeNum"))
        if fee_num and fee_num.isdecimal() and int(fee_num) > 255:
            result.errors.append("普通串口 feeNum 必须在0至255之间")

        # ── authParam 端口驱动组装（全类型统一，10.0.17.23 实测坐实）──
        # ETH/MQTT 端口：「IP地址/IP端口号」拼 5 段逗号串写入 extInfos.authParam；
        # RS485 等串口端口：authParam 承载电表密码透传，填了 IP 列则阻断。
        ip_raw = _text(detail.get("ipAddress"))
        ip_port_raw = _text(detail.get("ipPort"))
        password_raw = _text(detail.get("authParam"))
        try:
            assembled_auth = assemble_auth_param(
                ip_raw, ip_port_raw,
                _text(detail.get("proxyCommPort")), IP_PORTS,
                password=password_raw,
            )
        except ValueError as exc:
            result.errors.append(f"authParam: {exc}")
            assembled_auth = ""
        if ip_raw or ip_port_raw:
            # IP/端口输入已组装，不再作为未知输入参与后续序列化
            detail["ipAddress"] = ""
            detail["ipPort"] = ""
        if assembled_auth:
            detail["authParam"] = assembled_auth
            result.warnings.append(
                f"{node.node_key}: authParam 经通信IP端口组装为"
                f" {assembled_auth!r}（端口驱动落点）"
            )
        if result.errors:
            return result

        # ── 分路号 roadNo：明细优先，其次拓扑总览 ──
        # 未填 → 仅告警，省略依赖 roadNo 的下发/召测项，不中止本表解析（D3）；
        # 已填但非法 → 字段级错误（仅该目标写入失败，不连坐）。
        road_no_raw = _text(detail.get("roadNo")) or _text(node.road_no)
        road_no: int | None = None
        if not road_no_raw:
            result.warnings.append(
                f"电表 {node.node_key} 未填分路号 roadNo，"
                "省略 agentNum 与依赖分路号的下发/召测项"
            )
        else:
            try:
                road_no = int(road_no_raw)
                if road_no < 0:
                    raise ValueError
            except ValueError:
                result.errors.append(
                    f"电表 {node.node_key} 分路号 roadNo 不是非负整数: "
                    f"{road_no_raw!r}"
                )
                return result

        # ── 通讯地址：电表 identifier 通常直接等于 deviceAddress ──
        address = str(node.comm_address or "").strip()
        if not address:
            address = str(detail.get("commAddr", "") or "").strip()
        if not address:
            address = str(node.identifier or "").strip()
        if address:
            try:
                address = validate_device_address(address)
            except AddressConversionError as exc:
                result.errors.append(f"电表 {node.node_key} 通讯地址非法: {exc}")
                address = ""
        else:
            result.errors.append(
                f"电表 {node.node_key} 缺少通讯地址（commAddr / 通讯地址 / 条码 均为空）"
            )

        if not node.device_name:
            result.errors.append(f"电表 {node.node_key} 缺少设备名称")

        # ── 下拉友好名翻译（用户大分类号 / 抄表间隔，base 与 extInfos 共用）──
        # 用户大分类号优先用模板映射，硬编码兜底
        user_big_no = _map_code(
            detail.get("userBigNo", ""),
            getattr(task_config, "user_big_no_name_to_code", None)
            or _USER_BIG_NO_MAP,
            "",
        )
        interval_code = _map_code(
            detail.get("userSmallNo", ""), _INTERVAL_CODE_MAP,
            "",
        )

        # ── 建档 payload：档案顶层字段（getDeviceList 读，UI 参数设置页渲染）──
        # 码值映射统一来自 field_contract.py（单一事实源）
        # design §5/§6：不默认补全，只使用用户填写的值
        baud_raw = str(detail.get("baudRate", "") or "").strip()
        stop_raw = str(detail.get("stopDigit", "") or "").strip()
        check_raw = str(detail.get("checkDigit", "") or "").strip()
        data_raw = str(detail.get("dataDigit", "") or "").strip()
        # 四项只填写部分时无法完整编码 feeNum：不阻断，仅告警并跳过 feeNum 派生。
        serial_filled = [baud_raw, stop_raw, check_raw, data_raw]
        serial_count = sum(1 for v in serial_filled if v)
        if 0 < serial_count < 4:
            result.warnings.append(
                f"电表 {node.node_key} 串口参数不完整（已填 {serial_count}/4），"
                "不派生 feeNum，已填项照常写入"
            )
        if detail.get("proxyCommPort") in ("43", "44"):
            result.errors.append("端口43/44使用专用周期编码，当前串口模板不适用")
        base_payload = {
            "deviceName": node.device_name,
            "deviceTypeId": self.device_type_id,
            "deviceAddress": address,
            "commAddrRepetition": _COMM_ADDR_REPETITION,
            # 串口参数：用户填写才翻译，不填写则留空（不补默认）
            # baudRate 不写入档案顶层（不与平台『通信速率』挂钩），仅参与 feeNum 位域计算
            # 显式发空值以清除后端残留
            "baudRate": "",
            "stopDigit": _map_code(stop_raw, _STOP_DIGIT_CODE_MAP, "") if stop_raw else "",
            "checkDigit": _map_code(check_raw, _CHECK_DIGIT_CODE_MAP, "") if check_raw else "",
            "dataDigit": _map_code(data_raw, _DATA_DIGIT_CODE_MAP, "") if data_raw else "",
            # 协议代号：用户填写才翻译，不填写则留空（design §6：不得被固定 200 覆盖）
            "protocolNumber": _map_code(
                str(detail.get("protocolNumber", "") or "").strip(),
                _PROTOCOL_NUMBER_CODE_MAP, "",
            ) if str(detail.get("protocolNumber", "") or "").strip() else "",
            "proxyCommPort": str(
                detail.get("proxyCommPort", "") or detail.get("comPort", "")
                or ""
            ).strip(),
            # 分路号/测量点号在同网关内唯一；新建被后端默认成1，
            # 且 updateDeviceParent 挂载会再次重置，故修正由 edge_mount_device
            # 在挂载完成后二次 modifyDevice 执行
            # design §5：禁止测量点号自增，用户不填则留空
            # agentNum 仅在用户填了分路号时写入（下方条件添加）
            "measuredPointNum": _text(detail.get("measurNo")),
        }
        if road_no is not None:
            base_payload["agentNum"] = str(road_no)
        if node.identifier:
            base_payload["identifier"] = str(node.identifier).strip()
        if node.device_id:
            base_payload["deviceId"] = node.device_id
        collector = str(detail.get("collectorAddress", "") or "").strip()
        if collector:
            base_payload["collectorAddress"] = collector
        result.base_payload = base_payload

        # ── extInfos：档案扩展字段（仅序列化已填扩展项和可追溯派生字段）──
        # design §5/§6：不默认补全，只输出用户实际填写或可派生的字段
        ext_infos: dict[str, str] = {}
        # 品牌/型号必须命中模板映射，禁止把未知名称当码值。
        brand_raw = _text(detail.get("brand"))
        model_name = _text(detail.get("model"))
        brand_code = ""
        model_code = ""
        brand_map = getattr(task_config, "brand_name_to_code", {})
        model_map = getattr(task_config, "model_code_by_brand", {})
        try:
            if brand_raw:
                brand_code = _map_code(brand_raw, brand_map)
            if model_name:
                if not brand_code:
                    raise ValueError("填写型号必须同时填写有效品牌")
                brand_names = [
                    name for name, code in brand_map.items() if _text(code) == brand_code
                ]
                if brand_raw in brand_map:
                    brand_names = [brand_raw]
                if len(brand_names) != 1:
                    raise ValueError("品牌码值映射不唯一")
                model_code = _map_code(model_name, model_map.get(brand_names[0], {}))
            explicit_model = _text(detail.get("decimalNum"))
            if explicit_model and explicit_model != model_code:
                raise ValueError("decimalNum 必须与已映射的型号码一致")
        except ValueError as exc:
            result.errors.append(f"品牌/型号: {exc}")
            return result
        # 用户填写的扩展项（非空才输出）
        for key in _EXT_INFO_KEYS:
            raw = _text(detail.get(key))
            if raw:
                ext_infos[key] = raw
        # 品牌/型号：最终落点为 code（覆盖循环里的友好名/缺失）
        if brand_code:
            ext_infos["brand"] = brand_code
            if brand_raw in brand_map:
                ext_infos["brandName"] = brand_raw
        if model_code:
            ext_infos["decimalNum"] = model_code
            if model_name in model_map.get(brand_names[0], {}):
                ext_infos["decimalNumName"] = model_name
        # 用户大分类号仅取已映射的输入。
        if user_big_no:
            ext_infos["userBigNo"] = user_big_no
        # 抄表间隔（用户填写才输出）
        if interval_code:
            ext_infos["userSmallNo"] = interval_code
        # dsTypeId 派生（10.0.17.23 实测修正）：
        # - userBigNo 填写：dsTypeId = deviceTypeId + userBigNo（补零至 2 位）；
        #   边缘端期望两位数字格式（如 09 而非 9）
        # - userBigNo 未填：dsTypeId = deviceTypeId 本身（照明/配电房实测）
        user_big_no_raw = str(detail.get("userBigNo", "") or "").strip()
        if user_big_no_raw and user_big_no:
            user_big_no_padded = str(user_big_no).zfill(2)
            ext_infos["dsTypeId"] = f"{self.device_type_id}{user_big_no_padded}"
        else:
            ext_infos["dsTypeId"] = self.device_type_id
        result.ext_infos = ext_infos

        # ── 下发 itemBody（itemId=20200002）──
        # roadNo 仅用户填了分路号时下发；未填则省略（不虚构默认）。
        item_body: dict = {"commAddr": address}
        if road_no is not None:
            item_body["roadNo"] = road_no
        # baudRate 实测下发契约含该字段；不写档案顶层，显式发空串（对齐实测，清残留）
        item_body["baudRate"] = ""
        sources = {
            "protocolCode": base_payload.get("protocolNumber"),
            "measurNo": base_payload.get("measuredPointNum"),
            "comPort": base_payload.get("proxyCommPort"),
            "decimalNum": ext_infos.get("decimalNum"),
            "userBigNo": ext_infos.get("userBigNo"),
            "userSmallNo": ext_infos.get("userSmallNo"),
        }
        for key in ("integerNum", "authParam", "aCommAddr"):
            sources[key] = detail.get(key)
        for key, raw in sources.items():
            value = _text(raw)
            if not value:
                continue
            try:
                item_body[key] = int(value) if key in _INT_FIELDS else value
            except ValueError:
                result.errors.append(f"下发字段 {key} 不是整数: {value!r}")
        # 补全前端默认字段（对齐页面下发行为，避免 RTU DENY）
        # integerNum: 整数位位数，默认 6
        if "integerNum" not in item_body:
            item_body["integerNum"] = 6
        # authParam 下发侧恒存在且恒为 12 位十六进制（所有监测点类型统一，
        # 不按类型特殊处理）：
        # - 填了 IP地址/IP端口号 → hex(IP 4B) + hex(port 2B)；
        # - 其余情况（IP 型端口未填 IP、串口端口、端口未填）→ 占位默认全 E；
        # - 已是 12 位十六进制的输入值原样保留。
        # 实证：2026-10-21 现场抓包；档案 extInfos 侧形态不在此列。
        if ip_raw and ip_port_raw:
            try:
                item_body["authParam"] = encode_auth_param_hex(
                    ip_raw, ip_port_raw,
                )
            except ValueError as exc:
                result.errors.append(f"authParam: {exc}")
                item_body["authParam"] = AUTH_PARAM_PLACEHOLDER
        else:
            item_body["authParam"] = normalize_auth_param_for_deploy(
                assembled_auth or _text(item_body.get("authParam")),
            )
        # collCommAddr: 采集通信地址，默认 "000000000000"
        coll_addr = _text(base_payload.get("collectorAddress"))
        item_body["collCommAddr"] = coll_addr if coll_addr else "000000000000"
        # aCommAddr: A路通信地址，默认 ""
        if "aCommAddr" not in item_body:
            item_body["aCommAddr"] = ""
        # feeNum 位域计算（design §6）：仅当四项串口参数均填写时才计算
        # 不默认补全，不猜测
        baud_raw = str(detail.get("baudRate", "") or "").strip()
        stop_raw = str(detail.get("stopDigit", "") or "").strip()
        check_raw = str(detail.get("checkDigit", "") or "").strip()
        data_raw = str(detail.get("dataDigit", "") or "").strip()
        user_fee = _text(detail.get("feeNum"))
        if baud_raw and stop_raw and check_raw and data_raw:
            # 使用码值计算 feeNum（baudRate 不存档案，直接从翻译后码值取）
            baud_code = _map_code(baud_raw, _BAUD_RATE_CODE_MAP, "") if baud_raw else ""
            stop_code = base_payload.get("stopDigit", "")
            check_code = base_payload.get("checkDigit", "")
            data_code = base_payload.get("dataDigit", "")
            if baud_code and stop_code and check_code and data_code:
                item_body["feeNum"] = _compute_fee_num(
                    baud_code, stop_code, check_code, data_code,
                )
        elif user_fee:
            # 未填四项串口时使用已校验的显式feeNum。
            item_body["feeNum"] = _to_int(user_fee, 0)
        # 175 ParamSetMonitorThreeT.save 将四下拉位域保存到扩展属性。
        # 不写未填写项，也不将合法零值改成1。
        if "feeNum" in item_body:
            if user_fee and int(user_fee) != item_body["feeNum"]:
                result.errors.append("feeNum 与四项串口参数不一致")
            ext_infos["feeNum"] = str(item_body["feeNum"])
        result.deploy_item_body = item_body
        return result
