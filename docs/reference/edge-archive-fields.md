# 边缘建档字段与操作流程参考

本文件合并自两份历史文档的独有内容，作为维护者参考。
当前标准建档流程以包内四份维护中的参考文档为准：

- `agent_assets/skills/xlpa-device-archiving/references/excel-template-schema.md`
- `agent_assets/skills/xlpa-device-archiving/references/platform-dict-template-generation.md`
- `agent_assets/skills/xlpa-device-archiving/references/gateway-button-endpoints.md`
- `agent_assets/skills/xlpa-device-archiving/references/device-onboarding-playbook.md`

## 一、API 验证版操作流程（原 `设备建档操作流程.md`）

# 设备建档操作流程（API 验证版）

> 基于 10.0.11.89 / 10.0.11.175 实测验证，所有接口均通过纯 Python 调用确认。
> 后端地址：`http://{HOST}:7500`，appCode=5000。
> 配套录入模板：`设备建档录入模板v4.xlsx`（见文末附录）。

---

## 0. 登录与鉴权

### 步骤

```
1. POST /authorityManageServer/manage/action/getRSAKey/v1
   Body: {}
   Response: rtnData.keyName, rtnData.publicKeyValue (PEM 格式)

2. 生成随机 loginStr = secrets.token_hex(8)

3. POST /authorityManageServer/manage/action/login/v1
   Body: {
     loginName: RSA_encrypt(username),
     password: RSA_encrypt(password),
     keyName: step1.keyName,
     symmetricKey: RSA_encrypt(loginStr)
   }
   Response: rtnData.token, rtnData.sysUser.id

4. 后续每个请求必须携带 5 个 Header:
   - appCode: "5000"
   - token: login.token
   - tokenEncrypt: md5(token + loginStr + 毫秒时间戳)
   - dateTime: 毫秒时间戳字符串
   - userId: sysUser.id 字符串
```

### 加密细节

- RSA 模式：PKCS1v15
- 输入为 PEM 格式公钥（若 API 返回裸 Base64，需自行拼接 BEGIN/END PUBLIC KEY 头尾）
- 输出为 Base64 编码的密文字符串

---

## 1. 新建挂载点（父节点设备）

挂载点本身也是一个普通设备，创建后自动出现在设备树顶层。

### 接口

```
POST /devArchManager/doc/set/modifyDevice/v1
Body: {
  "deviceName": "挂载点名称",    // 必填，不可重复
  "deviceTypeId": "100015"       // 必填，虚拟网关=100015
}
Response: rtnCode=0, rtnData.deviceId (新设备ID)
```

### 注意

- 设备名称必须唯一，否则返回 rtnMsg 包含"已存在"
- 不传 deviceId 时为新增
- 建议用 `secrets.token_hex(4)` 生成唯一后缀

---

## 2. 新建设备

### 接口

```
POST /devArchManager/doc/set/modifyDevice/v1
Body: {
  "deviceName": "设备名称",      // 必填，不可重复
  "deviceTypeId": "100019"       // 必填，设备类型ID
}
Response: rtnCode=0, rtnData.deviceId
```

### 设备类型参考

| deviceTypeId | 名称 | 说明 |
|---|---|---|
| 100015 | 虚拟网关 | 常用作挂载点 |
| 100017 | 综合能源表 | 无规约 |
| 100019 | XLBA | 智慧能源单元 |
| 100023 | 照明 | 监测点，Modbus 类设备（10.0.17.23 实测建档） |
| 100024 | 配电房 | 监测点（10.0.17.23 实测建档） |

---

## 3. 挂载设备到父节点

### 接口

```
POST /devArchManager/doc/set/updateDeviceParent/v1
Body: {
  "deviceId": "子设备ID",
  "parentId": "父设备ID"       // 参数名是 parentId，不是 pid
}
Response: rtnCode=0
```

### 注意

- 参数名必须用 `parentId`，传 `pid` 会被静默忽略
- 挂载后设备出现在父节点下

---

## 4. 填写基本档案

基本档案页签的字段大部分是设备顶层字段，通过 modifyDevice 设置。

### 接口

```
POST /devArchManager/doc/set/modifyDevice/v1
Body: {
  "deviceId": "设备ID",
  "deviceName": "新名称",
  "identifier": "设备条码",
  "instDate": "2026-09-17",
  "instLocation": "安装地址",
  "taskIds": "实时数据",          // 基本档案"数据类型"，存顶层 taskIds
  "proxyCommType": "1",          // 代理通信方式 code
  "proxyCommPort": "8080",
  "upCommType": "2",             // 上行通信方式 code
  "billingMethod": "1"           // 计费方式 code
}
```

### 字段映射

| UI标签 | API字段 | 类型 | 备注 |
|---|---|---|---|
| 设备名称 | deviceName | 顶层 | 唯一 |
| 设备型号 | deviceTypeId | 顶层 | 27种可选 |
| 设备条码 | identifier | 顶层 | 唯一 |
| 安装时间 | instDate | 顶层 | YYYY-MM-DD |
| 安装地址 | instLocation | 顶层 | |
| **数据类型** | **taskIds** | **顶层** | **14项曲线/采集类型，非 extInfos.dataType** |
| 代理通信方式 | proxyCommType | 顶层 | code值 |
| 代理通信端口 | proxyCommPort | 顶层 | |
| 上行通信方式 | upCommType | 顶层 | code值 |
| 计费方式 | billingMethod | 顶层 | 仅2项 |

