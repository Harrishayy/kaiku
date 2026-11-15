import XCTest
@testable import KaikuKit

/// Visible expression cues (D60): the pure detector. A cue is a kind of expression that HOLDS, against the person's
/// own level earlier in the same task; a brief one, a face that was not in view, or a smile over it is none.
final class ExpressionCueTests: XCTestCase {
    /// An ARKit-like reading. All four cue-only values present, as the iPhone source sends them.
    private func face(smile: Double = 0.05, frown: Double = 0.05, inner: Double = 0.05, furrow: Double = 0.05,
                      press: Double = 0.05, squint: Double = 0.05) -> FaceReading {
        FaceReading(smile: smile, browRaise: inner, browFurrow: furrow, eyeClosed: 0.1, mouthOpen: 0,
                    frown: frown, browInner: inner, press: press, squint: squint)
    }

    /// The stricter thresholds these tests were written against (the shipped defaults are shorter).
    private var strict: ExpressionCueRules {
        var r = ExpressionCueRules(); r.settle_s = 20; r.sustain_s = 8; r.min_gap_s = 180; r.max_per_conversation = 2
        return r
    }

    /// Feeds `seconds` of one reading at 10 a second, starting at `t`; returns the cues handed over and the end time.
    @discardableResult
    private func run(_ d: inout ExpressionCueDetector, from t: Double, seconds: Double, _ reading: FaceReading?,
                     into fired: inout [ExpressionCueKind]) -> Double {
        var now = t
        for _ in 0..<Int((seconds * 10).rounded()) {
            now += 0.1
            if let k = d.add(at: now, reading) { fired.append(k) }
        }
        return now
    }

    func testALowerExpressionThatHoldsIsOneCueAndABriefOneIsNone() {
        var d = ExpressionCueDetector(rules: strict), fired: [ExpressionCueKind] = []
        var t = run(&d, from: 0, seconds: 25, face(), into: &fired)                      // her own level in this task
        t = run(&d, from: t, seconds: 4, face(frown: 0.45, inner: 0.4), into: &fired)   // a passing look: under 8 s
        t = run(&d, from: t, seconds: 5, face(), into: &fired)
        XCTAssertEqual(fired, []); XCTAssertTrue(d.counts.isEmpty, "a brief one is not counted either")
        t = run(&d, from: t, seconds: 12, face(frown: 0.45, inner: 0.4), into: &fired)
        XCTAssertEqual(fired, [.lower])
        XCTAssertEqual(d.counts["lower"]?.n, 1)
        XCTAssertEqual(d.counts["lower"]?.seconds ?? 0, 12, accuracy: 0.6)
        XCTAssertNil(d.counts["tense"]); XCTAssertNil(d.counts["brighter"])
    }

    func testNothingHoldsBeforeTheSettlingTimeAndTheLevelIsHerOwn() {
        var d = ExpressionCueDetector(rules: strict), fired: [ExpressionCueKind] = []
        // A face that rests with its mouth corners down from the first frame: that IS her level, not a cue.
        _ = run(&d, from: 0, seconds: 60, face(frown: 0.45, inner: 0.4), into: &fired)
        XCTAssertEqual(fired, []); XCTAssertTrue(d.counts.isEmpty)
    }

    func testASmileRulesOutLowerAndIsBrighterWhenItHolds() {
        var d = ExpressionCueDetector(rules: strict), fired: [ExpressionCueKind] = []
        var t = run(&d, from: 0, seconds: 25, face(), into: &fired)
        t = run(&d, from: t, seconds: 12, face(smile: 0.6, frown: 0.45, inner: 0.4), into: &fired)
        XCTAssertEqual(fired, [.brighter], "smiling with the brows up is not a lower expression")
        XCTAssertNil(d.counts["lower"])
    }

