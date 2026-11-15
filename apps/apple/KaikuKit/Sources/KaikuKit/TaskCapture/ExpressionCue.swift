import Foundation

// Visible expression cues (D60): the pure part. Per-frame numbers in, "this kind of expression has held for a
// while" out. A cue is named for what is seen on the face, never for what the person feels: a movement of the
// face is not proof of a feeling (Barrett et al. 2019). It is a reason for Kaiku to ask one open question, never
// a conclusion, and it is measured only against this person's own level earlier in the same task.
// No camera types and no pixels in this file; nothing here is stored except the counts in `tallies`.

/// The kinds, by what is seen.
public enum ExpressionCueKind: String, Codable, Sendable, CaseIterable {
    /// Less smiling, with the mouth corners down or the inner brows up.
    case lower
    /// Brows drawn down, with the lips pressed or the eyes narrowed.
    case tense
    /// Sustained smiling.
    case brighter
}

/// The thresholds (service config `[expression_cue]`, sent with the session; these defaults when it sends none).
public struct ExpressionCueRules: Codable, Sendable, Equatable {
    public var enabled = true
    /// May a cue put one quiet context turn into the open conversation.
    public var speak = true
    /// Face time before anything can hold: the person's own level in this task is taken from it.
    public var settle_s = 8.0
    /// How long it must hold without a break.
    public var sustain_s = 4.5
    /// How far above the person's own level in this task (0…1 strengths; for a landmark shape, the share wider).
    public var rise = 0.15
    /// At most one cue handed to the conversation in this long.
    public var min_gap_s = 90.0
    public var max_per_conversation = 3

    public static let standard = ExpressionCueRules()
    public init() {}

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let d = ExpressionCueRules()
        enabled = try c.decodeIfPresent(Bool.self, forKey: .enabled) ?? d.enabled
        speak = try c.decodeIfPresent(Bool.self, forKey: .speak) ?? d.speak
        settle_s = try c.decodeIfPresent(Double.self, forKey: .settle_s) ?? d.settle_s
        sustain_s = try c.decodeIfPresent(Double.self, forKey: .sustain_s) ?? d.sustain_s
        rise = try c.decodeIfPresent(Double.self, forKey: .rise) ?? d.rise
        min_gap_s = try c.decodeIfPresent(Double.self, forKey: .min_gap_s) ?? d.min_gap_s
        max_per_conversation = try c.decodeIfPresent(Int.self, forKey: .max_per_conversation) ?? d.max_per_conversation
    }

    /// Held to sane bounds whatever was sent: a detector never runs on a zero or a negative time.
    var bounded: ExpressionCueRules {
        var r = self
        r.settle_s = min(600, max(5, settle_s.isFinite ? settle_s : 8))
        r.sustain_s = min(120, max(2, sustain_s.isFinite ? sustain_s : 4.5))
        r.rise = min(1, max(0.02, rise.isFinite ? rise : 0.15))
        r.min_gap_s = min(3600, max(0, min_gap_s.isFinite ? min_gap_s : 90))
        r.max_per_conversation = min(10, max(0, max_per_conversation))
        return r
    }
}

/// How often and for how long one kind held in a task (`obs.face_signs.cues`).
public struct FaceCueCount: Codable, Sendable, Equatable {
    public var n: Int
    public var seconds: Double
    public init(n: Int, seconds: Double) { self.n = n; self.seconds = seconds }
}

/// The one sentence Kaiku is given for a cue. Fixed text: nothing measured, no number and no word of the person's
/// goes into it. Kaiku decides whether it fits; nothing is spoken by rule.
public enum ExpressionCueText {
    static let never = "Do not say you saw their face or mention a camera; do not name a feeling for them; do not repeat this later."
    /// A cue that could not be handed over (someone was speaking) for this long is dropped: the moment has passed.
    public static let staleAfter: TimeInterval = 30

    public static func text(_ kind: ExpressionCueKind) -> String {
        switch kind {
        case .lower:
            return "[source: device camera] For a little while their expression has looked lower than earlier in this "
                + "conversation. If it fits the moment, ask one short, open question about how they are doing right now. " + never
        case .tense:
            return "[source: device camera] For a little while their expression has looked more tense than earlier in this "
                + "conversation. If it fits the moment, slow down and ask one short, open question about how this is going "
                + "for them. " + never
        case .brighter:
            return "[source: device camera] For a little while their expression has looked brighter than earlier in this "
                + "conversation. If it fits the moment, you may be a little warmer and lighter. " + never
        }
    }

    public static let all: Set<String> = Set(ExpressionCueKind.allCases.map(text))
}

/// Turns per-frame readings into cues. Online: a few running numbers a kind, nothing else.
struct ExpressionCueDetector: Sendable {
    /// One kind's strength in one frame. `relative`: read as a share above the person's level (a landmark shape,
    /// whose size differs from face to face) instead of a 0…1 strength above it.
    struct Signal: Sendable, Equatable {
        var value: Double
        var relative = false
        /// False = something else on the face rules this kind out in this frame (a smile rules out lower and tense).
        var open = true
    }

    private struct Track: Sendable {
        var sum = 0.0, count = 0
        var level: Double?
        var on = false
        var since = 0.0
        var counted = false
    }

