import json, datetime

# 0025H-003EH 动态公式方案
# 电压/电流/功率 使用 DPT/DCT/DPQ 跨寄存器引用
# 电能二次侧 使用 PT*CT 跨寄存器引用

labels_config = [
    # === 电气参数 26项 (0025H-003EH) ===
    # 电压 (DPT公式: Val_s = Val_t * 10^(DPT-4))
    ('voltageA', 37, '[UINT16]', 'AB', "$D*pow(10,($'dpt'-4))"),
    ('voltageB', 38, '[UINT16]', 'AB', "$D*pow(10,($'dpt'-4))"),
    ('voltageC', 39, '[UINT16]', 'AB', "$D*pow(10,($'dpt'-4))"),
    ('lineVoltageAB', 40, '[UINT16]', 'AB', "$D*pow(10,($'dpt'-4))"),
    ('lineVoltageBC', 41, '[UINT16]', 'AB', "$D*pow(10,($'dpt'-4))"),
    ('lineVoltageAC', 42, '[UINT16]', 'AB', "$D*pow(10,($'dpt'-4))"),
    # 电流 (DCT公式: Val_s = Val_t * 10^(DCT-4))
    ('currentA', 43, '[UINT16]', 'AB', "$D*pow(10,($'dct'-4))"),
    ('currentB', 44, '[UINT16]', 'AB', "$D*pow(10,($'dct'-4))"),
    ('currentC', 45, '[UINT16]', 'AB', "$D*pow(10,($'dct'-4))"),
    # 有功功率 (DPQ公式: Val_s = Val_t * 10^(DPQ-4))
    ('activePowA', 46, '[SINT16]', 'AB', "$D*pow(10,($'dpq'-4))"),
    ('activePowB', 47, '[SINT16]', 'AB', "$D*pow(10,($'dpq'-4))"),
    ('activePowC', 48, '[SINT16]', 'AB', "$D*pow(10,($'dpq'-4))"),
    ('activePowT', 49, '[SINT16]', 'AB', "$D*pow(10,($'dpq'-4))"),
    # 无功功率 (DPQ公式)
    ('reactivePowA', 50, '[SINT16]', 'AB', "$D*pow(10,($'dpq'-4))"),
    ('reactivePowB', 51, '[SINT16]', 'AB', "$D*pow(10,($'dpq'-4))"),
    ('reactivePowC', 52, '[SINT16]', 'AB', "$D*pow(10,($'dpq'-4))"),
    ('reactivePowT', 53, '[SINT16]', 'AB', "$D*pow(10,($'dpq'-4))"),
    # 功率因数 (固定公式: Val_s = Val_t/1000)
    ('powFactorA', 54, '[UINT16]', 'AB', "$D/1000"),
    ('powFactorB', 55, '[UINT16]', 'AB', "$D/1000"),
    ('powFactorC', 56, '[UINT16]', 'AB', "$D/1000"),
    ('powFactorsT', 57, '[UINT16]', 'AB', "$D/1000"),
    # 视在功率 (DPQ公式)
    ('apparentPowA', 58, '[UINT16]', 'AB', "$D*pow(10,($'dpq'-4))"),
    ('apparentPowB', 59, '[UINT16]', 'AB', "$D*pow(10,($'dpq'-4))"),
    ('apparentPowC', 60, '[UINT16]', 'AB', "$D*pow(10,($'dpq'-4))"),
    ('apparentPowT', 61, '[UINT16]', 'AB', "$D*pow(10,($'dpq'-4))"),
    # 频率 (固定公式: Val_s = Val_t/100)
    ('gridFrequency', 62, '[UINT16]', 'AB', "$D/100"),
]

# === 电能数据 4项 (003FH-0046H) ===
energy_config = [
    # 电能二次侧: Val_t = word1*65536+word2, Val_s = Val_t/1000*PT*CT
    ('absorbedActiveEnergy', 63, '[UINT32]', 'ABCD', "$D/1000*$'ptRatio'*$'ctRatio'"),
    ('releasedActiveEnergy', 65, '[UINT32]', 'ABCD', "$D/1000*$'ptRatio'*$'ctRatio'"),
    ('inductiveReactiveEnergy', 67, '[UINT32]', 'ABCD', "$D/1000*$'ptRatio'*$'ctRatio'"),
    ('capacitiveReactiveEnergy', 69, '[UINT32]', 'ABCD', "$D/1000*$'ptRatio'*$'ctRatio'"),
]

# === 配置参数 8项 ===
config_items = [
    # 0023H: 高字节=DPT(3-7), 低字节=DCT(1-5)
    ('dpt', 35, '[8:15]', 'AB', ""),
    ('dct', 35, '[0:7]', 'AB', ""),
    # 0024H: 高字节=DPQ(4-10), 低字节=PQ符号位
    ('dpq', 36, '[8:15]', 'AB', ""),
    ('pqSign', 36, '[0:7]', 'AB', ""),
    # PT/CT变比
    ('ptRatio', 3, '[UINT16]', 'AB', ""),
    ('ctRatio', 4, '[UINT16]', 'AB', ""),
    # 通讯模式/报警选择
    ('commMode', 605, '[UINT16]', 'AB', ""),
    ('alarmSelect', 608, '[UINT16]', 'AB', ""),
]

all_items = labels_config + energy_config + config_items

labelList = []
tag_names = []

for name, addr, dtype, dorder, dexpr in all_items:
    tag_names.append(name)
    label = {
        "name": name,
        "read": {
            "func_code": 3,
            "data_type": dtype,
            "data_order": dorder,
            "addr_base": addr,
            "addr_exprs": "",
            "data_exprs": dexpr
        }
    }
    labelList.append(label)

config = {
    "prtlType": "MODBUS-RTU",
    "modelNum": 440,
    "classNum": 11,
    "taskList": [{
        "labels": tag_names
    }],
    "labelList": labelList
}

now = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
filename = f'安科瑞_电表类_{now}.json'
filepath = f'e:/codeGIT/skill/skill-modbus/output/{filename}'

with open(filepath, 'w', encoding='utf-8') as f:
    json.dump(config, f, ensure_ascii=False, indent='\t')

print(f'File: {filepath}')
print(f'Total labels: {len(tag_names)}')
for i, name in enumerate(tag_names):
    print(f'  {i+1}. {name}')