### 基本档案"数据类型"选项（taskIds，14项）

```
A芯电表曲线 / A芯总加组曲线 / 实时数据 / A芯电能表1分钟曲线 /
A芯脉冲曲线 / 5分钟组合曲线 / 5分钟分项采集 / A芯电能表5分钟曲线 /
A芯电能表1分钟功率曲线 / 15分钟分项采集 / 1分钟分项采集 /
15分钟组合曲线 / 1分钟组合曲线 / 日数据
```

> 关键发现（2026-09-17 Playwright 抓包验证）：基本档案页签的"数据类型"
> 下拉框对应的是**顶层 `taskIds` 字段**，选项为曲线/采集类型，
> 与设备拓展信息区域的"数据类型"（extInfos.dataType）是两个完全不同的字段。
> 之前误将 [FLOAT] 等值写入 extInfos.dataType 导致基本档案页签不显示，根因即在此。

---

## 5. 填写设备拓展信息

### 接口

```
POST /devArchManager/doc/set/modifyDevice/v1
Body: {
  "deviceId": "设备ID",
  "extInfos": [
    {"propertyCode": "nodeId", "propertyValue": "设备平台ID"},
    {"propertyCode": "mfgInfo", "propertyValue": "设备生厂商"},
    {"propertyCode": "nodeModel", "propertyValue": "设备型号"},
    {"propertyCode": "deviceType", "propertyValue": "设备类型"},
    {"propertyCode": "description", "propertyValue": "设备描述"},
    {"propertyCode": "modelId", "propertyValue": "设备模型编号"},
    {"propertyCode": "dataType", "propertyValue": "计量数据"}
  ]
}
```

### 字段映射（propertyCode 已经 getDeviceList 闭环验证）

| UI标签 | propertyCode | 备注 |
|---|---|---|
| 设备平台ID | nodeId | |
| 设备生厂商 | mfgInfo | |
| 设备型号 | nodeModel | |
| 设备类型 | deviceType | |
| 设备描述 | description | |
| 设备模型编号 | modelId | |
| **数据类型** | **dataType** | **计量数据 / 非计量数据** |

### 设备拓展信息"数据类型"选项（extInfos.dataType，2项）

```
计量数据 / 非计量数据
```

> 注意：此处的"数据类型"（extInfos.dataType）与基本档案的"数据类型"
> （taskIds）是两个不同字段，选项也完全不同。

### 注意

- extInfos 为增量合并，只传需要修改的条目即可
- 已有条目不会被删除

---

## 6. 填写参数设置 - 抄表参数

### 接口

```
POST /devArchManager/doc/set/modifyDevice/v1
Body: {
  "deviceId": "设备ID",
  "deviceAddress": "777001002003",   // 12位拼接
  "agentNum": "77",                   // 分路号（唯一性约束）
  "measuredPointNum": "77",           // 测量点号（唯一性约束）
  "protocolNumber": "协议代号",
  "baudRate": "1000bps",
  "proxyCommPort": "RS485-1",
  "collectorAddress": "采集器地址",
  "extInfos": [
    {"propertyCode": "userBigNo", "propertyValue": "用户大分类号"},
    {"propertyCode": "userSmallNo", "propertyValue": "2"},
    {"propertyCode": "aCommAddr", "propertyValue": "关联电表地址"},
    {"propertyCode": "brand", "propertyValue": "品牌编码"},
    {"propertyCode": "brandName", "propertyValue": "品牌名称"},
    {"propertyCode": "decimalNum", "propertyValue": "设备型号"},
    {"propertyCode": "decimalNumName", "propertyValue": "设备型号名称"}
  ]
}
```

### deviceAddress 12位拼接规则

```
deviceAddress = modbus地址(变长) + 通道号(3位补零) + 内机号(3位补零) + 设备序号(3位补零)

示例: modbus地址=777, 通道号=1, 内机号=2, 设备序号=3
     → "777" + "001" + "002" + "003" = "777001002003"

UI显示时自动拆分: 前段=modbus地址, 中3位=通道号, 中3位=内机号, 末3位=设备序号
```

### 唯一性约束

- `agentNum` + `measuredPointNum` 组合在同一父节点下不能重复
- 建议使用 77/88/99 等较大值避免冲突

### 抄表参数下拉选项（UI 实测，与页面一致）

| 下拉字段 | API字段 | 选项 |
|---|---|---|
| 通信速率 | baudRate | 300bps / 1000bps |
| 通信端口号 | proxyCommPort | RS485-1~4 / AC485-1~2 / ETH-1~2 / LoRa-1~6 / 4438-1~2 / MQTT / 控制模块 / 脉冲告警模块 / 监听RS485-1~2（共21项） |
| 抄表间隔 | extInfos.userSmallNo | 15秒 / 1分钟 / 5分钟 / 15分钟 / 60分钟 / 24小时 / 不抄表 |

