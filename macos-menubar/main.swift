// lele-voice-menubar (§六十七) —— 乐乐语音桥菜单栏管理小程序 (原生 AppKit, 无三方依赖)
//
// 菜单栏图标: 🎙 有声音 / 🔗 直连待机 / ☁️ 中转待机 / ❗ 守护无响应
// 菜单: 状态总览 · 打开实时日志(Console) · 编辑配置(TextEdit) · 通知开关 · 重启守护
//
// 编译: swiftc -O main.swift -o lele-voice-menubar
// 托管: LaunchAgent cn.taoge.lele-voice-menubar (lele-voice-daemon install 会自动装)

import AppKit
import Darwin

let logPath = NSHomeDirectory() + "/Library/Logs/cn.taoge.lele-voice-daemon.log"
let configPath = NSHomeDirectory() + "/.config/lele-voice/config.toml"
let daemonLabel = "cn.taoge.lele-voice-daemon"

// ---- 状态 (轮询刷新) ----
var alive = false
var direct = false
var sound = false
var pktsText = "—"
var kbpsText = "—"
var rttText = "—"
var notifyOn = readNotifyFlag()
var lastLogSize: UInt64 = 0
var recentEvent = ""

func readNotifyFlag() -> Bool {
    guard let text = try? String(contentsOfFile: configPath, encoding: .utf8) else { return true }
    for line in text.split(separator: "\n") {
        let t = line.trimmingCharacters(in: .whitespaces)
        if t.hasPrefix("notify") { return t.contains("true") }
    }
    return true
}

func setNotifyFlag(_ on: Bool) {
    guard let text = try? String(contentsOfFile: configPath, encoding: .utf8) else {
        alert("找不到配置文件", configPath)
        return
    }
    var lines = text.components(separatedBy: "\n")
    var replaced = false
    for i in lines.indices {
        let t = lines[i].trimmingCharacters(in: .whitespaces)
        if t.hasPrefix("notify") {
            let indent = lines[i].prefix(while: { $0 == " " })
            lines[i] = indent + "notify = \(on ? "true" : "false")" +
                (t.contains("#") ? "   # 收到事件(语音触发/直连建立)时发 macOS 系统通知" : "")
            replaced = true
            break
        }
    }
    guard replaced else {
        alert("配置里没有 notify 字段", "请在 [ui] 段加一行 notify = true 后重试")
        return
    }
    do {
        try lines.joined(separator: "\n").write(toFile: configPath, atomically: true, encoding: .utf8)
        notifyOn = on
        alert("通知已\(on ? "开启" : "关闭")", "守护 30 秒内自动生效(无需重启)")
    } catch {
        alert("写入配置失败", "\(error)")
    }
}

func alert(_ title: String, _ body: String) {
    let a = NSAlert()
    a.messageText = title
    a.informativeText = body
    a.runModal()
}

// ---- 轮询: 最后一条统计行 + 捕捉新事件行 ----
func poll() {
    guard let attr = try? FileManager.default.attributesOfItem(atPath: logPath),
          let size = attr[.size] as? UInt64,
          let handle = FileHandle(forReadingAtPath: logPath) else {
        alive = false
        return
    }
    defer { try? handle.close() }

    if size > lastLogSize && lastLogSize > 0 && size - lastLogSize < 2 * 1024 * 1024 {
        try? handle.seek(toOffset: lastLogSize)
        let fresh = String(decoding: handle.readDataToEndOfFile(), as: UTF8.self)
        for line in fresh.split(separator: "\n") {
            if line.contains("🎙") || line.contains("打洞") || line.contains("[IME]") {
                recentEvent = String(line.suffix(110))
            }
        }
    }
    lastLogSize = size

    let from = size > 65536 ? size - 65536 : 0
    try? handle.seek(toOffset: from)
    let tail = String(decoding: handle.readDataToEndOfFile(), as: UTF8.self)
    alive = false
    for line in tail.split(separator: "\n").reversed() {
        if line.contains("] 收 ") && line.contains("包") {
            alive = true
            direct = line.contains("直连✓")
            sound = !line.contains("[静音!]")
            if let r = line.range(of: "收 (\\d+) 包", options: .regularExpression) {
                pktsText = line[r].replacingOccurrences(of: "[收 包]", with: "", options: .regularExpression)
            }
            if let r = line.range(of: "\\(\\d+kbps\\)", options: .regularExpression) {
                kbpsText = line[r].replacingOccurrences(of: "[()]", with: "", options: .regularExpression)
            }
            if let r = line.range(of: "RTT≈\\d+ms", options: .regularExpression) {
                rttText = line[r].replacingOccurrences(of: "RTT≈", with: "")
            } else {
                rttText = "—"
            }
            break
        }
    }
}

