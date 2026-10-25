#!/usr/bin/env python3
"""Windows 默认录制设备枚举/热切换原型 (纯 ctypes COM, 零依赖).

- IMMDeviceEnumerator 枚举 capture 端点 + 读当前默认
- IPolicyConfig(未公开 COM) SetDefaultEndpoint 热切换默认设备
用法: python spike_win_micswitch.py [list|switch <名称子串>|restore]
"""

import ctypes
import sys
from ctypes import POINTER, byref, c_void_p, c_wchar_p
from ctypes import wintypes as wt

ole32 = ctypes.OleDLL("ole32")


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def guid(s):
    g = GUID()
    ole32.CLSIDFromString(s, byref(g))
    return g


CLSID_MMDeviceEnumerator = guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
CLSID_PolicyConfigClient = guid("{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}")
IID_IPolicyConfig = guid("{f8679f50-850a-41cf-9c72-430f290290c8}")


class PKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wt.DWORD)]


PKEY_Device_FriendlyName = PKEY()
ole32.CLSIDFromString("{a45c254e-df1c-4efd-8020-67d146a850e0}",
                      byref(PKEY_Device_FriendlyName.fmtid))
PKEY_Device_FriendlyName.pid = 14


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("pad", ctypes.c_ubyte * 6),
                ("pwszVal", c_void_p)]


class Com:
    """极简 COM vtable 调用器."""

    def __init__(self, ptr):
        self.ptr = ptr

    def call(self, idx, *args, argtypes=()):
        vtbl = ctypes.cast(
            ctypes.cast(self.ptr, POINTER(c_void_p)).contents,
            POINTER(c_void_p))
        fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(vtbl[idx])
        return fn(self.ptr, *args)


def co_init():
    try:
        ole32.CoInitializeEx(None, 2)   # COINIT_APARTMENTTHREADED
    except OSError:
        pass  # 已初始化


def get_enumerator():
    enum = c_void_p()
    ole32.CoCreateInstance(byref(CLSID_MMDeviceEnumerator), None, 1,
                           byref(IID_IMMDeviceEnumerator), byref(enum))
    return enum


def list_capture_devices(enum):
    """[(id, name), ...] 与当前默认 (id, name)."""
    coll = c_void_p()
    Com(enum).call(3, 1, 1, byref(coll),
                   argtypes=(ctypes.c_int, ctypes.c_int, POINTER(c_void_p)))
    n = wt.DWORD()
    Com(coll).call(3, byref(n), argtypes=(POINTER(wt.DWORD),))
    out = []
    for i in range(n.value):
        dev = c_void_p()
        Com(coll).call(4, i, byref(dev),
                       argtypes=(ctypes.c_uint, POINTER(c_void_p)))
        out.append(device_info(dev))
    default = c_void_p()
    Com(enum).call(4, 1, 0, byref(default),
                   argtypes=(ctypes.c_int, ctypes.c_int, POINTER(c_void_p)))
    d_id, d_name = device_info(default) if default.value else (None, None)
    return out, (d_id, d_name)


def device_info(dev):
    store = c_void_p()
    Com(dev).call(4, 0, byref(store),
                  argtypes=(ctypes.c_int, POINTER(c_void_p)))
    pv = PROPVARIANT()
    Com(store).call(5, byref(PKEY_Device_FriendlyName), byref(pv),
                    argtypes=(c_void_p, c_void_p))
    name = ctypes.wstring_at(pv.pwszVal) if pv.pwszVal else "?"
    idp = c_wchar_p()
    Com(dev).call(5, byref(idp), argtypes=(POINTER(c_wchar_p),))
    return idp.value, name


def set_default(device_id):
    """IPolicyConfig::SetDefaultEndpoint (vtable[13]) 三个 role 全切."""
    pc = c_void_p()
    ole32.CoCreateInstance(byref(CLSID_PolicyConfigClient), None, 1,
                           byref(IID_IPolicyConfig), byref(pc))
    for role in (0, 1, 2):   # eConsole / eMultimedia / eCommunications
        hr = Com(pc).call(13, device_id, role,
                          argtypes=(c_wchar_p, ctypes.c_int))
        if hr != 0:
            raise OSError(f"SetDefaultEndpoint role={role} hr={hr & 0xffffffff:#x}")


def main():
    co_init()
    enum = get_enumerator()
    devs, default = list_capture_devices(enum)
    print("当前默认录制设备:", default)
    print("全部录制端点:")
    for i, (did, name) in enumerate(devs):
        print(f"  [{i}] {name}")
    if len(sys.argv) >= 2 and sys.argv[1] == "switch":
        hint = sys.argv[2].lower()
        for did, name in devs:
            if hint in name.lower():
                print("切换默认 ->", name)
                set_default(did)
                print("OK")
                return
        print("未找到匹配设备")
    elif len(sys.argv) >= 2 and sys.argv[1] == "restore":
        if len(sys.argv) >= 3:
            set_default(sys.argv[2])
            print("restored", sys.argv[2])


if __name__ == "__main__":
    main()