### modbus skill 自动获取的字段（仅 6 个）

以下 6 个字段由 modbus 转换 skill 从规约管理获取，工程人员无需录入：

| UI标签 | propertyCode |
|---|---|
| 设备类型（用户大分类号） | userBigNo |
| 设备类型名称 | （随 userBigNo） |
| 品牌 | brand |
| 品牌名称 | brandName |
| 设备型号 | decimalNum |
| 设备型号名称 | decimalNumName |

> 其余抄表参数（modbus地址/通道号/内机号/设备序号/分路号/测量点号/协议代号/
> 通信速率/通信端口号/采集器地址/抄表间隔/关联电表地址）均需工程人员手动录入。

---

## 7. 填写参数设置 - 基本参数

### 接口

```
POST /devArchManager/doc/set/modifyDevice/v1
Body: {
  "deviceId": "设备ID",
  "extInfos": [
    {"propertyCode": "cT", "propertyValue": "100"},
    {"propertyCode": "pT", "propertyValue": "10"},
    {"propertyCode": "ratedVoltage", "propertyValue": "220"},
    {"propertyCode": "ratedCurrent", "propertyValue": "5"},
    {"propertyCode": "lineType", "propertyValue": "2"}
  ]
}
```

### lineType 值对照

| code | 显示 |
|---|---|
| 0 | 未知 |
| 1 | 三相三线 |
| 2 | 三相四线 |
| 3 | 单相 |

### 注意

- lineType 必须传**数字字符串**（"2"），不能传中文（"三相四线"）
- 传中文会导致 UI 显示 "NaN"

---

## 8. MODBUS数据透传（运维操作，非建档步骤）

### 性质说明

经实测验证（2026-09-17），MODBUS 数据透传区域是**设备实时通信界面**，
不属于建档配置存储范畴：
- "召测"按钮：从在线物理设备读取寄存器数据
- "下发"按钮：向在线物理设备写入寄存器数据
- UI "保存"按钮**不提交**此区域字段
- 字段值不存储在 modifyDevice 的 extInfos 中

### 字段列表（运行时使用）

| UI标签 | 说明 | 数据来源 |
|---|---|---|
| 分路号 | 复用 agentNum | 抄表参数设置 |
| 功能码 | MODBUS 功能码 | 召测/手动输入 |
| 基地址 | MODBUS 起始地址 | 召测/手动输入 |
| 地址运算公式 | 地址计算 | 手动输入 |
| 数据类型 | 数据格式（下拉） | [UINT16]/[SINT16]/[UINT32]/[SINT32]/[FLOAT]/[UBCD16]/[SBCD16] |
| 数据运算公式 | 数值转换 | 手动输入 |
| 数据字节排序 | 字节序（下拉） | AB/BA/ABCD/DCBA/BADC/CDAB |
| 数据值 | 读/写数据 | 召测/手动输入 |

### 对 Skill 的影响

- 建档 skill **不需要**填写此区域
- modbus 转换 skill 在**运行阶段**使用这些参数与设备通信
- Excel 模板中此区域标注为"运维操作，非建档必填"

---

## 9. 查询设备

### 9.1 获取设备树

```
POST /devArchManager/doc/get/getDeviceTree/v1
Body: {}
Response: rtnData = [树节点数组]
```

树节点字段（10.0.11.175）：
- `id`: 设备ID
- `name`: 设备名称
- `pid`: 父节点ID
- `deviceTypeId`: 设备类型
- `children`: 子节点数组

### 9.2 获取设备详情

```
POST /devArchManager/doc/get/getDeviceList/v1
Body: {"deviceId": "设备ID"}
Response: rtnData = [{完整设备对象，含43+字段和extInfos数组}]
```

### 9.3 获取子设备列表

```
POST /devArchManager/doc/get/getDeviceListByPId/v1
Body: {"deviceId": "父设备ID"}
Response: rtnData = [子设备数组]
```

### 9.4 获取字典选项

```
POST /sysConfigServer/dict/get/getDictItemList
Body: {"dictTypeCode": "CommunicationMode"}
Response: rtnData = [{itemCode, itemName, ...}]
```

### 9.5 获取设备类型列表

```
POST /devArchManager/doc/get/getDeviceTypeSelect/v1
Body: {}
Response: rtnData = [{id, name, ...}]
```

---

## 10. 修改设备

与新建使用同一接口，区别是**必须带 deviceId**。

```
POST /devArchManager/doc/set/modifyDevice/v1
Body: {
  "deviceId": "设备ID",     // 必须存在
  ...需要修改的字段...
}
```

### 部分更新特性

- 只传入需要修改的字段，未传入的字段保持不变
- extInfos 为增量合并，只传需要修改的条目
- 可用于修改任何页签的字段（基本档案/拓展信息/参数设置）

---

## 11. 删除设备

```
POST /devArchManager/doc/set/deleteDevice/v1
Body: {"deviceId": "设备ID"}
Response: rtnCode=0
```

### 注意

