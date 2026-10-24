// lele-voice-menubar (§六十七) —— 乐乐语音桥菜单栏管理小程序 (原生 AppKit, 无三方依赖)
//
// 菜单栏图标: 🎙 有声音 / 🔗 直连待机 / ☁️ 中转待机 / ⚠️ 未正确配置 / ❗ 守护无响应
// 菜单: 状态总览 · 配置与环境指引 · 打开实时日志(Console) · 编辑配置(TextEdit) · 通知开关 · 重启守护
//
// 编译: swiftc -O main.swift -o lele-voice-menubar
// 托管: LaunchAgent cn.taoge.lele-voice-menubar (lele-voice-daemon install 会自动装)

import AppKit
import Darwin

let logPath = NSHomeDirectory() + "/Library/Logs/cn.taoge.lele-voice-daemon.log"
let configPath = NSHomeDirectory() + "/.config/lele-voice/config.toml"
let daemonLabel = "cn.taoge.lele-voice-daemon"
let daemonAppPath = NSHomeDirectory() + "/Applications/lele-voice-daemon.app"
let daemonBinPath = daemonAppPath + "/Contents/MacOS/lele-voice-daemon"

func logMsg(_ msg: String) {
    let df = DateFormatter()
    df.dateFormat = "yyyy-MM-dd HH:mm:ss"
    let line = "[\(df.string(from: Date()))] \(msg)\n"
    fputs(line, stderr)
    fflush(stderr)
}

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
var pollCounter = 0

// ---- 环境与配置健康检查 ----
struct HealthReport {
    var isConfiguredProperly: Bool = true
    var axGranted: Bool = true
    var audioReady: Bool = true
    var configExists: Bool = true
    var imeReady: Bool = true
    var relayOk: Bool = true
    var daemonRunning: Bool = true
    var issues: [String] = []
    var rawDoctor: String = ""
}
var health = HealthReport()

// ---- 目标主机 (§六十八): 经 relay TSET/TGTQ 查询与切换 ----
var relayTarget: String? = nil      // 当前目标 tag (nil=未设)
var targetTick = 0
var roster: [(tag: String, host: String, os: String)] = []   // §七十 在线花名册
var targetMenuItems: [NSMenuItem] = []

func configValue(_ key: String) -> String? {
    guard let text = try? String(contentsOfFile: configPath, encoding: .utf8) else { return nil }
    for line in text.split(separator: "\n") {
        let t = line.trimmingCharacters(in: .whitespaces)
        if t.hasPrefix(key + " ") || t.hasPrefix(key + "=") {
            let v = t.drop(while: { $0 != "=" }).dropFirst().trimmingCharacters(in: .whitespaces)
            return v.trimmingCharacters(in: CharacterSet(charactersIn: "\""))
        }
    }
    return nil
}

func relayRpc(_ payload: String, timeout: Double = 1.2) -> String? {
    let host = configValue("host") ?? "124.221.187.167"
    let token = configValue("token") ?? "lele-6deb6d37"
    let msg = payload.replacingOccurrences(of: "$TOKEN", with: token)
    let fd = socket(AF_INET, SOCK_DGRAM, 0)
    guard fd >= 0 else { return nil }
    defer { close(fd) }
    var addr = sockaddr_in()
    memset(&addr, 0, MemoryLayout<sockaddr_in>.size)
    addr.sin_family = sa_family_t(AF_INET)
    addr.sin_port = UInt16(9761).bigEndian
    addr.sin_addr = in_addr(s_addr: inet_addr(host.cString(using: .utf8)!))
    var tv = timeval(tv_sec: Int(timeout), tv_usec: 0)
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))
    let sent = msg.withCString { cs in
        withUnsafePointer(to: &addr) { ap in
            sendto(fd, cs, msg.utf8.count, 0, UnsafeRawPointer(ap).assumingMemoryBound(to: sockaddr.self), socklen_t(MemoryLayout<sockaddr_in>.size))
        }
    }
    guard sent == msg.utf8.count else { return nil }
    var buf = [UInt8](repeating: 0, count: 2048)
    let n = recv(fd, &buf, buf.count, 0)
    guard n > 0 else { return nil }
    return String(decoding: buf[0..<n], as: UTF8.self)
}