    func testTenseNeedsTheBrowsDownWithPressedLipsOrNarrowedEyes() {
        var d = ExpressionCueDetector(rules: strict), fired: [ExpressionCueKind] = []
        var t = run(&d, from: 0, seconds: 25, face(), into: &fired)
        t = run(&d, from: t, seconds: 12, face(furrow: 0.2), into: &fired)                 // brows a little down, alone
        XCTAssertEqual(fired, [])
        _ = run(&d, from: t, seconds: 12, face(furrow: 0.5, press: 0.45), into: &fired)
        XCTAssertEqual(fired, [.tense]); XCTAssertEqual(d.counts["tense"]?.n, 1)
    }

    func testAFaceThatLeavesTheViewBreaksTheStretch() {
        var d = ExpressionCueDetector(rules: strict), fired: [ExpressionCueKind] = []
        var t = run(&d, from: 0, seconds: 25, face(), into: &fired)
        for _ in 0..<4 {                                                                   // 5 s seen, 1 s gone, again and again
            t = run(&d, from: t, seconds: 5, face(frown: 0.45, inner: 0.4), into: &fired)
            t = run(&d, from: t, seconds: 1, nil, into: &fired)
        }
        XCTAssertEqual(fired, [], "twenty seconds in pieces of five is not eight seconds held")
        XCTAssertTrue(d.counts.isEmpty)
    }

    func testHandOverIsLimitedButEveryStretchIsCounted() {
        var rules = strict; rules.min_gap_s = 60; rules.max_per_conversation = 2
        var d = ExpressionCueDetector(rules: rules), fired: [ExpressionCueKind] = []
        var t = run(&d, from: 0, seconds: 25, face(), into: &fired)
        for _ in 0..<4 {                                                                   // four stretches, 22 s apart
            t = run(&d, from: t, seconds: 12, face(frown: 0.45, inner: 0.4), into: &fired)
            t = run(&d, from: t, seconds: 10, face(), into: &fired)
        }
        // They held at 8, 30, 52 and 74 s after settling: the second and third are inside the 60 s gap, the fourth is not.
        XCTAssertEqual(fired, [.lower, .lower])
        XCTAssertEqual(d.counts["lower"]?.n, 4, "every stretch is counted, handed over or not")
        t = run(&d, from: t, seconds: 70, face(), into: &fired)
        _ = run(&d, from: t, seconds: 12, face(frown: 0.45, inner: 0.4), into: &fired)
        XCTAssertEqual(fired.count, 2, "never more than max_per_conversation")
        XCTAssertEqual(d.counts["lower"]?.n, 5)
    }

    func testDisabledRulesSeeNothingAndBrokenNumbersAreBounded() {
        var off = strict; off.enabled = false
        var d = ExpressionCueDetector(rules: off), fired: [ExpressionCueKind] = []
        var t = run(&d, from: 0, seconds: 25, face(), into: &fired)
        _ = run(&d, from: t, seconds: 20, face(frown: 0.6, inner: 0.6), into: &fired)
        XCTAssertEqual(fired, []); XCTAssertTrue(d.counts.isEmpty)
        var odd = ExpressionCueRules(); odd.sustain_s = 0; odd.settle_s = -.infinity; odd.rise = 0
        XCTAssertEqual(odd.bounded.sustain_s, 2); XCTAssertEqual(odd.bounded.settle_s, 8); XCTAssertEqual(odd.bounded.rise, 0.02)
        t = 0
        var e = ExpressionCueDetector()
        XCTAssertNil(e.add(at: .nan, face()))
    }