- 删除前需先删除/迁移所有子设备
- 操作不可逆

---

## 12. Skill 一键建档编排流程

```
输入: Excel模板文件路径（设备清单 Sheet，一行一设备）
  ↓
[解析Excel] 读取系统连接 + 设备清单每行
  ↓
[名称→code转换] 用数据源对照表将下拉文本转为 API code
  （设备型号名→deviceTypeId、通信方式名→code、接线方式名→code 等）
  ↓
[登录] getRSAKey → login → 获取 token
  ↓
[按挂载点分组] 挂载点名称相同的行归为一组
  ↓
[查找/创建挂载点]
  ├─ 按名称在设备树中搜索挂载点
  ├─ 如不存在 → modifyDevice 新建（deviceTypeId=100015）
  └─ 获取挂载点 deviceId
  ↓
[逐设备处理]
  ├─ [新建设备] modifyDevice {deviceName, deviceTypeId}
  ├─ [挂载] updateDeviceParent {deviceId, parentId}
  ├─ [调用 modbus skill 获取 6 个自动字段]
  │    userBigNo / brand / brandName / decimalNum / decimalNumName / 设备类型名称
  ├─ [填写基本档案] modifyDevice {deviceId, 顶层字段, taskIds}
  ├─ [填写设备拓展信息] modifyDevice {deviceId, extInfos: nodeId/mfgInfo/.../dataType}
  ├─ [填写抄表参数] modifyDevice {deviceId, deviceAddress拼接, agentNum, extInfos: userBigNo/...}
  └─ [填写基本参数] modifyDevice {deviceId, extInfos: cT/pT/lineType/...}
  ↓
[查询验证] getDeviceList → 对比所有字段值
  ↓
输出: 建档结果报告
```

### 关键转换规则

| 转换 | 说明 |
|---|---|
| deviceAddress 拼接 | modbus地址 + 通道号(3位) + 内机号(3位) + 设备序号(3位) = 12位 |
| 基本档案数据类型 | 下拉文本 → 顶层 taskIds |
| 拓展信息数据类型 | 计量数据/非计量数据 → extInfos.dataType |
| 接线方式 | 三相四线 → "2"（必须转数字 code） |
| 设备型号 | 645-2013版电表 → "100006" |

---

## 附录: 接口汇总

| 操作 | 方法 | 路径 | 关键参数 |
|------|------|------|---------|
| 获取RSA公钥 | POST | /authorityManageServer/manage/action/getRSAKey/v1 | {} |
| 登录 | POST | /authorityManageServer/manage/action/login/v1 | loginName, password, keyName, symmetricKey |
| 新增/修改设备 | POST | /devArchManager/doc/set/modifyDevice/v1 | deviceId(修改时), deviceName, deviceTypeId, ... |
| 挂载 | POST | /devArchManager/doc/set/updateDeviceParent/v1 | deviceId, parentId |
| 删除设备 | POST | /devArchManager/doc/set/deleteDevice/v1 | deviceId |
| 设备树 | POST | /devArchManager/doc/get/getDeviceTree/v1 | {} |
| 设备详情 | POST | /devArchManager/doc/get/getDeviceList/v1 | deviceId |
| 子设备列表 | POST | /devArchManager/doc/get/getDeviceListByPId/v1 | deviceId |
| 字典查询 | POST | /sysConfigServer/dict/get/getDictItemList | dictTypeCode |
| 设备类型 | POST | /devArchManager/doc/get/getDeviceTypeSelect/v1 | {} |

---

## 附录: 已知问题与关键发现

| 问题/发现 | 影响 | 状态 |
|------|------|------|
| **基本档案"数据类型"= taskIds** | 非 extInfos.dataType，选项为14项曲线/采集类型 | 已澄清(2026-09-17) |
| **三个同名的"数据类型"字段** | 基本档案=taskIds、拓展信息=extInfos.dataType、MODBUS=运行时 | 已区分 |
| **MODBUS数据透传不存储** | 该区域是实时通信界面，不通过modifyDevice保存 | 已确认(非bug) |
| lineType传中文显示NaN | 必须传数字编码字符串 | 已规避 |
| 设备名称/条码唯一性 | 重复时报错 | 已规避(随机后缀) |
| 分路号+测量点号唯一性 | 同父节点下不能重复 | 已规避(使用大值) |
| deviceAddress非12位UI显示空 | 必须拼接为12位 | 已规避 |
| 计费方式仅2项 | 统一电价/费率电价（非阶梯/分时） | 已修正 |
| 通信速率仅2项 | 300bps/1000bps（非1200/9600等） | 已修正 |
| 通信端口号是名称非数字 | RS485-1/ETH-1等，非8080 | 已修正 |

---

## 附录: Excel 模板结构（v4）

文件：`设备建档录入模板v4.xlsx`，4 个 Sheet：

| Sheet | 内容 |
|---|---|
| 说明 | 填写规则、三个数据类型字段说明 |
| 系统连接 | IP / 端口 / 账号 / 密码（不含挂载点） |
| 设备清单 | 一行一设备，49列，5个大分组彩色表头 |
| 数据源 | 下拉选项 + 名称→code 对照表 |

