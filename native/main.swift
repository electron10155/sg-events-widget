// SG Events Pet — a desktop-level widget showing Singapore free events
// Borderless transparent window sitting above wallpaper, below normal app windows.
// Built-in mini HTTP server serves the widget files. No external dependencies.

import Cocoa
import WebKit

// MARK: - Debug log

func dbgLog(_ msg: String) {
    let path = "/tmp/sgpet-debug.log"
    let stamp = DateFormatter.localizedString(from: Date(), dateStyle: .short, timeStyle: .medium)
    let line = "\(stamp): \(msg)\n"
    let existing = (try? String(contentsOfFile: path, encoding: .utf8)) ?? ""
    try? (existing + line).write(toFile: path, atomically: true, encoding: .utf8)
}

// MARK: - Mini HTTP File Server (BSD sockets, loopback only)

final class HTTPFileServer {
    private var listenFD: Int32 = -1
    let port: UInt16
    private let rootDir: URL

    init?(rootDir: URL, preferredPort: UInt16) {
        self.rootDir = rootDir
        var p = preferredPort
        var fd: Int32 = -1
        for _ in 0..<10 {
            let s = socket(AF_INET, SOCK_STREAM, 0)
            if s < 0 {
                dbgLog("server: socket() failed errno=\(errno)")
                continue
            }
            var yes: Int32 = 1
            setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &yes, socklen_t(MemoryLayout<Int32>.size))

            func tryBind(_ addrVal: in_addr_t) -> Int32 {
                var addr = sockaddr_in()
                addr.sin_family = sa_family_t(AF_INET)
                addr.sin_port = p.bigEndian
                addr.sin_addr = in_addr(s_addr: addrVal)
                return withUnsafePointer(to: &addr) {
                    $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                        bind(s, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                    }
                }
            }

            // Prefer loopback; fall back to ANY (this machine rejects 127.0.0.1 binds).
            // Peer-IP check in acceptLoop keeps access local-only.
            var bound = tryBind(INADDR_LOOPBACK)
            var usedAny = false
            if bound != 0 {
                bound = tryBind(INADDR_ANY)
                usedAny = true
            }
            if bound == 0 && listen(s, 8) == 0 {
                fd = s
                dbgLog("server: listening on port \(p) (\(usedAny ? "0.0.0.0 + local-only check" : "127.0.0.1"))")
                break
            }
            dbgLog("server: port \(p) bind=\(bound) errno=\(errno) \(String(cString: strerror(errno)))")
            close(s)
            p += 1
        }
        guard fd >= 0 else {
            dbgLog("server: FAILED to bind any port")
            return nil
        }
        self.listenFD = fd
        self.port = p
    }

    func start() {
        Thread.detachNewThread { [weak self] in
            self?.acceptLoop()
        }
    }

    private func acceptLoop() {
        while true {
            var clientAddr = sockaddr_in()
            var len = socklen_t(MemoryLayout<sockaddr_in>.size)
            let clientFD = withUnsafeMutablePointer(to: &clientAddr) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    accept(listenFD, $0, &len)
                }
            }
            if clientFD < 0 { continue }
            // Local-only: reject non-loopback peers (relevant when bound to 0.0.0.0)
            let peerIP = clientAddr.sin_addr.s_addr.bigEndian
            let isLoopback = (peerIP & 0xFF000000) == 0x7F000000
            if !isLoopback {
                close(clientFD)
                continue
            }
            Thread.detachNewThread { [weak self] in
                self?.handle(clientFD: clientFD)
            }
        }
    }

    private func handle(clientFD: Int32) {
        defer { close(clientFD) }

        // Read request headers
        var buffer = [UInt8]()
        let delimiter = Array("\r\n\r\n".utf8)
        var chunk = [UInt8](repeating: 0, count: 65536)
        var tv = timeval(tv_sec: 5, tv_usec: 0)
        setsockopt(clientFD, SOL_SOCKET, SO_RCVTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))
        func containsSubsequence(_ seq: [UInt8], _ sub: [UInt8]) -> Bool {
            guard !sub.isEmpty, seq.count >= sub.count else { return false }
            for i in 0...seq.count - sub.count {
                if seq[i..<i+sub.count].elementsEqual(sub) { return true }
            }
            return false
        }
        while true {
            let n = recv(clientFD, &chunk, 65536, 0)
            if n <= 0 { return }
            buffer.append(contentsOf: chunk[0..<n])
            if buffer.count > 1_000_000 { return }
            if containsSubsequence(buffer, delimiter) { break }
        }

        guard let reqText = String(bytes: buffer, encoding: .utf8),
              let firstLine = reqText.split(separator: "\r\n").first else { return }
        let parts = firstLine.split(separator: " ")
        guard parts.count >= 2 else { return }

        var path = String(parts[1])
        if path.hasPrefix("/") { path = String(path.dropFirst()) }
        if path.isEmpty { path = "index.html" }
        let queryless = String(path.split(separator: "?")[0])

        let rootPath = rootDir.standardizedFileURL.path
        let fileURL = rootDir.appendingPathComponent(queryless).standardizedFileURL
        guard fileURL.path.hasPrefix(rootPath),
              let data = FileManager.default.contents(atPath: fileURL.path) else {
            let resp = "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            resp.withCString { ptr in
                _ = send(clientFD, UnsafeRawPointer(ptr), strlen(ptr), 0)
            }
            return
        }

        let ext = fileURL.pathExtension.lowercased()
        let mime: String
        switch ext {
        case "html", "htm": mime = "text/html; charset=utf-8"
        case "json": mime = "application/json; charset=utf-8"
        case "js": mime = "text/javascript; charset=utf-8"
        case "css": mime = "text/css; charset=utf-8"
        case "png": mime = "image/png"
        case "jpg", "jpeg": mime = "image/jpeg"
        case "svg": mime = "image/svg+xml"
        default: mime = "application/octet-stream"
        }

        var out = Data("HTTP/1.1 200 OK\r\nContent-Type: \(mime)\r\nContent-Length: \(data.count)\r\nConnection: close\r\nCache-Control: no-cache\r\n\r\n".utf8)
        out.append(data)
        out.withUnsafeBytes { ptr in
            var sent = 0
            while sent < out.count {
                let n = send(clientFD, ptr.baseAddress!.advanced(by: sent), out.count - sent, 0)
                if n <= 0 { break }
                sent += n
            }
        }
    }
}

