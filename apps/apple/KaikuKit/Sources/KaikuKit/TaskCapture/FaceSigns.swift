import Foundation

// Face signs during tasks: the pure part. No camera types and no pixels in this file: per-frame numbers go in,
// one summary a task comes out (`obs.face_signs`). A sign is something a face does (a smile, a blink, a raised
// brow, a look toward the screen). It is never a feeling: nothing here names an emotion, and the numbers are only
// comparable within the same task and the same `method`.

/// How the head is placed, as far as the method can tell.
enum HeadPose: Sendable, Equatable {
    /// ARKit: the head's orientation relative to the device, a quaternion (any length; it is normalised here).
    case rotation(x: Double, y: Double, z: Double, w: Double)
    /// Vision: the face box's centre and width in image pixels.
    case place(x: Double, y: Double, width: Double)

    /// How far the head went from `a` to `b`: degrees turned for a rotation, face widths moved for a place.
    /// nil when the two are not the same kind or not usable numbers.
    static func distance(_ a: HeadPose, _ b: HeadPose) -> Double? {
        switch (a, b) {
        case let (.rotation(ax, ay, az, aw), .rotation(bx, by, bz, bw)):
            let na = (ax * ax + ay * ay + az * az + aw * aw).squareRoot(), nb = (bx * bx + by * by + bz * bz + bw * bw).squareRoot()
            guard na > 0, nb > 0, na.isFinite, nb.isFinite else { return nil }
            let dot = abs(ax * bx + ay * by + az * bz + aw * bw) / (na * nb)
            return 2 * acos(min(1, dot)) * 180 / .pi
        case let (.place(ax, ay, aw), .place(bx, by, bw)):
            let width = (aw + bw) / 2
            guard width > 0, width.isFinite else { return nil }
            let d = hypot(bx - ax, by - ay) / width
            return d.isFinite ? d : nil
        default:
            return nil
        }
    }

    var isUsable: Bool {
        switch self {
        case let .rotation(x, y, z, w): return [x, y, z, w].allSatisfy(\.isFinite) && (x * x + y * y + z * z + w * w) > 0
        case let .place(x, y, width): return [x, y, width].allSatisfy(\.isFinite) && width > 0
        }
    }
}

/// One look at one face, as numbers. `nil` = this method does not measure that sign (it is then never guessed).
struct FaceReading: Sendable, Equatable {
    /// 0…1 strengths. ARKit: blendshape coefficients. Vision: ratios of distances between landmarks.
    var smile: Double?
    var browRaise: Double?
    var browFurrow: Double?
    /// 1 = closed.
    var eyeClosed: Double?
    var mouthOpen: Double?
    /// Looking toward the screen.
    var gazeOn: Bool?
    var head: HeadPose?
    /// More 0…1 quantities that only feed `expression_range` (Vision: mouth width, brow height: their size
    /// differs from person to person, so they are never held against a threshold, but how much they vary
    /// within one task is a fact of that task).
    var shape: [Double] = []

    /// The reading with its strengths held to 0…1, or nil when any number in it is not a number: a reading
    /// with a broken value is not a usable face.
    var checked: FaceReading? {
        var r = self
        // .some(nil) = not measured (fine); nil = measured but not a number (the whole reading is unusable).
        func unit(_ v: Double?) -> Double?? {
            guard let v else { return .some(nil) }
            return v.isFinite ? .some(.some(min(1, max(0, v)))) : .none
        }
        guard let a = unit(smile), let b = unit(browRaise), let c = unit(browFurrow), let d = unit(eyeClosed), let e = unit(mouthOpen)
        else { return nil }
        r.smile = a; r.browRaise = b; r.browFurrow = c; r.eyeClosed = d; r.mouthOpen = e
        guard head?.isUsable ?? true, shape.allSatisfy(\.isFinite) else { return nil }
        r.shape = shape.map { min(1, max(0, $0)) }
        return r
    }
}

/// When a sign counts as present. `on` to begin, `off` to end: two levels, so a value that hovers at one line
/// does not flicker in and out (and one smile is not counted as five).
struct SignLevel: Sendable, Equatable {
    var on: Double
    var off: Double
}

