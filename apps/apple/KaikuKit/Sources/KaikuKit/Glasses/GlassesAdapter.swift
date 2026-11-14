import CoreGraphics
import Foundation
import simd

/// Meta glasses on a walk (plan 05 §6). One protocol, two adapters: `DATGlasses` (the Meta Wearables Device
/// Access Toolkit, in the iOS target because the SDK is iOS-only) and `MockGlasses` (synthetic IMU, here). The walk
/// only ever sees `GlassesEvent`s, so a disconnect mid-walk is just a state event and the walk goes on on the phone.
public enum GlassesState: String, Equatable, Sendable {
    case off            // not set up / not started
    case searching
    case registrationRequired
    case motionUnavailable
    case connected
    case batteryLow
    case disconnected   // was connected during this walk, now gone
}

/// One IMU reading: seconds on the device's monotonic clock, acceleration in m/s² including gravity.
public struct IMUSample: Sendable, Equatable {
    public var t: Double
    public var accel: SIMD3<Float>
    public init(t: Double, accel: SIMD3<Float>) { self.t = t; self.accel = accel }
}

public enum GlassesEvent: Sendable {
    case state(GlassesState)
    case imu([IMUSample])
    /// Mean brightness 0…1 of one sparse camera frame (the frame itself is discarded on the device).
    case brightness(Double)
    case tap
    /// One camera frame (only while the camera is on). In memory only; the walk passes it to Live or drops it.
    case frame(GlassesFrame)
    case camera(GlassesCameraState, note: String?)
    /// The glasses went on (true) or came off (false) the person's face.
    case worn(Bool)
    /// Something failed; plain words for the check screen and the log.
    case problem(String)
}

public protocol GlassesAdapter: AnyObject, Sendable {
    /// Shown nowhere on screen (logs only).
    var kind: String { get }
    func start(_ events: @escaping @Sendable (GlassesEvent) -> Void) async
    func stop() async
    /// Turns the camera stream on or off. Called only with the person's "Let Kaiku see" choice on.
    func setCamera(_ on: Bool) async
}

public extension GlassesAdapter {
    func setCamera(_ on: Bool) async {}
}

/// Synthetic glasses: a person walking at ~108 steps/min, looking ahead most of the time with short look-downs,
/// with sparse "daylight" readings. `dropAfter` simulates the glasses disconnecting mid-walk (§7 edge case).
public final class MockGlasses: GlassesAdapter, @unchecked Sendable {
    public let kind = "mock"
    private var task: Task<Void, Never>?
    private let dropAfter: TimeInterval?
    private let cadence: Double
    private let cameraLock = NSLock()
    private var cameraOn = false
    private var events: (@Sendable (GlassesEvent) -> Void)?

    public func setCamera(_ on: Bool) async {
        swapCamera(on)?(.camera(on ? .streaming : .off, note: nil))
    }

    private func swapCamera(_ on: Bool) -> (@Sendable (GlassesEvent) -> Void)? {
        cameraLock.lock(); defer { cameraLock.unlock() }
        cameraOn = on
        return events
    }

    private func keep(_ ev: @escaping @Sendable (GlassesEvent) -> Void) {
        cameraLock.lock(); defer { cameraLock.unlock() }
        events = ev
    }

    private var wantsFrames: Bool { cameraLock.lock(); defer { cameraLock.unlock() }; return cameraOn }

    /// A flat synthetic picture (no real scene): proves the frame path, nothing else.
    static func syntheticFrame(_ i: Int) -> GlassesFrame? {
        guard let ctx = CGContext(data: nil, width: 90, height: 160, bitsPerComponent: 8, bytesPerRow: 0,
                                  space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return nil }
        ctx.setFillColor(red: 0.45, green: 0.7 + 0.05 * Double(i % 3), blue: 0.5, alpha: 1)
        ctx.fill(CGRect(x: 0, y: 0, width: 90, height: 160))
        return ctx.makeImage().flatMap { GlassesVision.encode($0) }
    }

    public init(dropAfter: TimeInterval? = nil, cadence: Double = 108) {
        self.dropAfter = dropAfter
        self.cadence = cadence
    }

    public func start(_ events: @escaping @Sendable (GlassesEvent) -> Void) async {
        events(.state(.searching))
        keep(events)
        let cadence = cadence, dropAfter = dropAfter
        task = Task.detached { [weak self] in
            try? await Task.sleep(nanoseconds: 800_000_000)
            events(.state(.connected))
            var gen = MockGait(cadence: cadence)
            let begin = Date()
            var lastBright = -100.0
            var lastFrame = -100.0
            var frames = 0
            while !Task.isCancelled {
                let elapsed = Date().timeIntervalSince(begin)
                if let d = dropAfter, elapsed > d { events(.state(.disconnected)); return }
                events(.imu(gen.next(seconds: 0.2)))
                if elapsed - lastBright >= 20 { lastBright = elapsed; events(.brightness(0.62)) }
                if self?.wantsFrames == true, elapsed - lastFrame >= GlassesVision.minInterval,
                   let f = MockGlasses.syntheticFrame(frames) {
                    lastFrame = elapsed; frames += 1
                    events(.frame(f))
                }
                try? await Task.sleep(nanoseconds: 200_000_000)
            }
        }
    }

    public func stop() async {
        task?.cancel()
        task = nil
    }
}

/// Deterministic walking signal generator (also used by the tests): vertical bounce per step on the gravity
/// axis, ±3 % step-interval jitter, and a 4 s look-down (35° pitch) at the end of every 30 s.
public struct MockGait: Sendable {
    public var rate: Double = 30
    public var cadence: Double
    public var lookDownEvery: Double = 30
    public var lookDownFor: Double = 4
    private var t: Double = 0
    private var phase: Double = 0
    private var seed: UInt64 = 42

    public init(cadence: Double = 108) { self.cadence = cadence; stepPeriod = 60 / cadence }

    private mutating func rand() -> Double {
        seed = seed &* 6364136223846793005 &+ 1442695040888963407
        return Double(seed >> 11) / Double(1 << 53)
    }

    private var stepPeriod: Double = 60.0 / 108

    public mutating func next(seconds: Double) -> [IMUSample] {
        var out: [IMUSample] = []
        let n = Int(seconds * rate)
        for _ in 0..<n {
            t += 1 / rate
            phase += (1 / rate) / stepPeriod
            if phase >= 1 {
                phase -= 1
                stepPeriod = 60.0 / cadence * (1 + (rand() - 0.5) * 0.06)
            }
            let bounce = Float(2.6 * max(0, sin(phase * 2 * .pi)))   // one push per step
            let down = t.truncatingRemainder(dividingBy: lookDownEvery) >= lookDownEvery - lookDownFor
            let pitch = Float(down ? 35.0 * .pi / 180 : 0)
            let g: Float = 9.81
            let gravity = SIMD3<Float>(0, g * cos(pitch), g * sin(pitch))
            let up = gravity / simd_length(gravity)
            out.append(IMUSample(t: t, accel: gravity + up * bounce))
        }
        return out
    }
}