func queryRosterAsync() {
    DispatchQueue.global().async {
        let resp = relayRpc("RQST$TOKEN", timeout: 2.0)
        var t: String? = nil
        var list: [(String, String, String)] = []
        if let r = resp, r.hasPrefix("RST "), let data = r.dropFirst(4).data(using: .utf8),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            t = obj["target"] as? String
            if let hosts = obj["hosts"] as? [String: [String: Any]] {
                list = hosts.map { (tag, info) in
                    (tag, info["host"] as? String ?? tag, info["os"] as? String ?? "?")
                }.sorted { $0.1 < $1.1 }
            }
        }
        DispatchQueue.main.async {
            relayTarget = t
            roster = list.map { (tag: $0.0, host: $0.1, os: $0.2) }
            rebuildTargetMenu()
        }
    }
}

func setTargetAsync(_ t: String) {
    DispatchQueue.global().async {
        let resp = relayRpc("TSET$TOKEN@\(t)")
        DispatchQueue.main.async {
            if resp?.hasPrefix("TSET_OK") == true {
                relayTarget = t
            } else {
                alert("切换失败", "中转无响应 (relayRpc) —— 稍后重试")
            }
            refreshMenu()
        }
    }
}

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
    if !replaced {
        lines.append("")
        lines.append("[ui]")
        lines.append("notify = \(on ? "true" : "false")")
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

func runDoctorCheck() -> HealthReport {
    var rep = HealthReport()
    let bin = FileManager.default.isExecutableFile(atPath: daemonBinPath) ? daemonBinPath : NSHomeDirectory() + "/.local/bin/lele-voice-daemon"
    guard FileManager.default.isExecutableFile(atPath: bin) else {
        rep.isConfiguredProperly = false
        rep.daemonRunning = false
        rep.issues.append("守护程序未安装在 \(daemonAppPath)")
        return rep
    }
    let p = Process()
    p.launchPath = bin
    p.arguments = ["doctor"]
    var env = ProcessInfo.processInfo.environment
    env["HOME"] = NSHomeDirectory()
    env["__CFBundleIdentifier"] = daemonLabel
    p.environment = env
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = pipe
    do {
        try p.run()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        let out = String(decoding: data, as: UTF8.self)
        rep.rawDoctor = out

        if out.contains("辅助功能授权: ✗") {
            rep.axGranted = false
            rep.issues.append("辅助功能授权未授予 (微信输入法快捷键必失效)")
        }
        if out.contains("✗ 未找到") {
            rep.audioReady = false
            rep.issues.append("未找到虚拟麦克风 BlackHole 2ch")
        }
        if out.contains("查询输出设备超时") {
            rep.audioReady = false
            rep.issues.append("音频服务无响应 (可在终端执行 sudo killall coreaudiod 恢复)")
        }
        if out.contains("配置:") && out.contains("不存在") {
            rep.configExists = false
            rep.issues.append("配置文件不存在")
        }
        if out.contains("目标 com.tencent.inputmethod.wetype.pinyin → 未找到") {
            rep.imeReady = false
            rep.issues.append("未检测到微信输入法")
        }
        if out.contains("plist 存在但未加载") || (!out.contains("state = running") && !alive) {
            rep.daemonRunning = false
            rep.issues.append("守护进程未运行")
        }
        if out.contains("中转 STATUS: 无响应") {
            rep.relayOk = false
            rep.issues.append("中转服务器无响应 (124.221.187.167)")
        }
        rep.isConfiguredProperly = rep.issues.isEmpty
        logMsg("runDoctorCheck done: configured=\(rep.isConfiguredProperly), issues=\(rep.issues)\n--- DOCTOR RAW ---\n\(out)\n--- END DOCTOR RAW ---")
    } catch {
        rep.isConfiguredProperly = false
        rep.issues.append("无法执行 doctor 诊断: \(error.localizedDescription)")
        logMsg("runDoctorCheck error: \(error)")
    }
    return rep
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
    @objc func showConfigGuide() {
        health = runDoctorCheck()
        let a = NSAlert()
        a.messageText = health.isConfiguredProperly ? "乐乐语音桥 — 配置与运行环境正常" : "⚠️ 乐乐语音桥 — 检测到未正确配置"
        a.alertStyle = health.isConfiguredProperly ? .informational : .warning

        var body = ""
        if !health.isConfiguredProperly {
            body += "【未就绪项】\n"
            for (i, iss) in health.issues.enumerated() {
                body += "  \(i + 1). ❌ \(iss)\n"
            }
            body += "\n"
        } else {
            body += "✅ 所有必要环境项（辅助功能、BlackHole、输入法、配置文件）均已正确配置就绪！\n\n"
        }

        body += "【配置指引与步骤】\n"
        body += "1. 辅助功能授权 (要害, 必须)：\n"
        body += "   系统设置 → 隐私与安全性 → 辅助功能 → 添加并勾选：\n"
        body += "   lele-voice-daemon.app (位于 ~/Applications)\n"
        body += "   * 未授权时系统静默拦截按键，微信输入法语音面板无法唤起。\n"
        body += "   * 点击下方「打开系统设置」将直接跳转并定位该 App。\n\n"
        body += "2. 微信输入法设置 (必须)：\n"
        body += "   打开微信输入法设置 → 语音输入：\n"
        body += "   • 麦克风选择「自动」(跟随系统默认，由守护进程在输入时自动动态热切换)\n"
        body += "   • 快捷键保持默认 (Fn 按住说话 / Fn+空格 长输入)\n\n"
        body += "3. 中转与打洞配置 (可选)：\n"
        body += "   配置文件路径: ~/.config/lele-voice/config.toml\n"
        body += "   可修改公网中转 IP、端口、Token、打洞与通知设置。\n"

        a.informativeText = body
        a.addButton(withTitle: "打开系统设置 (辅助功能)")
        a.addButton(withTitle: "编辑配置文件 (TextEdit)")
        a.addButton(withTitle: "定位守护应用 (访达)")
        a.addButton(withTitle: "重新检测并重启守护")
        a.addButton(withTitle: "关闭")

        let resp = a.runModal()
        switch resp {
        case .alertFirstButtonReturn:
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
                NSWorkspace.shared.open(url)
            }
            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: daemonAppPath)])
        case .alertSecondButtonReturn:
            editConfig()
        case .alertThirdButtonReturn:
            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: daemonAppPath)])
        case NSApplication.ModalResponse(rawValue: 1003): // 第4个按钮
            restartDaemon()
            Timer.scheduledTimer(withTimeInterval: 1.0, repeats: false) { _ in
                health = runDoctorCheck()
                refreshMenu()
            }
        default:
            break
        }
    }

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

    @objc func targetItemClicked(_ sender: NSMenuItem) {
        guard let tag = sender.representedObject as? String else { return }
        setTargetAsync(tag)
    }
    @objc func refreshRosterClicked() { queryRosterAsync() }
    @objc func quitApp() { NSApp.terminate(nil) }
}
let actions = Actions()