/// A method's thresholds. A sign without a level here is one the method does not report.
struct FaceSignRules: Sendable, Equatable {
    var method: String
    var smile: SignLevel?
    var browRaise: SignLevel?
    var browFurrow: SignLevel?
    var mouthOpen: SignLevel?
    var eyeClosed: SignLevel?

    /// ARKit face tracking (TrueDepth iPhones). Values are blendshape coefficients, 0 (neutral) to 1 (as far as
    /// the face goes). The levels are set from that scale and from how the coefficients behave at rest and in
    /// speech; they have not been calibrated against people on a device (see apps/apple/AGENTS.md).
    static let arkit = FaceSignRules(
        method: "arkit_blendshapes",
        // mean of mouthSmileLeft / Right. A resting mouth stays under about 0.15 and a spoken "ee" reaches
        // 0.2 to 0.3 for a syllable; 0.4 is a smile another person would see.
        smile: SignLevel(on: 0.40, off: 0.25),
        // the larger of browInnerUp and the mean of browOuterUpLeft / Right: either way of raising the brows.
        browRaise: SignLevel(on: 0.30, off: 0.20),
        // mean of browDownLeft / Right (brows drawn down and together).
        browFurrow: SignLevel(on: 0.30, off: 0.20),
        // jawOpen minus mouthClose: the lips are apart, not only the jaw dropped behind closed lips.
        mouthOpen: SignLevel(on: 0.20, off: 0.10),
        // the smaller of eyeBlinkLeft / Right (both eyes, so a wink is not a blink). Looking down at the screen
        // alone lifts it to 0.3 to 0.5, so closed begins at 0.7 and open again is under 0.5.
        eyeClosed: SignLevel(on: 0.70, off: 0.50))

    /// Vision face landmarks (Mac, iPhones without TrueDepth). Only what flat landmark geometry shows without
    /// knowing the person's resting face: the mouth opening and the eyes closing. A smile, the brows and the
    /// gaze are not reported by this method.
    static let vision = FaceSignRules(
        method: "vision_landmarks",
        smile: nil, browRaise: nil, browFurrow: nil,
        // the gap between the inner lips over the mouth's width. Closed lips leave under about 0.05.
        mouthOpen: SignLevel(on: 0.12, off: 0.07),
        // how far the eye opening fell below the person's own open level in this task (`OpenEyeLevel`):
        // closed begins when over a third of the opening is gone.
        eyeClosed: SignLevel(on: 0.35, off: 0.20))
}

/// The limits that hold for every method, each with its reason.
enum FaceSignLimits {
    /// The longest step between two samples that still counts as looking continuously. The sources sample 15 to
    /// 30 times a second; a step over a second means capture was paused or stalled, and that time was not seen.
    static let gapCap = 1.0
    /// A smile shorter than this is not counted as one: mouth corners move this briefly in ordinary speech.
    static let smileMinSeconds = 0.5
    /// A blink lasts about 0.1 to 0.4 s. Eyes shut for longer are closed (resting, the breathing game), not blinking.
    static let blinkMaxSeconds = 0.5
    /// Under this many seconds with a face in view a blink rate would rest on a handful of blinks: it is left out.
    static let blinkRateMinSeconds = 20.0
    /// Head poses are compared this far apart, so a tracker's frame-to-frame jitter does not add up as movement.
    static let headStep = 0.2
    /// Under this many seconds of followed head there is no movement number.
    static let headMinSeconds = 2.0
    /// Under this many face frames there is no range of expression.
    static let rangeMinFrames = 10
    /// ARKit: looking toward the screen = the gaze points within this angle of the line from the eyes to the
    /// camera. A phone's screen reaches about 23° below its camera at 35 cm; the cone is that with a little room
    /// for the gaze estimate's own error.
    static let gazeConeDegrees = 25.0

    /// The camera format that costs least: the lowest frame rate on offer, then the fewest pixels.
    static func lightest<F>(_ formats: [(fps: Int, pixels: Int, format: F)]) -> F? {
        formats.min { ($0.fps, $0.pixels) < ($1.fps, $1.pixels) }?.format
    }