    func testTheMacsLandmarksGiveOnlyBrighterFromTheMouthGettingWider() {
        func mac(width: Double) -> FaceReading {
            FaceReading(eyeClosed: 0.1, mouthOpen: 0, head: .place(x: 100, y: 100, width: 200), shape: [width, 0.3])
        }
        XCTAssertEqual(Set(ExpressionCueDetector.signals(mac(width: 0.5)).keys), [.brighter],
                       "flat landmarks cannot tell a lower or a tense expression: those kinds are not reported")
        var d = ExpressionCueDetector(rules: strict), fired: [ExpressionCueKind] = []
        var t = 0.0
        for _ in 0..<250 { t += 0.1; if let k = d.add(at: t, mac(width: 0.50)) { fired.append(k) } }
        for _ in 0..<120 { t += 0.1; if let k = d.add(at: t, mac(width: 0.53)) { fired.append(k) } }   // 6% wider: not enough
        XCTAssertEqual(fired, [])
        for _ in 0..<120 { t += 0.1; if let k = d.add(at: t, mac(width: 0.62)) { fired.append(k) } }   // a quarter wider, held
        XCTAssertEqual(fired, [.brighter])
    }

    func testTheShippedDefaultsFireOnceForAClearLookHeldAboutFiveSeconds() {
        var d = ExpressionCueDetector(), fired: [ExpressionCueKind] = []
        var t = run(&d, from: 0, seconds: 9, face(), into: &fired)
        t = run(&d, from: t, seconds: 5, face(frown: 0.5, inner: 0.4), into: &fired)
        XCTAssertEqual(fired, [.lower])
        t = run(&d, from: t, seconds: 4, face(), into: &fired)
        _ = run(&d, from: t, seconds: 5, face(smile: 0.7), into: &fired)
        XCTAssertEqual(fired, [.lower], "a second one inside 90 s is counted but not handed over")
        XCTAssertEqual(d.counts["brighter"]?.n, 1)
    }

    func testTheSentenceForKaikuIsFixedAndNeverNamesAFeelingOrANumber() {
        XCTAssertEqual(ExpressionCueText.all.count, 3)
        for kind in ExpressionCueKind.allCases {
            let text = ExpressionCueText.text(kind).lowercased()
            XCTAssertTrue(text.hasPrefix("[source: device camera]"))
            XCTAssertTrue(text.contains("do not say you saw their face or mention a camera"))
            XCTAssertTrue(text.contains("do not name a feeling"))
            for word in ["sad", "depress", "unhappy", "upset", "angry", "anxious", "emotion", "diagnos", "relapse", "score"] {
                XCTAssertFalse(text.contains(word), "\(kind): \(word)")
            }
            XCTAssertNil(text.rangeOfCharacter(from: .decimalDigits), "no number crosses")
        }
    }

    func testCuesRideInTheFaceSignsPayloadOnlyWhenSomeHeldAndAFaceWasSeen() throws {
        let signs = FaceSignsSummary(method: "arkit_blendshapes", durationS: 90, samples: 900, coverage: 0.95)
        var result = TaskCameraResult(signs: signs, geometry: nil, simulated: false)
        var payload = FaceSigns(result, task: FaceSigns.checkIn, device: .phone, ref: nil)
        XCTAssertNil(payload.cues)
        XCTAssertFalse(String(data: try JSONEncoder().encode(payload), encoding: .utf8)!.contains("cues"), "absent, never empty")
        result.cues = ["lower": FaceCueCount(n: 2, seconds: 40.3)]
        payload = FaceSigns(result, task: FaceSigns.checkIn, device: .phone, ref: nil)
        XCTAssertEqual(payload.cues, ["lower": FaceCueCount(n: 2, seconds: 40.3)])
        var unseen = result; unseen.signs.coverage = 0
        XCTAssertNil(FaceSigns(unseen, task: FaceSigns.checkIn, device: .phone, ref: nil).cues, "no usable face: no cue")
    }

    func testRulesDecodeWithMissingFieldsAsTheDefaults() throws {
        let r = try JSONDecoder().decode(ExpressionCueRules.self, from: Data(#"{"sustain_s": 12, "speak": false}"#.utf8))
        XCTAssertEqual(r.sustain_s, 12); XCTAssertFalse(r.speak); XCTAssertTrue(r.enabled); XCTAssertEqual(r.settle_s, 8)
    }
}