设备清单 5 个大分组：

```
[挂载点] [ 基本档案 ] [ 设备拓展信息 ] [ 抄表参数 ] [ 基本参数 ] [ MODBUS数据透传 ]
```

颜色语义：绿色表头=modbus自动获取(6列)、黄色表头=必填、白色表头=可选。
所有下拉选项与 UI 页面逐一核对一致。

## 二、后端直连版操作流程（原 `档案管理操作流程.md`）

# 智慧能源单元 — 档案管理操作流程(后端直连)

> 本文全部接口、参数与响应均于 2026-09-16 在 10.0.11.89 环境用 Python 实测验证。
> 少数未逐一实测的写路径已在文中显式标注,其余内容无推测成分。
> 环境:门户前端 http://10.0.11.89:8081(档案管理位于子应用 xl-system-manage);后端 http://10.0.11.89:7500。

---

## 1. 登录与鉴权(所有操作的前置步骤)

### 1.1 获取 RSA 公钥

```
POST http://10.0.11.89:7500/authorityManageServer/manage/action/getRSAKey/v1
Content-Type: application/json
请求体: {}
响应 rtnData: { "keyName": "...", "publicKeyValue": "..." }
```

### 1.2 登录

```
POST http://10.0.11.89:7500/authorityManageServer/manage/action/login/v1
请求体:
{
  "loginName":    RSA加密(用户名),
  "password":     RSA加密(密码),
  "keyName":      1.1 返回的 keyName,
  "symmetricKey": RSA加密(loginStr)
}
```

- 三个加密值均为 **RSA PKCS1v15 + Base64**。
- `loginStr` 为自生成随机串(实测用 16 位 hex),登录后**必须留存**,签名要用。
- 响应 `rtnData`: `{ "token": "...", "sysUser": { "id": ..., ... } }`。

### 1.3 请求签名头(之后每个请求必带 5 个头)

| 请求头 | 值 |
|---|---|
| appCode | 固定 `5000` |
| token | 登录返回的 token |
| tokenEncrypt | `md5(token + loginStr + 当前毫秒时间戳)` |
| dateTime | 当前毫秒时间戳(字符串) |
| userId | `sysUser.id` |

### 1.4 统一响应结构

```json
{ "rtnCode": 0, "rtnData": ..., "rtnMsg": "" }
```

- `:7500` 成功码为 **rtnCode = 0**;
- `rtnCode = 200` 为业务失败(实测场景:唯一性冲突),rtnMsg 带原因;
- 登录接口的 rtnMsg 为"请求成功"等文本,判断成败仍以 rtnCode 为准。

---

## 2. 新增设备

```
POST http://10.0.11.89:7500/devArchManager/doc/set/modifyDevice/v1
```

**规则:请求体不带 deviceId 即为新增。**

最小必填(实测成功):

```json
{ "deviceName": "modbus测试设备_01", "deviceTypeId": "100017" }
```

- `deviceAddress` 传入会持久化(实测)。
- **坑:请求体传 `pid` 不会生效**,新建后必须用第 4 节的挂载接口指定上级。
- 返回:`rtnCode=0`,`rtnData` = 新设备 ID(18 位数字字符串)。

设备类型选择:

- `POST /devArchManager/doc/get/getDeviceTypeList/v1`(空 body)返回全部 **32 个类型**,节点含 deviceTypeId / deviceTypeName / 规约名称等;
- 平台**无 Modbus 规约类型**,全部绑定电力规约(645 / 698 / 1376.1 / 8163 等);
- 实测常用类型:`100015` 虚拟网关、`100017` 综合能源(无规约)、`100019` XLBA。

---

## 3. 修改设备

同一接口,**请求体带已存在的 deviceId 即为部分更新**:

```json
{ "deviceId": "6000000432906947", "deviceAddress": "116000000000" }
```

- 仅传入字段被修改,未传字段全部保留(实测只改地址时,名称/类型/挂载关系均不变);
- `extInfos` 支持**单条增量写入**(实测):

```json
{
  "deviceId": "6000000432906947",
  "extInfos": [ { "propertyCode": "brandName", "propertyValue": "测试品牌" } ]
}
```

写入后原有 extInfos 条目(如 `dsTypeId`)保留,即 **extInfos 为增量合并语义**。

### 3.1 参数设置页的保存逻辑(UI 行为,与直连的差异)

- 页面 UI"参数设置 → 保存"按钮**实际调用的是 modifyDevice**(不是 modifyDeviceParam);
- UI 提交为表单全量:`deviceId / parentId / collectorAddress / proxyCommPort / measuredPointNum / protocolNumber / agentNum / deviceAddress / baudRate` + `extInfos` 数组(15 项);
- UI 会把"modbus地址"**补零成 12 位**存储(输入 `115` → 存储 `115000000000`),显示时再去尾零;
- **坑:实测把 UI 全量 payload(含 15 条空 extInfos)直接回放会报唯一性冲突(rtnCode=200),后端直连请使用最小字段**;
- 另一套参数接口 `POST /devArchManager/doc/set/modifyDeviceParam/v1` 已确认存在(前端代码),但 UI 保存不经过它,其写路径未实测。

