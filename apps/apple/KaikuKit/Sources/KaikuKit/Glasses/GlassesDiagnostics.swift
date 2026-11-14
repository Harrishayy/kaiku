import CoreGraphics
import Foundation
import ImageIO
import Observation
import UniformTypeIdentifiers

/// What the glasses path is doing, written down so a failure can be found without a debugger.
///
/// `GlassesLog` appends one JSON object per line to `Application Support/Kaiku/glasses-log.jsonl` (shareable from
/// You → Glasses check). It holds event names, states, route names, counts and error text only: never audio, never
/// an image, never a word anyone said.
public final class GlassesLog: @unchecked Sendable {
    public static let shared = GlassesLog()
    public static var url: URL { KaikuPaths.support.appendingPathComponent("glasses-log.jsonl") }
    static let maxBytes = 400_000

    private let lock = NSLock()
    private let file: URL
    private var tail: [String] = []
    private let stamp: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]; return f
    }()

    public init(url: URL = GlassesLog.url) { file = url }

    /// `fields`: strings, numbers and booleans only (anything else is written as its description).
    public func log(_ event: String, _ fields: [String: Any] = [:]) {
        var obj: [String: Any] = ["event": event]
        for (k, v) in fields {
            switch v {
            case let s as String: obj[k] = String(s.prefix(300))
            case let b as Bool: obj[k] = b
            case let n as Int: obj[k] = n
            case let d as Double: obj[k] = (d * 1000).rounded() / 1000
            default: obj[k] = String(String(describing: v).prefix(300))
            }
        }
        lock.lock(); defer { lock.unlock() }
        obj["ts"] = stamp.string(from: Date())
        guard let data = try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys]),
              let line = String(data: data, encoding: .utf8) else { return }
        tail.append(line)
        if tail.count > 200 { tail.removeFirst(tail.count - 200) }
        kaikuLog.notice("glasses \(line, privacy: .public)")
        let bytes = Data((line + "\n").utf8)
        if let h = try? FileHandle(forWritingTo: file) {
            defer { try? h.close() }
            if let end = try? h.seekToEnd(), end > UInt64(Self.maxBytes) {
                // keep the newer half
                try? h.close()
                if let all = try? String(contentsOf: file, encoding: .utf8) {
                    let lines = all.split(separator: "\n")
                    let kept = lines.suffix(lines.count / 2).joined(separator: "\n") + "\n" + line + "\n"
                    try? kept.write(to: file, atomically: true, encoding: .utf8)
                }
                return
            }
            try? h.write(contentsOf: bytes)
        } else {
            try? bytes.write(to: file, options: .atomic)
        }
    }

    /// The newest lines written by this process (newest last).
    public func recent(_ n: Int = 40) -> [String] {
        lock.lock(); defer { lock.unlock() }
        return Array(tail.suffix(n))
    }

    public func clear() {
        lock.lock(); defer { lock.unlock() }
        tail = []
        try? FileManager.default.removeItem(at: file)
    }
}

/// One camera frame on its way to the live conversation. Lives in memory only: never written, never queued.
public struct GlassesFrame: Sendable, Equatable {
    public let jpeg: Data
    /// Mean brightness 0…1 of the frame, computed on this device.
    public let luminance: Double
    public let width: Int
    public let height: Int
    public init(jpeg: Data, luminance: Double, width: Int, height: Int) {
        self.jpeg = jpeg; self.luminance = luminance; self.width = width; self.height = height
    }
}

public enum GlassesCameraState: String, Sendable, Equatable {
    case off, needsPermission, starting, streaming, paused, failed
}

/// Frame handling that never leaves the device: downscale, JPEG-encode for Gemini Live, mean brightness.
public enum GlassesVision {
    /// Longest side sent to Live. A 360 × 640 stream frame is sent as it is.
    public static let maxSide = 640
    public static let quality = 0.6
    /// Live takes at most one frame a second (Gemini Live docs, "Sending video").
    public static let minInterval: TimeInterval = 1.0

