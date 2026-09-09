# 步骤1：协议文档分析结果

## 基本信息
- **品牌名称**: 安科瑞 (ACREL)
- **设备型号**: AMC系列智能电量采集监控装置
- **协议类型**: MODBUS-RTU
- **文档版本**: V3.10 (2025.2.20)

## 步骤2：modelNum 查找
- **型号名称**: AMC
- **所属品牌**: 安科瑞
- **型号编码 (modelNum)**: 440
- **设备类型**: 电表类

## 步骤3：classNum 查找
- **设备类型**: 电表
- **大类号 (classNum)**: 11

## 寄存器地址表（0100H-0119H 电气参数）

| 地址 | 名称 | R/W | 类型 | 描述 |
|------|------|-----|------|------|
| 0100H (256) | 相电压UA | R | Uint16 | 小数点1位，单位V |
| 0101H (257) | 相电压UB | R | Uint16 | 小数点1位，单位V |
| 0102H (258) | 相电压UC | R | Uint16 | 小数点1位，单位V |
| 0103H (259) | 线电压UAB | R | Uint16 | 小数点1位，单位V |
| 0104H (260) | 线电压UBC | R | Uint16 | 小数点1位，单位V |
| 0105H (261) | 线电压UAC | R | Uint16 | 小数点1位，单位V |
| 0106H (262) | 电流IA | R | Uint16 | 小数点3位，单位A |
| 0107H (263) | 电流IB | R | Uint16 | 小数点3位，单位A |
| 0108H (264) | 电流IC | R | Uint16 | 小数点3位，单位A |
| 0109H (265) | A相有功功率 | R | Int16 | 小数点3位，单位kW |
| 010AH (266) | B相有功功率 | R | Int16 | 小数点3位，单位kW |
| 010BH (267) | C相有功功率 | R | Int16 | 小数点3位，单位kW |
| 010CH (268) | 总有功功率 | R | Int16 | 小数点3位，单位kW |
| 010DH (269) | A相无功功率 | R | Int16 | 小数点3位，单位kvar |
| 010EH (270) | B相无功功率 | R | Int16 | 小数点3位，单位kvar |
| 010FH (271) | C相无功功率 | R | Int16 | 小数点3位，单位kvar |
| 0110H (272) | 总无功功率 | R | Int16 | 小数点3位，单位kvar |
| 0111H (273) | A相功率因数 | R | Int16 | -1000~1000，小数点3位 |
| 0112H (274) | B相功率因数 | R | Int16 | -1000~1000，小数点3位 |
| 0113H (275) | C相功率因数 | R | Int16 | -1000~1000，小数点3位 |
| 0114H (276) | 总功率因数 | R | Int16 | -1000~1000，小数点3位 |
| 0115H (277) | A相视在功率 | R | Uint16 | 小数点3位，单位VA |
| 0116H (278) | B相视在功率 | R | Uint16 | 小数点3位，单位VA |
| 0117H (279) | C相视在功率 | R | Uint16 | 小数点3位，单位VA |
| 0118H (280) | 总视在功率 | R | Uint16 | 小数点3位，单位VA |
| 0119H (281) | 频率F | R | Uint16 | 4500-6500，小数点2位 |

## 电能数据（003FH-0046H）

| 地址 | 名称 | R/W | 类型 | 描述 |
|------|------|-----|------|------|
| 003FH-0040H (63-64) | 吸收有功电能二次侧 | R | Uint32 | Val_t = word1×65536+word2, Val_s = Val_t/1000×PT×CT (kWh) |
| 0041H-0042H (65-66) | 释放有功电能二次侧 | R | Uint32 | 同上 |
| 0043H-0044H (67-68) | 感性无功电能二次侧 | R | Uint32 | 同上 (kvarh) |
| 0045H-0046H (69-70) | 容性无功电能二次侧 | R | Uint32 | 同上 (kvarh) |