### 3.2 "modbus地址是空的"排查结论(实测)

- 参数设置页的"modbus地址"输入框 = 设备档案的 `deviceAddress` 字段(同一数据);
- UI 按 **12 位格式**解析:存储 `115000000000` 时显示 `115`;**非 12 位值解析为空**;
- 因此纯 API 写短地址(如 `"115"`)会导致 UI 显示为空 —— 写 12 位形态即恢复正常显示;
- `getDeviceParam`(数据项参数组)与 `deviceAddress` 是**两套独立存储**,参数组为空不代表地址未设置。

---

## 4. 挂载 / 更换上级设备

```
POST http://10.0.11.89:7500/devArchManager/doc/set/updateDeviceParent/v1
{ "deviceId": "子设备ID", "parentId": "上级设备ID" }
```

- **参数名必须是 `parentId`**;实测传 `pid` 时接口返回"更换上级设备成功"但实际不生效;
- 挂载点本身也是普通设备(实测用 `100015` 虚拟网关类型创建),创建后自动出现在设备树顶层。

---

## 5. 删除设备

```
POST http://10.0.11.89:7500/devArchManager/doc/set/deleteDevice/v1
{ "deviceId": "..." }
```

返回 `rtnCode=0`(实测多次执行成功)。

---

## 6. 查询接口

| 接口 | 请求体 | 说明(均为实测) |
|---|---|---|
| /doc/get/getDeviceTree/v1 | `{}` | 全量设备树;节点字段:name / id / pid / deviceAddress / deviceTypeId / deviceTypeName / agentNum / measuredPointNum / deviceClassify / eigenValue / chipA / createTime / identifier / deviceSort / children |
| /doc/get/getDeviceListByPId/v1 | `{ "deviceId": ... }` | 反查直接子设备:`[{deviceId, deviceName, deviceAddress}]` |
| /doc/get/getDeviceList/v1 | `{ "deviceId": ... }` | 单设备完整档案,共 44 个字段(明细见《档案设备项清单.xlsx》Sheet 档案字段清单) |
| /doc/get/getDeviceTypeList/v1 | `{}` | 全部设备类型(含规约信息) |
| /doc/get/getDeviceTypeSelect/v1 | `{}` | 类型下拉(code/name),实测返回 100001~100021 等 |
| /doc/get/getDeviceParam/v1 | `{ "deviceId": ..., "itemIdS": ["20100039", ...] }` | 数据项参数组:`[{itemId, itemName, itemBody: {子字段...}}]`;未保存过的 item 返回空数组。实测样例:itemId=20100039"无线频道",itemBody={channelNo, currFrequency, workFrequency} |
| /doc/get/getWebConfig/v1 | `{ "fileName": "DeviceTab.json" }` | 按设备类型的页签配置,每个类型分 deviceConfig(设备形态)与 gatewayConfig(网关形态)两组 |
| /doc/get/getItemStructure/v1 | `{ "deviceIdList": [...] }` | 数据项结构;对无数据项的设备返回 null |

辅助字典(参数设置页加载时调用,实测):

- `getDictItemList`,`{ "dictTypeCode": "CommunicationMode" }` → 通信方式字典(实测 15 项:4G/5G物联网、以太网、RS485端口1~4、Lora、小无线、A芯通道、前置机、B芯通道、虚拟网关、MQTT、交流采样、B芯操作系统);
- `getDeviceBaseList`,`{ "chipA": "1" }` → A 芯设备清单(含其 extInfos:cT / pT / collCycle / dsTypeId);
- 参数设置页还会调用 `getOperPlatformToken` 获取规约管理平台 token,再调用规约管理后端 `api/Protocol/GetModbusTypes`(该系统响应格式为 `{code: 20000, ...}`,与档案管理后端不同)。

---

## 7. Python 调用骨架(已验证可运行)

