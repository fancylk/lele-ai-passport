"""按键读取 (§六十八补5): 统一官方 BSP 电压分档 + 三采样消抖.

坑实录: 各 UI 曾沿用旧导游版的 300/800/2200mV 分档, 与官方 BSP
(config.py BTN_MV_*, 0-150/150-447/447-1900) 不符 —— OK 键实际电压落在
447-800 区间时被误判为 DOWN ("按 OK 却在切换"); 且 OK 按压行程会瞬时扫过
DOWN 电压段, 无消抖时产生幽灵 DOWN 边沿. read_btn() 返回**稳定状态**,
状态只在同一键连续 3 次采样后变化 (边沿恰好一次), 各 UI 用 btn != last_btn
判边沿的写法无需改动.
"""

from config import BTN_MV_UP, BTN_MV_DOWN, BTN_MV_OK

_state = None   # 当前稳定键: "UP"/"DOWN"/"OK"/None
_cand = None    # 候选键
_cand_n = 0
last_mv = 0     # 最近一次原始电压 (选择页自诊显示用)


def read_btn(adc):
    global _state, _cand, _cand_n
    global last_mv
    try:
        mv = (adc.read() * 3300) // 4095
        last_mv = mv
    except Exception:
        return _state
    if mv < BTN_MV_DOWN[0]:
        k = "UP"
    elif mv < BTN_MV_OK[0]:
        k = "DOWN"
    elif mv < BTN_MV_OK[1]:
        k = "OK"
    else:
        k = None
    if k == _state:
        _cand = None
        _cand_n = 0
        return _state
    if k == _cand:
        _cand_n += 1
        if _cand_n >= 3:
            _state = _cand
            _cand = None
            _cand_n = 0
    else:
        _cand = k
        _cand_n = 1
    return _state
