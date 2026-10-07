@echo off
REM ============================================================
REM  乐乐语音桥 Windows 接收器一键启动
REM  音频: 腾讯中转(124.221.187.167:9761) -> 本机 -> VB-Cable
REM  前提: 已装 Python 3.9+(勾选 Add to PATH) 和 VB-Cable
REM ============================================================
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [!] 未找到 python. 请先安装 Python 3.9+ 并勾选 "Add to PATH"
    echo     下载: https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

python -c "import sounddevice" >nul 2>nul
if errorlevel 1 (
    echo [*] 首次运行: 正在安装 sounddevice...
    python -m pip install sounddevice
    if errorlevel 1 (
        echo [!] pip 安装失败, 手动执行: python -m pip install sounddevice
        pause
        exit /b 1
    )
)

echo [*] 启动接收器: 订阅腾讯中转, 音频输出到 VB-Cable ^(CABLE Input^)
echo     让微信输入法的语音输入麦克风选择 "CABLE Input (VB-Audio Virtual Cable)"
echo     按 Ctrl-C 停止
echo.
python "%~dp0voice_receiver.py" --relay 124.221.187.167 --device "CABLE Input"
pause