```python
"""档案管理后端直连骨架(登录 + 新增 + 挂载 + 修改 + 删除)。"""

import base64
import hashlib
import secrets
import time

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

AUTH = "http://10.0.11.89:7500"
USER = "测试账号"
PWD = "测试密码"


def rsa_encrypt(public_key_pem: str, plain: str) -> str:
    """RSA PKCS1 v1.5 加密,返回 Base64。"""
    if "BEGIN" not in public_key_pem:
        public_key_pem = (
            "-----BEGIN PUBLIC KEY-----\n"
            + public_key_pem
            + "\n-----END PUBLIC KEY-----"
        )
    key = serialization.load_pem_public_key(public_key_pem.encode())
    return base64.b64encode(key.encrypt(plain.encode(), padding.PKCS1v15())).decode()


client = httpx.Client(timeout=20)
key_data = client.post(
    f"{AUTH}/authorityManageServer/manage/action/getRSAKey/v1", json={}
).json()["rtnData"]
login_str = secrets.token_hex(8)  # 必须留存,签名依赖
login = client.post(
    f"{AUTH}/authorityManageServer/manage/action/login/v1",
    json={
        "loginName": rsa_encrypt(key_data["publicKeyValue"], USER),
        "password": rsa_encrypt(key_data["publicKeyValue"], PWD),
        "keyName": key_data["keyName"],
        "symmetricKey": rsa_encrypt(key_data["publicKeyValue"], login_str),
    },
).json()["rtnData"]
token = login["token"]
user_id = str(login["sysUser"]["id"])


def call(path: str, payload: dict | None = None) -> dict:
    """带签名头调用 :7500 后端,失败时抛出异常。"""
    ts_ms = int(time.time() * 1000)
    sign = hashlib.md5(f"{token}{login_str}{ts_ms}".encode()).hexdigest()
    result = client.post(
        f"{AUTH}{path}",
        json=payload or {},
        headers={
            "appCode": "5000",
            "token": token,
            "tokenEncrypt": sign,
            "dateTime": str(ts_ms),
            "userId": user_id,
        },
    ).json()
    if result["rtnCode"] != 0:
        raise RuntimeError(f"{path} 失败: {result}")
    return result["rtnData"]


# 1) 新增(最小必填:deviceName + deviceTypeId)
dev_id = call("/devArchManager/doc/set/modifyDevice/v1",
              {"deviceName": "自动建档测试", "deviceTypeId": "100017"})

# 2) 挂载(参数名必须是 parentId,传 pid 不生效)
call("/devArchManager/doc/set/updateDeviceParent/v1",
     {"deviceId": dev_id, "parentId": "上级设备ID"})

# 3) 修改 modbus 地址(12 位形态,否则 UI 显示为空)
call("/devArchManager/doc/set/modifyDevice/v1",
     {"deviceId": dev_id, "deviceAddress": "116000000000"})

# 4) extInfos 单条增量写入(已有条目保留)
call("/devArchManager/doc/set/modifyDevice/v1", {
    "deviceId": dev_id,
    "extInfos": [{"propertyCode": "brandName", "propertyValue": "某品牌"}],
})

# 5) 查询完整档案(44 字段,明细见《档案设备项清单.xlsx》)
device = call("/devArchManager/doc/get/getDeviceList/v1", {"deviceId": dev_id})

# 6) 删除
call("/devArchManager/doc/set/deleteDevice/v1", {"deviceId": dev_id})
```

---

## 8. 实测坑位汇总

| # | 坑位 | 结论 |
|---|---|---|
| 1 | 新增时传 `pid` 指定上级 | 静默不生效;必须用 updateDeviceParent + `parentId` |
| 2 | updateDeviceParent 传 `pid` | 返回"更换上级设备成功"但树中关系不变 |
| 3 | deviceAddress 写短地址(如 "115") | 后端正常存储,但 UI 参数设置页解析为空 → 显示空;写 12 位形态(如 "116000000000")即可 |
| 4 | UI 全量保存 payload 直接回放 | 报唯一性冲突(rtnCode=200);直连一律用最小字段 |
| 5 | extInfos 误以为全量覆盖 | 实为增量合并,单条写入不影响其他条目 |
| 6 | getDeviceParam 返回 [] 误判地址未设 | 参数组(itemIdS/itemBody)与 deviceAddress 是两套存储 |
| 7 | :7500 响应码 | 成功是 rtnCode=0(不是 200);200 是业务失败 |
| 8 | modifyDevice 语义 | 新增/修改/参数页保存共用一个接口,以"是否带已存在 deviceId"区分 |


---

## 9. 多监测点类型与通信 IP/端口（v15 建档契约，10.0.17.23 实测）

本节记录 v15-engineer 模板建档链路对「监测点类型」与「通信 IP/端口」的处理规则，
是 `mcp_server/archiving`（generator / excel_reader / field_contract / profiles）的字段事实源说明。

### 9.1 监测点类型（XLBA / 照明 / 配电房，每类一张独立 sheet）

- 建档链路支持三类监测点，`deviceTypeId` 与边缘 `getDeviceTypeSelect` 同源：
  `XLBA电表=100019`、`照明=100023`、`配电房=100024`。
- **每种监测点类型各自占用一张独立明细 sheet**：`监测点·XLBA`、`监测点·照明`、
  `监测点·配电房`；列结构与 XLBA 完全一致（同一 20 列）。表 ↔ 类型（`sheet_name` /
  `device_type` / `device_type_id`）以 `field_contract.SHEET_SPECS` 中非网关 spec 为
  单一事实源，generator 循环建表、reader 经 `monitor_sheet_specs()` /
  `get_sheet_spec_by_name()` 取用。
- 监测点类型**由设备名称所在的 `监测点·X` 表决定**（名称在工作簿内全局唯一）；
  v15 **取消**「挂载关系」的「监测点类型」列，「挂载关系」只保留 挂载点 / 监测点 /
  网关类型 三列（网关仍由「网关类型」列定类型）。
- 解析规则：
  - **缺表可解析**：上传的工作簿只含全部支持类型中的一部分监测点 sheet 时，reader
    忽略缺失表、正常解析已存在的表（向后兼容：交付模板是全量，用户按需填其中若干）。
  - **跨表同名冲突**：同一设备名称出现在两张 `监测点·X` 表 → 类型冲突，报错。
  - **孤立监测点报错**：`挂载关系` 引用的监测点在任何 `监测点·X` 表都没有明细 →
    报错，不猜类型。