    /// Whether a gaze direction counts as toward the screen. Both vectors in the same space, any length.
    static func gazeOn(direction d: (x: Double, y: Double, z: Double), toCamera c: (x: Double, y: Double, z: Double)) -> Bool? {
        let nd = (d.x * d.x + d.y * d.y + d.z * d.z).squareRoot(), nc = (c.x * c.x + c.y * c.y + c.z * c.z).squareRoot()
        guard nd > 0, nc > 0, nd.isFinite, nc.isFinite else { return nil }
        let cosine = (d.x * c.x + d.y * c.y + d.z * c.z) / (nd * nc)
        return acos(min(1, max(-1, cosine))) * 180 / .pi <= gazeConeDegrees
    }
}

/// What one task's camera time comes to. Optional = not measured by the method, or too little to say.
struct FaceSignsSummary: Equatable, Sendable {
    var method: String
    /// Seconds the camera sampled (pauses are not counted).
    var durationS: Double
    /// Frames looked at.
    var samples: Int
    /// Share of those frames with exactly one usable face.
    var coverage: Double
    var smileShare: Double?
    var smiles: Int?
    var browRaiseShare: Double?
    var browFurrowShare: Double?
    var mouthOpenShare: Double?
    var blinksPerMin: Double?
    var gazeOnShare: Double?
    /// ARKit: degrees a second the head turns relative to the device. Vision: face widths a second the face
    /// moves in the picture. Both include the device being moved.
    var headMovement: Double?
    var expressionRange: Double?
}

/// Turns per-frame readings into the summary. Online: nothing but a few running numbers is kept.
struct FaceSignsAccumulator: Sendable {
    let rules: FaceSignRules

    /// One thresholded sign: how many frames measured it, in how many it was on, and how much it varied.
    private struct Channel: Sendable {
        var measured = 0
        var onFrames = 0
        var isOn = false
        var since = 0.0
        var mean = 0.0
        var m2 = 0.0

        enum Change { case none, began, ended(seconds: Double) }

        mutating func add(_ value: Double, level: SignLevel?, at t: Double) -> Change {
            measured += 1
            let d = value - mean
            mean += d / Double(measured)
            m2 += d * (value - mean)
            guard let level else { return .none }
            var change = Change.none
            if !isOn, value >= level.on { isOn = true; since = t; change = .began }
            else if isOn, value < level.off { isOn = false; change = .ended(seconds: t - since) }
            if isOn { onFrames += 1 }
            return change
        }

        /// The face was lost: whatever was on is over, and its end was not seen.
        mutating func lose() { isOn = false }

        func share(_ level: SignLevel?) -> Double? { level != nil && measured > 0 ? Double(onFrames) / Double(measured) : nil }
        var deviation: Double? { measured >= 2 ? (max(0, m2) / Double(measured - 1)).squareRoot() : nil }
    }

    private(set) var samples = 0
    private(set) var faces = 0
    private var lastT: Double?
    private var lastFaceT: Double?
    private var sampledSeconds = 0.0
    private var faceSeconds = 0.0
    private var smile = Channel(), browRaise = Channel(), browFurrow = Channel(), mouthOpen = Channel(), eyeClosed = Channel()
    private var shape: [Channel] = []
    private var smiles = 0
    private var smileCounted = false
    private var blinks = 0
    private var gazeMeasured = 0, gazeOn = 0
    private var headAnchor: (t: Double, pose: HeadPose)?
    private var headDistance = 0.0, headSeconds = 0.0

    init(rules: FaceSignRules) { self.rules = rules }