// ---- 菜单栏 ----
let app = NSApplication.shared
app.setActivationPolicy(.accessory)

let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
item.button?.font = NSFont.menuBarFont(ofSize: 0)

let warningLine = NSMenuItem(title: "⚠️ 未正确配置环境 (点击查看配置指引)", action: #selector(Actions.showConfigGuide), keyEquivalent: "")
warningLine.target = actions
warningLine.isHidden = true

let statusLine = NSMenuItem(title: "读取守护状态…", action: nil, keyEquivalent: "")
statusLine.isEnabled = false
let eventLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
eventLine.isEnabled = false
let targetLine = NSMenuItem(title: "语音目标: 查询中…", action: nil, keyEquivalent: "")
targetLine.isEnabled = false
let rosterHeaderLine = NSMenuItem(title: "在线主机 (点选切换):", action: nil, keyEquivalent: "")
rosterHeaderLine.isEnabled = false
let rosterRefreshItem = NSMenuItem(title: "↻ 刷新主机列表", action: #selector(Actions.refreshRosterClicked), keyEquivalent: "")
let toggleLine = NSMenuItem(title: "系统通知", action: #selector(Actions.toggleNotify), keyEquivalent: "")

let menu = NSMenu()
menu.autoenablesItems = false
menu.addItem(warningLine)
menu.addItem(statusLine)
menu.addItem(eventLine)
menu.addItem(targetLine)
menu.addItem(rosterHeaderLine)
rosterRefreshItem.target = actions
menu.addItem(rosterRefreshItem)
// 动态主机项插在刷新项之后 (rebuildTargetMenu 管理)
menu.addItem(.separator())
menu.addItem(withTitle: "🛠 打开配置并指导配置…", action: #selector(Actions.showConfigGuide), keyEquivalent: "").target = actions
menu.addItem(withTitle: "打开实时日志 (Console)", action: #selector(Actions.openLog), keyEquivalent: "").target = actions
menu.addItem(withTitle: "编辑配置 (TextEdit)", action: #selector(Actions.editConfig), keyEquivalent: "").target = actions
menu.addItem(toggleLine)
toggleLine.target = actions
menu.addItem(.separator())
menu.addItem(withTitle: "重启守护", action: #selector(Actions.restartDaemon), keyEquivalent: "").target = actions
menu.addItem(withTitle: "退出菜单栏", action: #selector(Actions.quitApp), keyEquivalent: "").target = actions
item.menu = menu

func updateWarningUI() {
    if !alive {
        warningLine.isHidden = false
        warningLine.title = "❗ 守护未运行 (菜单里点「重启守护」)"
        item.button?.title = "❗"
        item.button?.toolTip = "乐乐语音桥 (守护未运行)"
    } else {
        item.button?.title = sound ? "🎙" : (direct ? "🔗" : "☁️")
        item.button?.toolTip = "乐乐语音桥 (" + (direct ? "UDP直连✓" : "中转待机☁️") + ")"
        if !health.isConfiguredProperly && !health.issues.isEmpty {
            warningLine.isHidden = false
            warningLine.title = "⚠️ 环境提示: " + (health.issues.first ?? "点击查看指引")
        } else {
            warningLine.isHidden = true
        }
    }
    logMsg("updateWarningUI: alive=\(alive), properly=\(health.isConfiguredProperly), icon='\(item.button?.title ?? "")', issues=\(health.issues)")
}

func refreshMenu() {
    poll()
    updateWarningUI()
    statusLine.title = alive
        ? "收 \(pktsText) 包 · \(kbpsText) · RTT \(rttText) · \(direct ? "直连" : "中转")"
        : "守护未运行 (菜单里点「重启守护」)"
    eventLine.title = recentEvent.isEmpty ? "" : "最近: \(recentEvent)"
    eventLine.isEnabled = false
    toggleLine.title = "系统通知: \(notifyOn ? "开 ✓" : "关")"
    targetTick += 1
}
func targetLabel(_ t: String?) -> String {
    if let t = t, let hit = roster.first(where: { $0.tag == t }) {
        return hit.host + " (" + (hit.os == "macos" ? "Mac" : hit.os) + ")"
    }
    return t ?? "未设置"
}
/// §七十: 动态重建主机菜单项 (roster 变化/刷新时调用)
func rebuildTargetMenu() {
    for item in targetMenuItems {
        menu.removeItem(item)
    }
    targetMenuItems.removeAll()
    if roster.isEmpty {
        let m = NSMenuItem(title: "   (无在线主机)", action: nil, keyEquivalent: "")
        m.isEnabled = false
        menu.insertItem(m, at: rosterIndexBase())
        targetMenuItems.append(m)
    } else {
        for host in roster {
            let label = "   " + host.host + " · " + (host.os == "macos" ? "Mac" : host.os.capitalized)
            let m = NSMenuItem(title: label, action: #selector(Actions.targetItemClicked), keyEquivalent: "")
            m.target = actions
            m.representedObject = host.tag
            m.state = (host.tag == relayTarget) ? .on : .off
            menu.insertItem(m, at: rosterIndexBase() + targetMenuItems.count)
            targetMenuItems.append(m)
        }
    }
    targetLine.title = "语音目标: " + targetLabel(relayTarget)
}
/// 动态项插入基点 = 刷新项的 index + 1
func rosterIndexBase() -> Int {
    let idx = menu.index(of: rosterRefreshItem)
    return (idx >= 0 ? idx : menu.numberOfItems - 1) + 1
}
func targetPollTick() {
    // 每 3 个 tick(~12s)后台拉一次花名册+目标; 失败保留旧值
    if targetTick % 3 == 0 { queryRosterAsync() }
}

// 首次启动
poll()
refreshMenu()
Timer.scheduledTimer(withTimeInterval: 4.0, repeats: true) { _ in refreshMenu(); targetPollTick() }
queryRosterAsync()
app.run()