## 配置参数

| 地址 | 名称 | R/W | 类型 | 描述 |
|------|------|-----|------|------|
| 0001H (1) | 通讯地址(高字节)/波特率(低字节) | R/W | Uint16 | 高字节:0001-0247, 低字节:0-3(38400/19200/9600/4800) |
| 0002H (2) | 控制字 | R/W | Uint16 | bit8:接线方式(0=三相四线,1=三相三线) |
| 0003H (3) | PT变比 | R/W | Uint16 | 1-9999 |
| 0004H (4) | CT变比 | R/W | Uint16 | 1-9999 |
| 0022H (34) | 开关量输入输出状态 | R/W | Uint16 | bit15:DO2, bit14:DO1, bit13-10:DI4-DI1 |
| 0023H (35) | DPT(高字节)/DCT(低字节) | R | Uint16 | DPT:3-7, DCT:1-5 |
| 0024H (36) | DPQ(高字节)/PQ符号(低字节) | R | Uint16 | DPQ:4-10, PQ符号:Q,Qc,Qb,Qa,P,Pc,Pb,Pa |
| 025DH (605) | 通讯模式 | R/W | Uint16 | 0:无校验,1:2停止位,2:奇校验,3:偶校验 |
| 0260H (608) | DO1报警选择 | R/W | Uint16 | 0000-9999 |

## 数据转换规则（6.5.2节）

1. 电压: Val_s = Val_t × 10^(DPT-4), 单位V
2. 电流: Val_s = Val_t × 10^(DCT-4), 单位A
3. 功率: Val_s = Val_t × 10^(DPQ-4), 单位W/var
4. 功率因数: Val_s = Val_t / 1000
5. 频率: Val_s = Val_t / 100
6. 电能: Val_t = word1×65536+word2, Val_s = Val_t/1000×PT×CT (kWh/kvarh)

## 原子标签映射

### 已找到的标签（原子标签定义.md）
| 中文名称 | 英文标签 | 量纲 |
|----------|----------|------|
| A相电压曲线 | voltageA | V |
| B相电压曲线 | voltageB | V |
| C相电压曲线 | voltageC | V |
| A相电流曲线 | currentA | A |
| B相电流曲线 | currentB | A |
| C相电流曲线 | currentC | A |
| 有功功率曲线（并网功率） | activePowT | kW |
| 无功功率曲线 | reactivePowT | kvar |
| 总功率因数曲线 | powFactorsT | - |
| 总视在功率曲线 | apparentPowT | VA |
| 电网频率 | gridFrequency | Hz |

### 需要自定义的标签
| 中文名称 | 建议英文标签 |
|----------|-------------|
| AB线电压 | lineVoltageAB |
| BC线电压 | lineVoltageBC |
| AC线电压 | lineVoltageAC |
| A相有功功率 | activePowA |
| B相有功功率 | activePowB |
| C相有功功率 | activePowC |
| A相无功功率 | reactivePowA |
| B相无功功率 | reactivePowB |
| C相无功功率 | reactivePowC |
| A相功率因数 | powFactorA |
| B相功率因数 | powFactorB |
| C相功率因数 | powFactorC |
| A相视在功率 | apparentPowA |
| B相视在功率 | apparentPowB |
| C相视在功率 | apparentPowC |
| PT变比 | ptRatio |
| CT变比 | ctRatio |
| 电压小数点(DPT) | dpt |
| 电流小数点(DCT) | dct |
| 功率小数点(DPQ) | dpq |
| PQ符号 | pqSign |
| 吸收有功电能二次侧 | absorbedActiveEnergy |
| 释放有功电能二次侧 | releasedActiveEnergy |
| 感性无功电能二次侧 | inductiveReactiveEnergy |
| 容性无功电能二次侧 | capacitiveReactiveEnergy |
| 通讯模式 | commMode |
| DO1报警选择 | alarmSelect |