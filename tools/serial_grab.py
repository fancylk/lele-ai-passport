#!/usr/bin/env python3
"""抢占被 main.py stdin 吞键的 MicroPython 板子的 REPL.

原理: ESP32-C3 USB-Serial-JTAG 复位 (esptool 同款 RTS/DTR 时序) →
释放瞬间 REPL 有零点几秒窗口, 立刻 Ctrl-C 风暴打断 main.py → 拿到 REPL.

用法: python3 serial_grab.py /dev/cu.usbmodem101 [--cmd "print(1)"]
成功后进交互透传; --cmd 则执行单条并退出.
"""
import sys
import time
import argparse

import serial  # pyserial, mpremote 依赖自带


def usbjtag_reset(ser):
    # esptool USB_JTAG_SERIAL reset: RTS 断言复位, 再释放
    ser.setDTR(False)
    ser.setRTS(True)
    time.sleep(0.1)
    ser.setRTS(False)
    time.sleep(0.05)


def seize(port, quiet=False):
    ser = serial.Serial(port, 115200, timeout=0.1)
    ser.reset_input_buffer()
    usbjtag_reset(ser)
    # Ctrl-C 风暴抢窗口, 然后尝试 raw 模式
    deadline = time.time() + 4
    got = b""
    while time.time() < deadline:
        ser.write(b"\x03")
        time.sleep(0.02)
        got += ser.read(4096)
        if b">>>" in got or b">" in got.split(b"\r\n")[-1:]:
            break
    ser.write(b"\x03")  # 再补一发
    time.sleep(0.3)
    got += ser.read(4096)
    ser.reset_input_buffer()
    if not quiet:
        print("[grab] window output tail:", got[-120:])
    return ser


def run_cmd(ser, cmd, wait=6.0):
    ser.write(b"\x05")  # ctrl-E paste mode
    time.sleep(0.1)
    ser.write(b"\x10\x04")  # 不用 raw, 直接普通模式执行
    ser.reset_input_buffer()
    ser.write(cmd.encode() + b"\r\n")
    t0 = time.time()
    out = b""
    while time.time() - t0 < wait:
        out += ser.read(4096)
        time.sleep(0.05)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("--cmd", help="执行单条 python 后退出")
    args = ap.parse_args()

    ser = seize(args.port)
    probe = run_cmd(ser, "print('REPL-OK')")
    if b"REPL-OK" not in probe:
        print("[!] 未抢到 REPL, 输出:", probe[-200:])
        sys.exit(1)
    print("[+] 已抢到 REPL")
    if args.cmd:
        print(run_cmd(ser, args.cmd, wait=10).decode("utf-8", "replace"))
    else:
        # 交互透传
        import termios
        import select
        old = termios.tcgetattr(sys.stdin.fileno())
        import tty
        tty.setcbreak(sys.stdin.fileno())
        try:
            while True:
                r, _, _ = select.select([sys.stdin, ser], [], [], 0.05)
                if sys.stdin in r:
                    d = sys.stdin.read(1)
                    if d == "\x1d":  # Ctrl-] 退出
                        break
                    ser.write(d.encode())
                if ser in r:
                    sys.stdout.write(ser.read(4096).decode("utf-8", "replace"))
                    sys.stdout.flush()
        finally:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old)
            ser.close()


if __name__ == "__main__":
    main()