    /// A smile at or above this rules out `lower` and `tense` in that frame, and `brighter` needs at least it
    /// (the smile's own "off" level in `FaceSignRules.arkit`: under it nobody would call it a smile).
    static let smileLine = 0.25
    /// After the settling time the level follows the signal this slowly (seconds), and only while the kind is off:
    /// a face that settles into a new resting look stops being a cue, a held one does not pull its own level up.
    static let levelSeconds = 120.0
    static let order: [ExpressionCueKind] = [.lower, .tense, .brighter]

    let rules: ExpressionCueRules
    private(set) var tallies: [ExpressionCueKind: FaceCueCount] = [:]
    private var tracks: [ExpressionCueKind: Track] = [:]
    private var faceSeconds = 0.0
    private var lastFaceT: Double?
    private var lastT: Double?
    private var handed = 0
    private var lastHandedAt: Double?

    init(rules: ExpressionCueRules = .standard) { self.rules = rules.bounded }

    /// What each kind reads in one usable face. A kind the method cannot see is absent, never guessed.
    static func signals(_ r: FaceReading) -> [ExpressionCueKind: Signal] {
        var out: [ExpressionCueKind: Signal] = [:]
        if let smile = r.smile {
            // ARKit blendshapes. lower: mouth corners down (mouthFrown) and inner brows up (browInnerUp) together
            // count fully, one alone half. tense: brows down with pressed lips or narrowed eyes.
            let calm = smile < smileLine
            if let frown = r.frown, let inner = r.browInner {
                out[.lower] = Signal(value: max(frown, (frown + inner) / 2), open: calm)
            }
            if let furrow = r.browFurrow, let press = r.press, let squint = r.squint {
                out[.tense] = Signal(value: (furrow + max(press, squint)) / 2, open: calm)
            }
            out[.brighter] = Signal(value: smile, open: smile >= smileLine)
        } else if r.shape.count == 2, r.shape[0] > 0 {
            // Vision landmarks (Mac): only the mouth getting wider than this person's own in this task, which a
            // smile does. The mouth corners' height and the brows' pull are not readable from flat landmarks
            // without knowing the resting face, so `lower` and `tense` are not reported by this method.
            out[.brighter] = Signal(value: r.shape[0], relative: true)
        }
        return out
    }

    /// One sampled frame. Returns a kind to hand to the open conversation now (at most `max_per_conversation`,
    /// `min_gap_s` apart), or nil. Every stretch that held is counted in `tallies`, handed over or not.
    mutating func add(at t: Double, _ reading: FaceReading?) -> ExpressionCueKind? {
        guard rules.enabled, t.isFinite, lastT.map({ t > $0 }) ?? true else { return nil }
        lastT = t
        guard let r = reading?.checked else { lose(); return nil }
        var dt = 0.0
        if let before = lastFaceT, t - before <= FaceSignLimits.gapCap { dt = t - before } else { lose() }
        lastFaceT = t
        faceSeconds += dt
        let signals = Self.signals(r)
        var fire: ExpressionCueKind?
        for kind in Self.order {
            guard let s = signals[kind], s.value.isFinite else { tracks[kind]?.on = false; continue }
            var track = tracks[kind] ?? Track()
            if faceSeconds < rules.settle_s || track.level == nil {
                // settling: the person's own level in this task
                track.sum += s.value; track.count += 1
                if faceSeconds >= rules.settle_s { track.level = track.sum / Double(track.count) }
                tracks[kind] = track
                continue
            }
            let level = track.level ?? 0
            let above = s.relative ? (level > 0 ? (s.value - level) / level : 0) : s.value - level
            let was = track.on
            if !track.on, s.open, above >= rules.rise { track.on = true; track.since = t; track.counted = false }
            else if track.on, !s.open || above < rules.rise / 2 { track.on = false }
            if track.on {
                if !track.counted, t - track.since >= rules.sustain_s {
                    track.counted = true
                    var c = tallies[kind] ?? FaceCueCount(n: 0, seconds: 0)
                    c.n += 1; c.seconds += t - track.since
                    tallies[kind] = c
                    if fire == nil, handed < rules.max_per_conversation,
                       lastHandedAt.map({ t - $0 >= rules.min_gap_s }) ?? true { fire = kind }
                } else if track.counted, was {
                    tallies[kind]?.seconds += dt
                }
            } else if dt > 0 {
                track.level = level + min(1, dt / Self.levelSeconds) * (s.value - level)
            }
            tracks[kind] = track
        }
        if fire != nil { handed += 1; lastHandedAt = t }
        return fire
    }

    /// The face was lost or sampling broke: nothing that was holding carries over it.
    private mutating func lose() {
        lastFaceT = nil
        for kind in tracks.keys { tracks[kind]?.on = false }
    }

    /// The counts for `obs.face_signs.cues`, seconds to one place. Empty = none held.
    var counts: [String: FaceCueCount] {
        var out: [String: FaceCueCount] = [:]
        for (kind, c) in tallies where c.n > 0 {
            out[kind.rawValue] = FaceCueCount(n: c.n, seconds: min(86_400, (c.seconds * 10).rounded() / 10))
        }
        return out
    }
}