// ---- 动作 ----
final class Actions: NSObject {
    @objc func openLog() {
        guard FileManager.default.fileExists(atPath: logPath) else { alert("日志不存在", logPath); return }
        NSWorkspace.shared.open([URL(fileURLWithPath: logPath)], withApplicationAt: URL(fileURLWithPath: "/System/Applications/Utilities/Console.app"), configuration: NSWorkspace.OpenConfiguration())
    }
    @objc func editConfig() {
        guard FileManager.default.fileExists(atPath: configPath) else { alert("配置不存在", configPath); return }
        NSWorkspace.shared.open([URL(fileURLWithPath: configPath)], withApplicationAt: URL(fileURLWithPath: "/System/Applications/TextEdit.app"), configuration: NSWorkspace.OpenConfiguration())
    }
    @objc func toggleNotify() {
        setNotifyFlag(!notifyOn)
        refreshMenu()
    }
    @objc func restartDaemon() {
        let p = Process()
        p.launchPath = "/bin/sh"
        p.arguments = ["-c", "launchctl kickstart -k gui/\(getuid())/\(daemonLabel)"]
        try? p.run()
    }
    @objc func quitApp() { NSApp.terminate(nil) }
}
let actions = Actions()

// ---- 菜单栏 ----
let app = NSApplication.shared
app.setActivationPolicy(.accessory)

let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
item.button?.font = NSFont.menuBarFont(ofSize: 0)

let statusLine = NSMenuItem(title: "读取守护状态…", action: nil, keyEquivalent: "")
statusLine.isEnabled = false
let eventLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
eventLine.isEnabled = false
let toggleLine = NSMenuItem(title: "系统通知", action: #selector(Actions.toggleNotify), keyEquivalent: "")

let menu = NSMenu()
menu.autoenablesItems = false
menu.addItem(statusLine)
menu.addItem(eventLine)
menu.addItem(.separator())
menu.addItem(withTitle: "打开实时日志 (Console)", action: #selector(Actions.openLog), keyEquivalent: "").target = actions
menu.addItem(withTitle: "编辑配置 (TextEdit)", action: #selector(Actions.editConfig), keyEquivalent: "").target = actions
menu.addItem(toggleLine)
toggleLine.target = actions
menu.addItem(.separator())
menu.addItem(withTitle: "重启守护", action: #selector(Actions.restartDaemon), keyEquivalent: "").target = actions
menu.addItem(withTitle: "退出菜单栏", action: #selector(Actions.quitApp), keyEquivalent: "").target = actions
item.menu = menu

func refreshMenu() {
    poll()
    item.button?.title = !alive ? "❗" : (sound ? "🎙" : (direct ? "🔗" : "☁️"))
    item.button?.toolTip = "乐乐语音桥" + (!alive ? " (守护无响应)" : "")
    statusLine.title = alive
        ? "收 \(pktsText) 包 · \(kbpsText) · RTT \(rttText) · \(direct ? "直连" : "中转")"
        : "守护未运行 (菜单里点「重启守护」)"
    eventLine.title = recentEvent.isEmpty ? "" : "最近: \(recentEvent)"
    eventLine.isEnabled = false
    toggleLine.title = "系统通知: \(notifyOn ? "开 ✓" : "关")"
}

refreshMenu()
Timer.scheduledTimer(withTimeInterval: 4.0, repeats: true) { _ in refreshMenu() }
app.run()