// MARK: - Drag-enable WebView (drag anywhere on the widget)

final class PetWebView: WKWebView {
    override var mouseDownCanMoveWindow: Bool { true }
}

// MARK: - Desktop Panel (non-activating, transparent)

final class DesktopPanel: NSPanel {
    override var canBecomeKey: Bool { true }
}

// MARK: - App Delegate

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, NSWindowDelegate, WKScriptMessageHandler {
    var panel: DesktopPanel!
    var webView: PetWebView!
    var server: HTTPFileServer!
    var baseURL: URL!
    var reloadTimer: Timer?
    var closeButton: NSButton!

    // Compact = ~1/3 the area of Full. Mini widget by default.
    static let compactSize = NSSize(width: 420, height: 170)
    static let fullSize = NSSize(width: 480, height: 600)
    var isExpanded = false

    let transparentCSS = """
    document.documentElement.style.background = 'transparent';
    document.body.style.background = 'transparent';
    document.body.style.padding = '0';
    document.body.style.margin = '0';
    document.body.style.width = '100%';
    document.body.style.height = '100%';
    document.body.style.alignItems = 'stretch';
    document.body.style.justifyContent = 'stretch';
    var card = document.querySelector('.pet');
    if (card) {
      card.style.width = '100%';
      card.style.height = '100%';
      card.style.boxShadow = '0 14px 40px rgba(0,0,0,0.45), 0 0 0 1px rgba(255,255,255,0.08)';
    }
    """

    func applicationDidFinishLaunching(_ notification: Notification) {
        // 1. Locate widget files: project dir first, bundle fallback
        let projectDir = URL(fileURLWithPath: "/Users/wanziyan/WorkBuddy/2026-08-20-19-16-05/sg-events-widget")
        let bundleDir = Bundle.main.resourceURL?.appendingPathComponent("widget")
        let dir: URL
        if FileManager.default.fileExists(atPath: projectDir.appendingPathComponent("index.html").path) {
            dir = projectDir
        } else if let bd = bundleDir,
                  FileManager.default.fileExists(atPath: bd.appendingPathComponent("index.html").path) {
            dir = bd
        } else {
            dir = projectDir
        }

        // 2. Start embedded HTTP server
        dbgLog("app: launching, widget dir = \(dir.path)")
        server = HTTPFileServer(rootDir: dir, preferredPort: 8765)
        server?.start()
        let port = server?.port ?? 8765
        baseURL = URL(string: "http://127.0.0.1:\(port)/")!
        dbgLog("app: baseURL = \(baseURL.absoluteString)")

        // 3. Create desktop-level panel (always starts in compact mini mode)
        let rect = NSRect(origin: savedOrigin() ?? defaultOrigin(), size: Self.compactSize)
        panel = DesktopPanel(contentRect: rect,
                             styleMask: [.borderless, .nonactivatingPanel],
                             backing: .buffered, defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.hidesOnDeactivate = false
        panel.level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.desktopIconWindow)) + 1)
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
        panel.isMovableByWindowBackground = true
        panel.delegate = self

        // Square corners for the widget window (no rounding, no white edge artifacts).
        panel.contentView?.wantsLayer = true
        panel.contentView?.layer?.cornerRadius = 0
        panel.contentView?.layer?.masksToBounds = false
        panel.contentView?.layer?.backgroundColor = NSColor.clear.cgColor

        // 4. WebView
        let config = WKWebViewConfiguration()
        let ucc = WKUserContentController()
        ucc.addUserScript(WKUserScript(source: transparentCSS,
                                        injectionTime: .atDocumentEnd,
                                        forMainFrameOnly: true))
        ucc.add(self, name: "widget")
        config.userContentController = ucc

        webView = PetWebView(frame: NSRect(origin: .zero, size: Self.compactSize),
                             configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        if #available(macOS 12.0, *) {
            webView.underPageBackgroundColor = .clear
        }
        if webView.responds(to: NSSelectorFromString("setDrawsBackground:")) {
            webView.setValue(false, forKey: "drawsBackground")
        }
        webView.load(URLRequest(url: baseURL, cachePolicy: .reloadIgnoringLocalCacheData))
        panel.contentView = webView
        panel.orderFrontRegardless()
        dbgLog("app: panel frame after create = \(panel.frame)")

        // 5. Subtle close button (top-right corner, in transparent margin)
        closeButton = NSButton(frame: NSRect(x: 0, y: 0, width: 18, height: 18))
        closeButton.isBordered = false
        closeButton.attributedTitle = NSAttributedString(
            string: "✕",
            attributes: [
                .font: NSFont.systemFont(ofSize: 13, weight: .medium),
                .foregroundColor: NSColor.white.withAlphaComponent(0.65),
            ])
        closeButton.alphaValue = 0.35
        closeButton.toolTip = "退出小组件 (或按 ⌘Q)"
        closeButton.target = NSApplication.shared
        closeButton.action = #selector(NSApplication.terminate(_:))
        panel.contentView?.addSubview(closeButton)
        positionCloseButton()

        // 6. Cmd+Q quits
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if event.modifierFlags.contains(.command),
               event.charactersIgnoringModifiers?.lowercased() == "q" {
                NSApp.terminate(nil)
            }
            return event
        }

        // 7. Periodic reload (picks up daily-updated events.json)
        reloadTimer = Timer.scheduledTimer(withTimeInterval: 6 * 3600, repeats: true) { [weak self] _ in
            self?.webView.reload()
        }

        // 8. Sanity check: log the frame again shortly after launch
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { [weak self] in
            guard let self = self else { return }
            dbgLog("app: panel frame after 2s = \(self.panel.frame)")
        }
    }

    private func defaultOrigin() -> NSPoint {
        guard let visible = NSScreen.main?.visibleFrame else {
            return NSPoint(x: 100, y: 100)
        }
        return NSPoint(x: visible.maxX - Self.compactSize.width - 48,
                       y: visible.minY + 64)
    }

    private func savedOrigin() -> NSPoint? {
        if let s = UserDefaults.standard.string(forKey: "PetOrigin") {
            let parts = s.split(separator: ",").compactMap { Double($0) }
            if parts.count == 2 { return NSPoint(x: parts[0], y: parts[1]) }
        }
        // Backward compatibility with old "PetFrame" (x,y,w,h) key
        if let s = UserDefaults.standard.string(forKey: "PetFrame") {
            let parts = s.split(separator: ",").compactMap { Double($0) }
            if parts.count == 4 { return NSPoint(x: parts[0], y: parts[1]) }
        }
        return nil
    }

    func windowDidMove(_ notification: Notification) {
        guard let f = panel.frame as NSRect? else { return }
        UserDefaults.standard.set("\(f.origin.x),\(f.origin.y)", forKey: "PetOrigin")
    }

    private func positionCloseButton() {
        let size = panel.frame.size
        closeButton.frame = NSRect(x: size.width - 26, y: size.height - 26, width: 18, height: 18)
    }

    /// Resize between compact mini widget and full page, with animation.
    /// Keeps the widget anchored by its top edge center, clamped to the screen.
    func setExpanded(_ expanded: Bool) {
        guard expanded != isExpanded else { return }
        isExpanded = expanded
        let target = expanded ? Self.fullSize : Self.compactSize
        var f = panel.frame
        let centerX = f.midX
        let topY = f.maxY
        f.size = target
        f.origin.x = centerX - target.width / 2
        f.origin.y = topY - target.height
        // Clamp to visible screen area
        if let vis = NSScreen.main?.visibleFrame {
            f.origin.x = min(max(f.origin.x, vis.minX + 8), vis.maxX - target.width - 8)
            f.origin.y = min(max(f.origin.y, vis.minY + 8), vis.maxY - target.height - 8)
        }
        panel.setFrame(f, display: true, animate: true)
        positionCloseButton()
    }

    // MARK: WKScriptMessageHandler — expand / collapse from the web page

    func userContentController(_ userContentController: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard let dict = message.body as? [String: Any],
              let action = dict["action"] as? String else { return }
        DispatchQueue.main.async { [weak self] in
            switch action {
            case "expand": self?.setExpanded(true)
            case "collapse": self?.setExpanded(false)
            default: break
            }
        }
    }

    // MARK: WKNavigationDelegate — external links open in browser, keep widget on localhost

    func webView(_ webView: WKWebView,
                 decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        if url.host == "127.0.0.1" || url.host == "localhost" {
            decisionHandler(.allow)
        } else {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        // Server might not be ready yet — retry shortly
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
            self?.webView.reload()
        }
    }
}

// MARK: - main

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
