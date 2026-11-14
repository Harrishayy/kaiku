import Foundation
import simd

/// Walk numbers from the glasses IMU, computed on the phone in memory (plan 05 §6). Axis-agnostic:
/// - steps: peaks of |a| above its running mean (≥ 1.0 m/s², ≥ 0.28 s apart);
/// - cadence: steps per minute of walking time (step intervals ≤ 2 s);
/// - gait regularity: 1 − coefficient of variation of the step intervals (clamped 0…1);
/// - head-up ratio: share of time the slow gravity vector is within 20° of the "looking ahead" reference
///   (the median gravity direction of the first seconds of walking).
public struct GaitAnalyzer: Sendable {
    public private(set) var steps = 0
    private var intervals: [Double] = []
    private var lastStepT: Double?
    private var mean: Float = 9.81
    private var prev: Float = 0
    private var prevPrev: Float = 0
    private var prevT: Double = 0
    private var gravity: SIMD3<Float>?
    private var calib: [SIMD3<Float>] = []
    private var reference: SIMD3<Float>?
    private var upTime = 0.0
    private var totalTime = 0.0
    private var lastT: Double?

    public static let peakThreshold: Float = 1.0
    public static let minStep = 0.28
    public static let headUpDegrees: Float = 20
    public static let calibrationSamples = 60

    public init() {}

    public mutating func add(_ samples: [IMUSample]) { for s in samples { add(s) } }

    public mutating func add(_ s: IMUSample) {
        let m = simd_length(s.accel)
        mean += (m - mean) * 0.02
        let x = m - mean
        // local maximum at the previous sample
        if prev > prevPrev, prev >= x, prev > Self.peakThreshold {
            if let last = lastStepT {
                let dt = prevT - last
                if dt >= Self.minStep {
                    steps += 1
                    if dt <= 2 { intervals.append(dt) }
                    lastStepT = prevT
                }
            } else {
                steps += 1
                lastStepT = prevT
            }
        }
        prevPrev = prev; prev = x; prevT = s.t

        // slow gravity estimate → head pitch relative to the walking reference
        let g = gravity.map { $0 + (s.accel - $0) * 0.05 } ?? s.accel
        gravity = g
        let dt = lastT.map { min(0.5, max(0, s.t - $0)) } ?? 0
        lastT = s.t
        if reference == nil {
            calib.append(simd_normalize(g))
            if calib.count >= Self.calibrationSamples {
                // component-wise median is plenty for a near-constant vector
                func med(_ k: (SIMD3<Float>) -> Float) -> Float { let v = calib.map(k).sorted(); return v[v.count / 2] }
                reference = simd_normalize(SIMD3(med { $0.x }, med { $0.y }, med { $0.z }))
            }
        }
        if let r = reference {
            let cosA = simd_dot(simd_normalize(g), r)
            let angle = acos(min(1, max(-1, cosA))) * 180 / .pi
            totalTime += dt
            if angle <= Self.headUpDegrees { upTime += dt }
        }
    }

    public var walkingSeconds: Double { intervals.reduce(0, +) }

    public var cadence: Double? {
        guard intervals.count >= 10, walkingSeconds > 0 else { return nil }
        return min(250, Double(intervals.count) / walkingSeconds * 60)
    }

    public var regularity: Double? {
        guard intervals.count >= 10 else { return nil }
        let mu = intervals.reduce(0, +) / Double(intervals.count)
        let sd = sqrt(intervals.map { ($0 - mu) * ($0 - mu) }.reduce(0, +) / Double(intervals.count))
        return min(1, max(0, 1 - sd / mu))
    }

    public var headUpRatio: Double? {
        guard totalTime >= 10 else { return nil }
        return min(1, max(0, upTime / totalTime))
    }
}

/// Daylight minutes from sparse brightness readings: each reading stands for the time until the next one
/// (capped at 60 s); readings ≥ 0.45 count as daylight.
public struct DaylightCounter: Sendable {
    private var last: (Date, Double)?
    public private(set) var seconds = 0.0
    public private(set) var readings = 0
    public static let threshold = 0.45
    public init() {}

    public mutating func add(_ brightness: Double, at t: Date = Date()) {
        if let (d, b) = last, b >= Self.threshold { seconds += min(60, t.timeIntervalSince(d)) }
        last = (t, brightness)
        readings += 1
    }

    public mutating func close(at t: Date = Date()) {
        if let (d, b) = last, b >= Self.threshold { seconds += min(60, t.timeIntervalSince(d)) }
        last = nil
    }

    public var minutes: Double? { readings > 0 ? seconds / 60 : nil }
}