    /// One sampled frame at `t` (seconds on the source's clock). `reading` is nil when the frame did not hold
    /// exactly one usable face. A sample without a real time, or not later than the one before, is not a sample.
    mutating func add(at t: Double, _ reading: FaceReading?) {
        guard t.isFinite, lastT.map({ t > $0 }) ?? true else { return }
        if let last = lastT, t - last <= FaceSignLimits.gapCap { sampledSeconds += t - last }
        lastT = t
        samples += 1
        guard let r = reading?.checked else { lose(); return }
        if let before = lastFaceT, t - before <= FaceSignLimits.gapCap { faceSeconds += t - before } else { lose() }
        lastFaceT = t
        faces += 1

        if let v = r.smile {
            switch smile.add(v, level: rules.smile, at: t) {
            case .began, .ended: smileCounted = false
            case .none: break
            }
            if smile.isOn, !smileCounted, t - smile.since >= FaceSignLimits.smileMinSeconds { smiles += 1; smileCounted = true }
        }
        if let v = r.browRaise { _ = browRaise.add(v, level: rules.browRaise, at: t) }
        if let v = r.browFurrow { _ = browFurrow.add(v, level: rules.browFurrow, at: t) }
        if let v = r.mouthOpen { _ = mouthOpen.add(v, level: rules.mouthOpen, at: t) }
        if let v = r.eyeClosed, case .ended(let seconds) = eyeClosed.add(v, level: rules.eyeClosed, at: t),
           seconds <= FaceSignLimits.blinkMaxSeconds { blinks += 1 }
        if let g = r.gazeOn { gazeMeasured += 1; if g { gazeOn += 1 } }
        if let pose = r.head {
            if let anchor = headAnchor {
                if t - anchor.t >= FaceSignLimits.headStep {
                    if let d = HeadPose.distance(anchor.pose, pose) { headDistance += d; headSeconds += t - anchor.t }
                    headAnchor = (t, pose)
                }
            } else { headAnchor = (t, pose) }
        }
        if shape.isEmpty { shape = Array(repeating: Channel(), count: r.shape.count) }
        if shape.count == r.shape.count { for i in shape.indices { _ = shape[i].add(r.shape[i], level: nil, at: t) } }
    }

    /// No usable face in this sample (or a break in sampling): nothing that was on carries over it.
    private mutating func lose() {
        lastFaceT = nil
        headAnchor = nil
        smile.lose(); browRaise.lose(); browFurrow.lose(); mouthOpen.lose(); eyeClosed.lose()
        smileCounted = false
    }

    var summary: FaceSignsSummary {
        // The range of expression: over the expression channels this method measures, twice each one's standard
        // deviation (a 0…1 value cannot vary by more than 0.5), averaged. Blinks are not expression and stay out.
        let channels = [smile, browRaise, browFurrow, mouthOpen] + shape
        let spreads = channels.filter { $0.measured >= FaceSignLimits.rangeMinFrames }.compactMap(\.deviation)
        let range = spreads.isEmpty ? nil : min(1, 2 * spreads.reduce(0, +) / Double(spreads.count))
        let blinkRate = rules.eyeClosed != nil && eyeClosed.measured > 0 && faceSeconds >= FaceSignLimits.blinkRateMinSeconds
            ? Double(blinks) / faceSeconds * 60 : nil
        return FaceSignsSummary(
            method: rules.method, durationS: sampledSeconds, samples: samples,
            coverage: samples > 0 ? Double(faces) / Double(samples) : 0,
            smileShare: smile.share(rules.smile), smiles: rules.smile != nil && smile.measured > 0 ? smiles : nil,
            browRaiseShare: browRaise.share(rules.browRaise), browFurrowShare: browFurrow.share(rules.browFurrow),
            mouthOpenShare: mouthOpen.share(rules.mouthOpen), blinksPerMin: blinkRate,
            gazeOnShare: gazeMeasured > 0 ? Double(gazeOn) / Double(gazeMeasured) : nil,
            headMovement: headSeconds >= FaceSignLimits.headMinSeconds ? headDistance / headSeconds : nil,
            expressionRange: range)
    }
}

/// Vision only: the person's own open-eye level in this task, so an eye is "closed" relative to how open that
/// eye usually is in this picture (eyes, glasses and camera angles differ too much for one fixed number).
/// It follows a wider eye quickly and a narrower one slowly, so a blink does not pull the level down with it.
struct OpenEyeLevel: Sendable {
    /// Share of the difference taken up a sample when the eye is wider than the level / narrower than it.
    static let rise = 0.3, fall = 0.02
    /// An eye flatter than this in the picture (a face turned far away, a very small face) cannot be told open
    /// from closed.
    static let floor = 0.05
    private(set) var level: Double?

    /// 0 (as open as usual) … 1 (shut) for an eye opening of `aspect` (height over width), or nil when it cannot say.
    mutating func closedness(of aspect: Double) -> Double? {
        guard aspect.isFinite, aspect >= 0 else { return nil }
        if let l = level { level = l + (aspect > l ? Self.rise : Self.fall) * (aspect - l) } else { level = aspect }
        guard let l = level, l >= Self.floor else { return nil }
        return min(1, max(0, 1 - aspect / l))
    }
}