    public static func encode(_ image: CGImage, maxSide: Int = maxSide, quality: Double = quality) -> GlassesFrame? {
        let scale = min(1, Double(maxSide) / Double(max(image.width, image.height)))
        let w = max(1, Int(Double(image.width) * scale)), h = max(1, Int(Double(image.height) * scale))
        guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                                  space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return nil }
        ctx.interpolationQuality = .medium
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
        guard let scaled = ctx.makeImage() else { return nil }
        let out = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(out, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(dest, scaled, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { return nil }
        return GlassesFrame(jpeg: out as Data, luminance: luminance(scaled), width: w, height: h)
    }

    /// Mean luma (Rec. 601) of a 16 × 16 reduction. Camera auto-exposure flattens it, so this is a rough
    /// "bright view" hint for the self-test, not a light measurement.
    public static func luminance(_ image: CGImage) -> Double {
        let n = 16
        var px = [UInt8](repeating: 0, count: n * n * 4)
        let ok = px.withUnsafeMutableBytes { raw -> Bool in
            guard let ctx = CGContext(data: raw.baseAddress, width: n, height: n, bitsPerComponent: 8, bytesPerRow: n * 4,
                                      space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return false }
            ctx.draw(image, in: CGRect(x: 0, y: 0, width: n, height: n))
            return true
        }
        guard ok else { return 0 }
        var sum = 0.0
        for i in stride(from: 0, to: px.count, by: 4) {
            sum += 0.299 * Double(px[i]) + 0.587 * Double(px[i + 1]) + 0.114 * Double(px[i + 2])
        }
        return sum / Double(n * n) / 255
    }

    public static func image(_ jpeg: Data) -> CGImage? {
        guard let src = CGImageSourceCreateWithData(jpeg as CFData, nil) else { return nil }
        return CGImageSourceCreateImageAtIndex(src, 0, nil)
    }
}

/// What the Device Access Toolkit says about the glasses right now (filled by the iOS shell; plain words so the
/// check screen and the log can show them as they are).
public struct GlassesSnapshot: Sendable, Equatable {
    public var sdk = "not in this build"
    public var registration = "unknown"
    public var device: String?
    public var model: String?
    public var link = "no glasses found"
    public var worn = "unknown"
    public var hinge = "unknown"
    public var battery: Int?
    /// Camera permission in the Meta AI app: granted · denied · unknown (+ why).
    public var camera = "unknown"
    public init() {}
}

/// The iOS shell's handle on the DAT SDK for the check screen (the walk itself uses `GlassesAdapter`).
public protocol GlassesControl: Sendable {
    func snapshot() async -> GlassesSnapshot
    /// Opens the Meta AI app to ask for the camera. Returns the resulting status in plain words.
    func requestCamera() async -> String
    /// One frame for the self-test: starts a short device session + camera stream, takes the first frame, stops.
    func testFrame() async -> (frame: GlassesFrame?, note: String)
}

/// Live state of the glasses path, for the walk screen and the check screen. Nothing here is persisted.
@Observable @MainActor
public final class GlassesStatus {
    public static let shared = GlassesStatus()
    public var snapshot = GlassesSnapshot()
    public var route = TalkAudio.Route()
    public var live = "not started"
    public var lastPersonAt: Date?
    public var lastKaikuAt: Date?
    public var camera: GlassesCameraState = .off
    public var cameraNote: String?
    public private(set) var framesSent = 0
    public private(set) var lastError: String?
    public private(set) var lastErrorAt: Date?
    @ObservationIgnored private var frameTimes: [Date] = []

    public init() {}

    /// Frames sent per second over the last 10 s.
    public var framesPerSecond: Double {
        let recent = frameTimes.filter { Date().timeIntervalSince($0) <= 10 }
        return Double(recent.count) / 10
    }

    public func frameSent(at t: Date = Date()) {
        framesSent += 1
        frameTimes.append(t)
        if frameTimes.count > 30 { frameTimes.removeFirst(frameTimes.count - 30) }
    }

    public func resetFrames() { framesSent = 0; frameTimes = [] }

    public func error(_ text: String, where place: String) {
        lastError = text
        lastErrorAt = Date()
        GlassesLog.shared.log("error", ["where": place, "error": text])
    }

    public func clearError() { lastError = nil; lastErrorAt = nil }

    public func refresh(app: AppModel) async {
        route = TalkAudio.route
        if let c = app.glassesControl { snapshot = await c.snapshot() }
    }
}