- 能力通用化：下发/召测/时钟不区分监测点类型，无类型能力旗；下发内容为执行时
  实时读取的后端当前参数（itemId `20200002`），参数项缺失/为空整批失败并提示
  先完成参数保存，不用模板值或默认报文替代。`照明` / `配电房` 的下发现场效果
  属实施后实测事项，代码不再预判；准入仅需 confirm，前置阶段状态以 warnings 呈现。

### 9.2 authParam 多态与端口驱动组装

`authParam` 是**多态字段**，落点由 `proxyCommPort` 决定（全类型统一），且
**档案侧与下发侧形态不同**：

| 端口类型 | `proxyCommPort`（ETH-1/ETH-2/MQTT = `40`/`41`/`50`） | 串口端口（RS485 等） |
|---|---|---|
| authParam 承载 | 通信 IP + 端口 | 电表密码 |
| 档案 `extInfos.authParam` | 5 段逗号串 `ip1,ip2,ip3,ip4,port` | 填了密码才写（透传） |
| 下发 `itemBody.authParam` | **恒存在**，12 位十六进制 `hex(IP)+hex(port)` | **恒存在**，无 IP+端口来源→占位 `EEEEEEEEEEEE` |
| 明细「IP地址/IP端口号」列 | 可填；填则两列齐 | **禁止填写**（填则阻断） |

- **IP 型端口档案侧**：`authParam = ipAddress.replace('.', ',') + ',' + ipPort`，
  即恒为 5 段逗号串（示例：`192,168,1,11,21883`）；两列均留空时不填为 `",,,,"`。
  校验：IP 必须为合法 4 段 IPv4、端口为数字；二者只填其一则报错。
  证据：10.0.17.23 手工建档抓包。
- **下发侧（所有监测点类型统一，不按类型特殊处理）**：`itemBody.authParam`
  恒存在且恒为 12 位小写十六进制——填了 IP地址/IP端口号时编码为 IP 四段
  各 1 字节 + 端口 16 位大端（示例：`192.168.23.150:21883` → `c0a81796557b`）；
  无 IP+端口来源（串口端口、IP 型端口两列留空、端口未填）时统一取页面
  占位默认 `EEEEEEEEEEEE`。已是 12 位十六进制的输入值小写原样保留。
  证据：2026-10-21 现场下发抓包（ETH-1／comPort=40）。
  实现：`encode_auth_param_hex` + `normalize_auth_param_for_deploy`；
  端口超出 16 位时报错，不截断。
- **串口端口的档案侧**：`extInfos.authParam` 透传填写的电表密码；若填写
  「IP地址/IP端口号」列则报错阻断（无 IP 型端口承载）。字典名
  「通信密码（电表）」是 RS485 语义下的历史遗留。密码因无法按 IP+端口
  编码，**下发侧不携带密码值**，退回占位默认。占位默认随现场而异
  （Path B 175 为 `000000000000`），需偏离时由显式输入承载。
- IP/端口两列经 profile 组装后从明细输入清除，不再作为未知输入参与序列化。
- **免模板直连下发**：读回的后端现值同样过 `normalize_auth_param_for_deploy`
  归一（缺键或仍为五段串时补/转成 12 位十六进制）。
- 历史纠正：早期曾判「固定默认 `EEEEEEEEEEEE` 非实测契约」而整体省略该键，
  已被两份现场下发抓包推翻——20200002 的 `itemBody` 始终包含 `authParam`。
- 落点常量 `IP_PORTS = {"40", "41", "50"}` 定义于 `field_contract`，供各监测点 profile 引用。
  注：完整 IP 端口集合仅 `40` 已实测，`41/50` 按语义纳入，需现场各端口类型核验。

### 9.3 dsTypeId 派生分支

`extInfos.dsTypeId` 按「用户大分类号 `userBigNo`」是否填写分两支：

- `userBigNo` **已填**：`dsTypeId = deviceTypeId + userBigNo`，其中 `userBigNo` 补零至 2 位
  （边缘端期望两位数字格式，如 `09` 而非 `9`）。示例：XLBA `100019` + 环境传感器 `09` → `10001909`。
- `userBigNo` **未填**：`dsTypeId = deviceTypeId` 本身（照明/配电房实测：`100023` / `100024`）。

### 9.4 契约证据状态

- `ip` / `port`：经 10.0.17.23 手工建档抓包 + 脚本建档实测，已由 `UNVERIFIED` 升为 `VERIFIED`，
  语义为「经 `authParam` 端口驱动承载」，允许进入可执行模板。
- `authParam`（派生）：`source=DERIVED`，`derived_deps=("ip","port","proxyCommPort")`，
  `archive_ext_key="authParam"`，`readback_path="extInfos.authParam"`，`VERIFIED`。
- `proxyCommType`（监测点级）：落点仍未核实，维持 `UNVERIFIED` 不写入；已降为「声明但不硬阻断」的列。
