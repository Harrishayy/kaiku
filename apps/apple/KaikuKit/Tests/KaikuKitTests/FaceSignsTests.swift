import AVFoundation
import CoreGraphics
import XCTest
@testable import KaikuKit

// Face signs during tasks ("Camera during activities"). Everything here runs on made-up numbers: sequences
// written out below, a stand-in camera source (`FakeFaceSource`), a fake Live line and a stubbed service.
// No test opens a camera, looks at a face or reaches a network. What these tests cannot show (what ARKit and
// Vision report for a real face) is listed in apps/apple/AGENTS.md → "Face signs during tasks".

// MARK: - made-up sequences

/// A face at rest, as each method would report it.
private func rest(_ rules: FaceSignRules = .arkit) -> FaceReading {
    rules.method == "arkit_blendshapes"
        ? FaceReading(smile: 0.05, browRaise: 0.04, browFurrow: 0.03, eyeClosed: 0.1, mouthOpen: 0.02, gazeOn: true,
                      head: .rotation(x: 0, y: 0, z: 0, w: 1))
        : FaceReading(eyeClosed: 0.02, mouthOpen: 0.03, head: .place(x: 320, y: 240, width: 200), shape: [0.45, 0.33])
}

/// Feeds `seconds` of readings at `hz`, `make(t)` giving the reading at each time (nil = no face in that frame).
private func watch(_ rules: FaceSignRules = .arkit, seconds: Double, hz: Double = 30, from start: Double = 0,
                 into given: FaceSignsAccumulator? = nil, _ make: (Double) -> FaceReading?) -> FaceSignsAccumulator {
    var a = given ?? FaceSignsAccumulator(rules: rules)
    let n = Int((seconds * hz).rounded())
    for i in 0...n { let t = start + Double(i) / hz; a.add(at: t, make(t)) }
    return a
}

/// True inside any of the half-open windows `[from, from + length)`.
private func within(_ t: Double, _ windows: [(Double, Double)]) -> Bool { windows.contains { t >= $0.0 - 1e-9 && t < $0.0 + $0.1 - 1e-9 } }

// MARK: - the accumulator

final class FaceSignsAccumulatorTests: XCTestCase {
    func testAStillFaceHasFullCoverageAndNothingHappening() {
        let s = watch(seconds: 60) { _ in rest() }.summary
        XCTAssertEqual(s.method, "arkit_blendshapes")
        XCTAssertEqual(s.samples, 1801)
        XCTAssertEqual(s.durationS, 60, accuracy: 0.001)
        XCTAssertEqual(s.coverage, 1)
        XCTAssertEqual(s.smileShare, 0); XCTAssertEqual(s.smiles, 0)
        XCTAssertEqual(s.browRaiseShare, 0); XCTAssertEqual(s.browFurrowShare, 0); XCTAssertEqual(s.mouthOpenShare, 0)
        XCTAssertEqual(s.blinksPerMin, 0, "a minute with a face and no blink is a rate of zero, not a missing number")
        XCTAssertEqual(s.gazeOnShare, 1)
        XCTAssertEqual(s.headMovement ?? -1, 0, accuracy: 1e-9)
        XCTAssertEqual(s.expressionRange ?? -1, 0, accuracy: 1e-9)
    }

    func testABlinkTrainIsCountedAndGivenAsARate() {
        // One blink every 4 s, each 0.2 s long, for a minute: 15 blinks.
        let blinks = stride(from: 2.0, to: 60.0, by: 4.0).map { ($0, 0.2) }
        let s = watch(seconds: 60) { t in var r = rest(); r.eyeClosed = within(t, blinks) ? 0.95 : 0.1; return r }.summary
        XCTAssertEqual(s.blinksPerMin ?? -1, 15, accuracy: 0.01)
        XCTAssertEqual(s.smiles, 0)
        XCTAssertEqual(s.expressionRange ?? -1, 0, accuracy: 1e-9, "blinks are not expression")
    }

    func testEyesShutForLongAreClosedNotBlinking() {
        let s = watch(seconds: 40) { t in var r = rest(); r.eyeClosed = within(t, [(5, 2.0), (20, 0.7)]) ? 0.95 : 0.1; return r }.summary
        XCTAssertEqual(s.blinksPerMin, 0, "0.7 s and 2 s with the eyes shut are longer than a blink")
        let edge = watch(seconds: 40) { t in var r = rest(); r.eyeClosed = within(t, [(5, 0.4)]) ? 0.95 : 0.1; return r }.summary
        XCTAssertEqual(edge.blinksPerMin ?? -1, 1.5, accuracy: 0.01, "0.4 s is still a blink")
    }

    func testLookingDownIsNotABlinkAndAValueAtTheLineIsOneClosure() {
        // Looking down at the screen: the coefficient sits at 0.45 the whole time, under the closed level.
        let down = watch(seconds: 30) { _ in var r = rest(); r.eyeClosed = 0.45; return r }.summary
        XCTAssertEqual(down.blinksPerMin, 0)
        // One 0.3 s closure whose value wobbles around the closed level (0.72, 0.66, 0.74, …): never under 0.5
        // until it ends, so it is one blink, not one per wobble.
        let wobble = watch(seconds: 30) { t in
            var r = rest()
            r.eyeClosed = within(t, [(10, 0.3)]) ? (Int((t * 30).rounded()) % 2 == 0 ? 0.72 : 0.66) : 0.2
            return r
        }.summary
        XCTAssertEqual(wobble.blinksPerMin ?? -1, 2, accuracy: 0.01)
    }

    func testTwoSmilesAreTwoAndASyllableIsNone() {
        // A 2 s smile, a 1.5 s smile, and a 0.2 s pull of the mouth corners (a spoken "ee"): two smiles.
        let on: [(Double, Double)] = [(5, 2.0), (12, 1.5), (20, 0.2)]
        let s = watch(seconds: 30) { t in var r = rest(); r.smile = within(t, on) ? 0.6 : 0.05; return r }.summary
        XCTAssertEqual(s.smiles, 2)
        XCTAssertEqual(s.smileShare ?? -1, 3.7 / 30, accuracy: 0.005, "the share is every frame with the smile on")
        XCTAssertGreaterThan(s.expressionRange ?? 0, 0.05)
    }

    func testASmileThatHoversAtTheLineIsOneSmile() {
        // 0.42, 0.37, 0.41, 0.36, … for three seconds: it goes on at 0.40 and only off under 0.25.
        let s = watch(seconds: 10) { t in
            var r = rest()
            r.smile = within(t, [(2, 3.0)]) ? (Int((t * 30).rounded()) % 2 == 0 ? 0.42 : 0.37) : 0.05
            return r
        }.summary
        XCTAssertEqual(s.smiles, 1)
        XCTAssertEqual(s.smileShare ?? -1, 0.3, accuracy: 0.01)
        // The same wobble that never reaches the "on" level is not a smile at all.
        let under = watch(seconds: 10) { t in var r = rest(); r.smile = Int((t * 30).rounded()) % 2 == 0 ? 0.39 : 0.30; return r }.summary
        XCTAssertEqual(under.smiles, 0); XCTAssertEqual(under.smileShare, 0)
    }

    func testAnOngoingSmileAtTheEndCountsOnce() {
        let s = watch(seconds: 10) { t in var r = rest(); r.smile = t >= 8 ? 0.7 : 0.05; return r }.summary
        XCTAssertEqual(s.smiles, 1, "two seconds of smile is a smile even if the task ends during it")
    }

    func testBrowsAndMouthAreSharesOfFaceFrames() {
        let s = watch(seconds: 20) { t in
            var r = rest()
            r.browRaise = within(t, [(0, 5.0)]) ? 0.5 : 0.05
            r.browFurrow = within(t, [(10, 2.0)]) ? 0.4 : 0.05
            r.mouthOpen = within(t, [(5, 10.0)]) ? 0.3 : 0.02
            return r
        }.summary
        XCTAssertEqual(s.browRaiseShare ?? -1, 0.25, accuracy: 0.01)
        XCTAssertEqual(s.browFurrowShare ?? -1, 0.10, accuracy: 0.01)
        XCTAssertEqual(s.mouthOpenShare ?? -1, 0.50, accuracy: 0.01)
    }

    func testAFaceThatLeavesTheFrame() {
        // 10 s there, 10 s gone, 10 s back. A smile and a closure are both cut by the face leaving.
        let s = watch(seconds: 30) { t in
            if t >= 10 && t < 20 { return nil }
            var r = rest()
            r.smile = (t >= 9.7 && t < 10) || (t >= 20 && t < 20.3) ? 0.7 : 0.05      // 0.3 s each side of the gap
            r.eyeClosed = (t >= 9.9 && t < 10) || (t >= 20 && t < 20.1) ? 0.95 : 0.1  // shut when it left, shut when it came back
            r.head = .rotation(x: 0, y: t < 10 ? 0 : sin(0.5), z: 0, w: t < 10 ? 1 : cos(0.5))   // came back turned by a radian
            return r
        }.summary
        XCTAssertEqual(s.coverage, 2.0 / 3, accuracy: 0.01)
        XCTAssertEqual(s.durationS, 30, accuracy: 0.001, "the camera sampled all thirty seconds")
        XCTAssertEqual(s.smiles, 0, "two 0.3 s pieces either side of a gap are not one 0.6 s smile")
        XCTAssertNil(s.blinksPerMin, "under twenty seconds with a face: no rate")
        XCTAssertEqual(s.headMovement ?? -1, 0, accuracy: 1e-6, "where the head is after a gap is not movement across it")
    }

    func testAClosureCutByTheFaceLeavingIsNotABlink() {
        // The eyes shut just as the face leaves the picture (not counted: its end was not seen); one whole blink later.
        let s = watch(seconds: 60) { t in
            if t >= 30 && t < 31 { return nil }
            var r = rest(); r.eyeClosed = (t >= 29.9 && t < 30) || (t >= 40 && t < 40.2) ? 0.95 : 0.1; return r
        }.summary
        XCTAssertEqual(s.blinksPerMin ?? -1, 60.0 / 59, accuracy: 0.05, "one blink in fifty-nine seconds with a face")
    }

    func testBrokenNumbersAreNotAFace() {
        var a = FaceSignsAccumulator(rules: .arkit)
        a.add(at: 0, rest())
        var bad = rest(); bad.smile = .nan
        a.add(at: 0.1, bad)
        var worse = rest(); worse.head = .rotation(x: .infinity, y: 0, z: 0, w: 1)
        a.add(at: 0.2, worse)
        var zero = rest(); zero.head = .rotation(x: 0, y: 0, z: 0, w: 0)
        a.add(at: 0.3, zero)
        a.add(at: .nan, rest())            // a sample without a time is not a sample
        a.add(at: .infinity, rest())
        XCTAssertEqual(a.summary.samples, 4)
        XCTAssertEqual(a.summary.coverage, 0.25)
        for v in [a.summary.durationS, a.summary.coverage, a.summary.smileShare ?? 0] { XCTAssertTrue(v.isFinite) }
        XCTAssertNil(FaceReading(smile: .nan).checked)
        XCTAssertNil(FaceReading(shape: [0.2, .nan]).checked)
        XCTAssertEqual(FaceReading(smile: 1.4, mouthOpen: -0.2).checked, FaceReading(smile: 1, mouthOpen: 0), "a strength is held to 0…1")
        XCTAssertNotNil(FaceReading().checked, "a face with nothing measured is still a face")
    }

    func testOneFrame() {
        var a = FaceSignsAccumulator(rules: .arkit)
        var r = rest(); r.smile = 0.8
        a.add(at: 12.5, r)
        let s = a.summary
        XCTAssertEqual(s.samples, 1); XCTAssertEqual(s.coverage, 1); XCTAssertEqual(s.durationS, 0)
        XCTAssertEqual(s.smileShare, 1); XCTAssertEqual(s.smiles, 0, "one frame is not half a second of smile")
        XCTAssertEqual(s.gazeOnShare, 1)
        XCTAssertNil(s.blinksPerMin); XCTAssertNil(s.headMovement); XCTAssertNil(s.expressionRange)
        var none = FaceSignsAccumulator(rules: .arkit)
        none.add(at: 1, nil)
        XCTAssertEqual(none.summary.coverage, 0)
        XCTAssertNil(none.summary.smileShare); XCTAssertNil(none.summary.smiles); XCTAssertNil(none.summary.gazeOnShare)
        XCTAssertEqual(FaceSignsAccumulator(rules: .arkit).summary.samples, 0)
    }

    func testTimeThatWasNotSampledIsNotCounted() {
        // Ten seconds, the app away for five minutes, ten more seconds.
        let first = watch(seconds: 11) { _ in rest() }
        let s = watch(seconds: 11, from: 311, into: first) { _ in rest() }.summary
        XCTAssertEqual(s.durationS, 22, accuracy: 0.001)
        XCTAssertEqual(s.blinksPerMin, 0, "twenty-two seconds with a face, in two pieces: enough for a rate")
        // Samples out of order or twice at one time are dropped, not counted backwards.
        var a = FaceSignsAccumulator(rules: .arkit)
        a.add(at: 1, rest()); a.add(at: 1, rest()); a.add(at: 0.5, rest()); a.add(at: 1.1, rest())
        XCTAssertEqual(a.summary.samples, 2)
        XCTAssertEqual(a.summary.durationS, 0.1, accuracy: 1e-9)
    }

    func testHeadMovementIsDegreesASecondForARotation() {
        // Turning about the vertical axis at 10° a second for 20 s.
        let turning = watch(seconds: 20) { t in
            var r = rest(); let half = t * 10 * .pi / 180 / 2
            r.head = .rotation(x: 0, y: sin(half), z: 0, w: cos(half)); return r
        }.summary
        XCTAssertEqual(turning.headMovement ?? -1, 10, accuracy: 0.05)
        // q and −q are the same orientation; a quaternion of another length too.
        XCTAssertEqual(HeadPose.distance(.rotation(x: 0, y: 0, z: 0, w: 1), .rotation(x: 0, y: 0, z: 0, w: -1)) ?? -1, 0, accuracy: 1e-6)
        XCTAssertEqual(HeadPose.distance(.rotation(x: 0, y: 0, z: 0, w: 2), .rotation(x: 0, y: 2, z: 0, w: 0)) ?? -1, 180, accuracy: 1e-6)
        XCTAssertNil(HeadPose.distance(.rotation(x: 0, y: 0, z: 0, w: 1), .place(x: 0, y: 0, width: 1)), "two methods' poses do not compare")
        // A tracker's jitter of a few hundredths of a degree a frame stays small because poses are compared 0.2 s apart.
        let jitter = watch(seconds: 20) { t in
            var r = rest(); let half = (Int((t * 30).rounded()) % 2 == 0 ? 0.05 : -0.05) * .pi / 180 / 2
            r.head = .rotation(x: sin(half), y: 0, z: 0, w: cos(half)); return r
        }.summary
        XCTAssertLessThan(jitter.headMovement ?? 99, 0.6)
        XCTAssertNil(watch(seconds: 1.5) { _ in rest() }.summary.headMovement, "under two seconds followed: no number")
    }

    func testHeadMovementIsFaceWidthsASecondForAPlace() {
        // The face box slides 50 px a second and is 200 px wide: a quarter of a face width a second.
        let s = watch(.vision, seconds: 20, hz: 15) { t in var r = rest(.vision); r.head = .place(x: 100 + 50 * t, y: 240, width: 200); return r }.summary
        XCTAssertEqual(s.headMovement ?? -1, 0.25, accuracy: 0.002)
        // The same slide twice as near the camera (twice the pixels, twice the width) is the same number.
        let near = watch(.vision, seconds: 20, hz: 15) { t in var r = rest(.vision); r.head = .place(x: 200 + 100 * t, y: 480, width: 400); return r }.summary
        XCTAssertEqual(near.headMovement ?? -1, 0.25, accuracy: 0.002)
    }

    func testVisionLeavesSmileBrowsAndGazeOut() {
        let blinks = stride(from: 3.0, to: 60.0, by: 5.0).map { ($0, 0.2) }
        let s = watch(.vision, seconds: 60, hz: 15) { t in
            var r = rest(.vision)
            r.eyeClosed = within(t, blinks) ? 0.8 : 0.02
            r.mouthOpen = within(t, [(10, 6.0)]) ? 0.3 : 0.03
            return r
        }.summary
        XCTAssertEqual(s.method, "vision_landmarks")
        XCTAssertNil(s.smileShare); XCTAssertNil(s.smiles); XCTAssertNil(s.browRaiseShare); XCTAssertNil(s.browFurrowShare); XCTAssertNil(s.gazeOnShare)
        XCTAssertEqual(s.blinksPerMin ?? -1, 12, accuracy: 0.01)
        XCTAssertEqual(s.mouthOpenShare ?? -1, 0.1, accuracy: 0.01)
        XCTAssertNotNil(s.headMovement); XCTAssertNotNil(s.expressionRange)
        // Even handed a smile value, a method without a level for it reports no smile.
        let handed = watch(.vision, seconds: 5, hz: 15) { _ in var r = rest(.vision); r.smile = 0.9; return r }.summary
        XCTAssertNil(handed.smileShare); XCTAssertNil(handed.smiles)
        XCTAssertNil(FaceSignRules.vision.smile); XCTAssertNil(FaceSignRules.vision.browRaise); XCTAssertNil(FaceSignRules.vision.browFurrow)
    }

    func testRangeOfExpression() {
        // Every channel flipping between nothing and everything is the widest a face can go.
        let wide = watch(seconds: 10) { t in
            let on = Int((t * 30).rounded()) % 2 == 0
            return FaceReading(smile: on ? 1 : 0, browRaise: on ? 1 : 0, browFurrow: on ? 1 : 0, eyeClosed: 0.1, mouthOpen: on ? 1 : 0)
        }.summary
        XCTAssertEqual(wide.expressionRange ?? -1, 1, accuracy: 0.01)
        // One channel of four moving a little.
        let little = watch(seconds: 10) { t in var r = rest(); r.mouthOpen = Int((t * 30).rounded()) % 2 == 0 ? 0.1 : 0.2; return r }.summary
        XCTAssertEqual(little.expressionRange ?? -1, 2 * 0.05 / 4, accuracy: 0.002)
        // Too few frames to speak of a range.
        XCTAssertNil(watch(seconds: 0.2) { _ in rest() }.summary.expressionRange)
        // Vision's extra shape numbers count toward it; a frame that lacks them is passed over, not a zero.
        let shaped = watch(.vision, seconds: 10, hz: 15) { t in
            var r = rest(.vision); r.shape = Int((t * 15).rounded()) % 5 == 0 ? [] : [Int((t * 15).rounded()) % 2 == 0 ? 0.4 : 0.5, 0.33]; return r
        }.summary
        XCTAssertGreaterThan(shaped.expressionRange ?? 0, 0.02)
    }

    func testGazeTowardTheScreenIsACone() {
        func at(_ degrees: Double) -> Bool? {
            FaceSignLimits.gazeOn(direction: (sin(degrees * .pi / 180), 0, cos(degrees * .pi / 180)), toCamera: (0, 0, 3))
        }
        XCTAssertEqual(at(0), true); XCTAssertEqual(at(24), true); XCTAssertEqual(at(26), false); XCTAssertEqual(at(180), false)
        XCTAssertNil(FaceSignLimits.gazeOn(direction: (0, 0, 0), toCamera: (0, 0, 1)), "no direction, no answer")
        XCTAssertNil(FaceSignLimits.gazeOn(direction: (.nan, 0, 1), toCamera: (0, 0, 1)))
        let s = watch(seconds: 20) { t in var r = rest(); r.gazeOn = t < 15; return r }.summary
        XCTAssertEqual(s.gazeOnShare ?? -1, 0.75, accuracy: 0.01)
    }

    func testTheLightestCameraFormatIsChosen() {
        XCTAssertEqual(FaceSignLimits.lightest([(fps: 60, pixels: 1440 * 1080, format: "a"), (fps: 60, pixels: 640 * 480, format: "b"),
                                                (fps: 30, pixels: 1280 * 720, format: "c")]), "c")
        XCTAssertEqual(FaceSignLimits.lightest([(fps: 60, pixels: 1440 * 1080, format: "a"), (fps: 60, pixels: 640 * 480, format: "b")]), "b")
        XCTAssertNil(FaceSignLimits.lightest([(fps: Int, pixels: Int, format: String)]()))
    }

    func testEveryLevelLeavesRoomBetweenOnAndOff() {
        for rules in [FaceSignRules.arkit, .vision] {
            for level in [rules.smile, rules.browRaise, rules.browFurrow, rules.mouthOpen, rules.eyeClosed].compactMap({ $0 }) {
                XCTAssertGreaterThan(level.on, level.off); XCTAssertGreaterThan(level.off, 0); XCTAssertLessThan(level.on, 1)
            }
        }
        XCTAssertEqual(Set([FaceSignRules.arkit.method, FaceSignRules.vision.method]), ["arkit_blendshapes", "vision_landmarks"])
    }
}

// MARK: - landmark geometry (the Vision path's arithmetic, on drawn shapes)

final class FaceGeometryTests: XCTestCase {
    /// A six-point eye contour `width` wide and `opening` × width tall, turned by `degrees` about `centre`.
    private func eye(width: Double = 40, opening: Double, degrees: Double = 0, centre: CGPoint = CGPoint(x: 200, y: 300)) -> [CGPoint] {
        let h = width * opening / 2
        let flat: [(Double, Double)] = [(-width / 2, 0), (-width / 6, h), (width / 6, h), (width / 2, 0), (width / 6, -h), (-width / 6, -h)]
        return turn(flat, degrees, centre)
    }

    private func turn(_ points: [(Double, Double)], _ degrees: Double, _ centre: CGPoint) -> [CGPoint] {
        let a = degrees * .pi / 180
        return points.map { CGPoint(x: Double(centre.x) + $0.0 * cos(a) - $0.1 * sin(a), y: Double(centre.y) + $0.0 * sin(a) + $0.1 * cos(a)) }
    }

    /// Outer and inner lip contours: `width` wide, the lips `gap` × width apart, the outer lips `lip` thick.
    private func mouth(width: Double = 60, gap: Double, lip: Double = 6, degrees: Double = 0) -> (inner: [CGPoint], outer: [CGPoint]) {
        let g = width * gap / 2, c = CGPoint(x: 220, y: 180), w = width / 2
        let inner: [(Double, Double)] = [(-w * 0.8, 0), (-w * 0.3, g), (w * 0.3, g), (w * 0.8, 0), (w * 0.3, -g), (-w * 0.3, -g)]
        let outer: [(Double, Double)] = [(-w, 0), (-w * 0.4, g + lip), (w * 0.4, g + lip), (w, 0), (w * 0.4, -g - lip), (-w * 0.4, -g - lip)]
        return (turn(inner, degrees, c), turn(outer, degrees, c))
    }

    /// The line through two eyes of a head tilted by `degrees`.
    private func eyeLine(degrees: Double = 0) -> FaceGeometry.Axis {
        let ends = turn([(-40, 0), (40, 0)], degrees, CGPoint(x: 220, y: 300))
        return FaceGeometry.line(from: ends[0], to: ends[1])!
    }

    func testAnEyesOpeningIsItsHeightOverItsWidthHoweverTheHeadIsTilted() {
        for degrees in [0.0, 20, 45, 90, 137, -30] {
            XCTAssertEqual(FaceGeometry.eyeOpening(eye(opening: 0.33, degrees: degrees)) ?? -1, 0.33, accuracy: 1e-6, "\(degrees)°")
            XCTAssertEqual(FaceGeometry.eyeOpening(eye(opening: 0.05, degrees: degrees)) ?? -1, 0.05, accuracy: 1e-6, "\(degrees)°")
        }
        // Nearer to the camera or farther: the same eye.
        XCTAssertEqual(FaceGeometry.eyeOpening(eye(width: 12, opening: 0.3)) ?? -1, FaceGeometry.eyeOpening(eye(width: 120, opening: 0.3)) ?? -2, accuracy: 1e-9)
        // The box around a tilted eye would have said something else (why the measure follows the eye's own axis).
        let tilted = eye(opening: 0.05, degrees: 45)
        let box = (tilted.map(\.y).max()! - tilted.map(\.y).min()!) / (tilted.map(\.x).max()! - tilted.map(\.x).min()!)
        XCTAssertGreaterThan(Double(box), 0.5)
        XCTAssertNil(FaceGeometry.eyeOpening([CGPoint(x: 1, y: 1), CGPoint(x: 2, y: 2)]), "two points are not a contour")
        XCTAssertNil(FaceGeometry.eyeOpening([CGPoint(x: 1, y: 1), CGPoint(x: 1, y: 1), CGPoint(x: 1, y: 1)]))
        XCTAssertNil(FaceGeometry.eyeOpening([CGPoint(x: 1, y: 1), CGPoint(x: CGFloat.nan, y: 1), CGPoint(x: 3, y: 1)]))
    }

    func testTheMouthsOpeningIsTheGapBetweenTheLips() {
        for degrees in [0.0, 30, 90, -140] {
            let shut = mouth(gap: 0.02, degrees: degrees), open = mouth(gap: 0.35, degrees: degrees), eyes = eyeLine(degrees: degrees)
            XCTAssertEqual(FaceGeometry.mouthOpening(inner: shut.inner, outer: shut.outer, eyeLine: eyes) ?? -1, 0.02, accuracy: 1e-6)
            XCTAssertEqual(FaceGeometry.mouthOpening(inner: open.inner, outer: open.outer, eyeLine: eyes) ?? -1, 0.35, accuracy: 1e-6)
            XCTAssertEqual(FaceGeometry.mouthWidth(outer: open.outer, eyeLine: eyes) ?? -1, 60, accuracy: 1e-6)
        }
        // Thick lips or a wide closed mouth are not an open mouth: only the gap counts.
        let full = mouth(width: 90, gap: 0.02, lip: 14)
        XCTAssertEqual(FaceGeometry.mouthOpening(inner: full.inner, outer: full.outer, eyeLine: eyeLine()) ?? -1, 0.02, accuracy: 1e-6)
        // A mouth open into an "O" is taller than it is wide: its own farthest points are no longer its corners
        // (which is why the mouth is measured against the line of the eyes).
        let o = mouth(gap: 0.9)
        XCTAssertEqual(FaceGeometry.mouthOpening(inner: o.inner, outer: o.outer, eyeLine: eyeLine()) ?? -1, 0.9, accuracy: 1e-6)
        XCTAssertNotEqual(FaceGeometry.axis(o.outer)?.length ?? 0, 60, accuracy: 1)
        XCTAssertNil(FaceGeometry.line(from: CGPoint(x: 1, y: 1), to: CGPoint(x: 1, y: 1)))
        XCTAssertNil(FaceGeometry.line(from: nil, to: CGPoint(x: 1, y: 1)))
        let level = FaceSignRules.vision.mouthOpen!
        XCTAssertLessThan(0.02, level.off); XCTAssertGreaterThan(0.35, level.on)
    }

    func testAnEyeIsClosedAgainstItsOwnOpenLevel() {
        // Two people's eyes (0.34 and 0.22 open): each one's blink reads as closed, neither's open eye does.
        for usual in [0.34, 0.22] {
            var level = OpenEyeLevel()
            var open: [Double] = [], shut: [Double] = []
            for i in 0..<300 {                       // 20 s at 15 looks a second, a 0.2 s blink every 4 s
                let blinking = i % 60 >= 30 && i % 60 < 33
                let c = level.closedness(of: blinking ? usual * 0.25 : usual)!
                if blinking { shut.append(c) } else { open.append(c) }
            }
            XCTAssertGreaterThan(shut.min()!, FaceSignRules.vision.eyeClosed!.on, "usual \(usual)")
            XCTAssertLessThan(open.max()!, FaceSignRules.vision.eyeClosed!.off, "usual \(usual): the level does not sink with a blink")
            XCTAssertEqual(level.level ?? 0, usual, accuracy: usual * 0.08)
        }
        // Eyes narrowing slowly and staying there (looking down at a keyboard) become the new usual, not "closed".
        var slow = OpenEyeLevel(), last = 0.0
        for i in 0..<900 { last = slow.closedness(of: i < 150 ? 0.32 : 0.22)! }
        XCTAssertLessThan(last, FaceSignRules.vision.eyeClosed!.off)
        // An eye too flat in the picture to tell (a face turned far away) gives no answer rather than "closed".
        var flat = OpenEyeLevel()
        XCTAssertNil(flat.closedness(of: 0.03)); XCTAssertNil(flat.closedness(of: .nan)); XCTAssertNil(flat.closedness(of: -1))
    }

    /// The whole Vision arithmetic on a drawn face: contours → openings → closedness → the summary.
    func testADrawnFaceBlinkingAndOpeningItsMouthComesOutAsTheRightNumbers() {
        var left = OpenEyeLevel(), right = OpenEyeLevel()
        var a = FaceSignsAccumulator(rules: .vision)
        for i in 0...(60 * 15) {
            let t = Double(i) / 15
            let blinking = i % 75 >= 40 && i % 75 < 43            // 0.2 s every 5 s: 12 a minute
            let talking = t >= 20 && t < 32                        // mouth open for 12 of 60 s
            let l = eye(opening: blinking ? 0.07 : 0.3, degrees: 8), r = eye(opening: blinking ? 0.06 : 0.28, degrees: 8, centre: CGPoint(x: 280, y: 311))
            let m = mouth(gap: talking ? 0.3 : 0.02, degrees: 8)
            let lo = FaceGeometry.eyeOpening(l)!, ro = FaceGeometry.eyeOpening(r)!
            let cl = left.closedness(of: lo), cr = right.closedness(of: ro)
            let eyes = FaceGeometry.line(from: FaceGeometry.centre(l), to: FaceGeometry.centre(r))!
            a.add(at: t, FaceReading(eyeClosed: cl.flatMap { x in cr.map { min(x, $0) } },
                                     mouthOpen: FaceGeometry.mouthOpening(inner: m.inner, outer: m.outer, eyeLine: eyes),
                                     head: .place(x: 240, y: 300, width: 180)))
        }
        let s = a.summary
        XCTAssertEqual(s.blinksPerMin ?? -1, 12, accuracy: 0.01)
        XCTAssertEqual(s.mouthOpenShare ?? -1, 0.2, accuracy: 0.01)
        XCTAssertEqual(s.headMovement ?? -1, 0, accuracy: 1e-9)
        XCTAssertNil(s.smileShare)
    }
}

// MARK: - the controller on a stand-in camera

/// A stand-in for the camera: it opens nothing and hands on whatever a test gives it. A test double.
final class FakeFaceSource: TaskCameraSource, @unchecked Sendable {
    let rules: FaceSignRules
    var simulated = false
    var ready = true
    private(set) var starts = 0, stops = 0
    private(set) var sample: (@Sendable (TaskCameraSample) -> Void)?
    private(set) var failed: (@Sendable () -> Void)?
    var clock = 0.0
    var running: Bool { starts > stops && sample != nil }

    init(rules: FaceSignRules = .arkit) { self.rules = rules }
    func start(sample: @escaping @Sendable (TaskCameraSample) -> Void, failed: @escaping @Sendable () -> Void) async -> Bool {
        starts += 1; self.sample = sample; self.failed = failed; return ready
    }
    func stop() { stops += 1 }

    /// `seconds` of made-up readings at `hz`, with the older geometry on every sample that is 0.2 s on.
    func feed(seconds: Double, hz: Double = 30, _ make: (Double) -> FaceReading? = { _ in rest() }) {
        let n = Int((seconds * hz).rounded())
        var lastGeometry = -Double.infinity
        for _ in 0..<n {
            clock += 1 / hz
            var s = TaskCameraSample(t: clock, face: make(clock))
            if clock - lastGeometry >= 0.2 - 0.004 {
                lastGeometry = clock
                s.geometry = s.face == nil ? .missing : .face(TaskFaceFrame(centerX: 0.5, centerY: 0.5, mouthAspect: 0.2 + 0.1 * sin(clock), eyeAspect: 0.25))
            }
            sample?(s)
        }
    }
}

@MainActor final class TaskCameraControllerTests: XCTestCase {
    private func settle() async { try? await Task.sleep(nanoseconds: 60_000_000) }

    func testWithTheChoiceOffNothingIsAskedOpenedOrKept() async {
        let source = FakeFaceSource()
        var asked = false
        let camera = TaskCamera(source: source, permission: { asked = true; return true })
        await camera.begin(allowed: false)
        XCTAssertFalse(asked); XCTAssertEqual(source.starts, 0); XCTAssertEqual(camera.state, .off)
        source.feed(seconds: 1)
        XCTAssertNil(camera.finish())
    }

    func testWithoutPermissionTheTaskGoesOnWithoutTheCamera() async {
        let source = FakeFaceSource()
        let camera = TaskCamera(source: source, permission: { false })
        await camera.begin(allowed: true)
        XCTAssertEqual(camera.state, .unavailable); XCTAssertEqual(source.starts, 0); XCTAssertNil(camera.finish())
        XCTAssertEqual(camera.state, .off)
        // A camera that cannot start (no camera, a closed lid) is the same calm state.
        let broken = FakeFaceSource(); broken.ready = false
        let second = TaskCamera(source: broken, permission: { true })
        await second.begin(allowed: true)
        XCTAssertEqual(second.state, .unavailable)
        broken.feed(seconds: 1)
        XCTAssertNil(second.finish())
    }

    func testAPermissionAnsweredAfterTheTaskWasLeftCannotOpenTheCamera() async {
        let source = FakeFaceSource()
        var answer: CheckedContinuation<Bool, Never>?
        let camera = TaskCamera(source: source, permission: { await withCheckedContinuation { answer = $0 } })
        let starting = Task { await camera.begin(allowed: true) }
        while answer == nil { await Task.yield() }
        XCTAssertEqual(camera.state, .requesting)
        camera.cancel(); answer?.resume(returning: true)
        await starting.value
        XCTAssertEqual(source.starts, 0); XCTAssertEqual(camera.state, .off)
    }

    func testItSamplesFromBeginToFinishAndNoLonger() async {
        let source = FakeFaceSource()
        let camera = TaskCamera(source: source, permission: { true })
        await camera.begin(allowed: true)
        XCTAssertEqual(camera.state, .capturing); XCTAssertEqual(source.starts, 1)
        source.feed(seconds: 30) { t in var r = rest(); r.smile = t >= 10 && t < 12 ? 0.7 : 0.05; return r }
        let seen = camera.finish()
        XCTAssertEqual(camera.state, .off); XCTAssertGreaterThanOrEqual(source.stops, 1)
        XCTAssertEqual(seen?.signs.samples, 900)
        XCTAssertEqual(seen?.signs.smiles, 1)
        XCTAssertEqual(seen?.signs.method, "arkit_blendshapes")
        XCTAssertEqual(seen?.geometry?.samples, 150, "the older two numbers keep their five looks a second")
        XCTAssertEqual(seen?.simulated, false)
        source.feed(seconds: 5)                      // a frame that arrives after the end is nobody's
        XCTAssertNil(camera.finish())
        await camera.begin(allowed: true)            // the next task starts from nothing
        source.feed(seconds: 1)
        XCTAssertEqual(camera.finish()?.signs.samples, 30)
    }

    func testHerTapTurnsItOffForThisTaskAndThrowsAwayWhatItHad() async {
        let source = FakeFaceSource()
        let camera = TaskCamera(source: source, permission: { true })
        await camera.begin(allowed: true)
        source.feed(seconds: 10)
        let stopsBefore = source.stops
        camera.stopForThisTask()
        XCTAssertEqual(camera.state, .stopped); XCTAssertGreaterThan(source.stops, stopsBefore)
        source.feed(seconds: 10)
        await camera.resume()                        // coming back to the front does not turn it on again
        XCTAssertEqual(camera.state, .stopped); XCTAssertEqual(source.starts, 1)
        XCTAssertNil(camera.finish(), "nothing of a task she turned it off in is sent")
    }

    func testOutOfTheFrontItClosesAndComesBackWithTheNumbersItHad() async {
        let source = FakeFaceSource()
        let camera = TaskCamera(source: source, permission: { true })
        await camera.begin(allowed: true)
        source.feed(seconds: 10)
        camera.suspend()                             // the lock button, another app, the display asleep
        XCTAssertEqual(camera.state, .suspended); XCTAssertEqual(source.stops, 2, "closed at once (once by begin's reset, once now)")
        source.feed(seconds: 60)                     // whatever still arrives is dropped
        source.clock += 300
        await camera.resume()
        XCTAssertEqual(camera.state, .capturing); XCTAssertEqual(source.starts, 2)
        source.feed(seconds: 10)
        let seen = camera.finish()
        XCTAssertEqual(seen?.signs.samples, 600)
        XCTAssertEqual(seen?.signs.durationS ?? 0, 20, accuracy: 0.1, "the time away was not sampled")
        // Asked for the camera while the system's question was still up: it opens only when the screen is back.
        var answer: CheckedContinuation<Bool, Never>?
        let asking = TaskCamera(source: FakeFaceSource(), permission: { await withCheckedContinuation { answer = $0 } })
        let first = Task { await asking.begin(allowed: true) }
        while answer == nil { await Task.yield() }
        asking.suspend(); XCTAssertEqual(asking.state, .suspended)
        let waiting = answer; answer = nil
        let second = Task { await asking.resume() }
        while answer == nil { await Task.yield() }
        waiting?.resume(returning: true); answer?.resume(returning: true)
        await first.value; await second.value
        XCTAssertEqual(asking.state, .capturing)
    }

    func testACameraTakenAwayLeavesTheTaskGoingAndKeepsWhatWasSampled() async {
        let source = FakeFaceSource()
        let camera = TaskCamera(source: source, permission: { true })
        await camera.begin(allowed: true)
        source.feed(seconds: 5)
        source.failed?()                             // another app took the camera, the lid closed
        await settle()
        XCTAssertEqual(camera.state, .unavailable)
        source.feed(seconds: 5)
        XCTAssertEqual(camera.finish()?.signs.samples, 150)
        // A failure reported by a camera that was already closed changes nothing.
        await camera.begin(allowed: true)
        let stale = source.failed
        camera.cancel(); stale?(); await settle()
        XCTAssertEqual(camera.state, .off)
    }

    func testNeverBesideAWalkOrACallThatIsNotATask() async {
        let source = FakeFaceSource()
        let camera = TaskCamera(source: source, permission: { true })
        var busy = true
        camera.blocked = { busy }
        await camera.begin(allowed: true)
        XCTAssertEqual(camera.state, .unavailable); XCTAssertEqual(source.starts, 0)
        // A call that begins in the middle of a game closes the camera within one check.
        let every = TaskCamera.watchEvery
        TaskCamera.watchEvery = 0.02
        defer { TaskCamera.watchEvery = every }
        busy = false
        await camera.begin(allowed: true)
        XCTAssertEqual(camera.state, .capturing)
        source.feed(seconds: 2)
        busy = true
        try? await Task.sleep(nanoseconds: 200_000_000)
        XCTAssertEqual(camera.state, .unavailable)
        XCTAssertFalse(source.running)
    }

    func testAStandInsNumbersAreMarkedAsSuch() async {
        let source = FakeFaceSource(rules: .vision); source.simulated = true
        let camera = TaskCamera(source: source, permission: { true })
        await camera.begin(allowed: true)
        source.feed(seconds: 2, hz: 15) { _ in rest(.vision) }
        XCTAssertEqual(camera.finish()?.simulated, true)
    }
}

// MARK: - the flow: choice → camera → observations → receipt (stubbed service)

/// A service stand-in. It keeps what was posted, and can play a service that does not know `obs.face_signs` yet.
final class FaceSignsHTTP: URLProtocol {
    enum Unknown { case known, namedInRejected, wholeBatchRefused }
    static let lock = NSLock()
    nonisolated(unsafe) static var offline = false
    nonisolated(unsafe) static var unknown = Unknown.known
    nonisolated(unsafe) static var posted: [[String: Any]] = []
    nonisolated(unsafe) static var posts = 0
    static func reset() { lock.lock(); offline = false; unknown = .known; posted = []; posts = 0; lock.unlock() }
    static var accepted: [[String: Any]] { lock.lock(); defer { lock.unlock() }; return posted }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var data = request.httpBody ?? Data()
        if let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(buffer, count: n) }
        }
        let path = request.url!.path
        Self.lock.lock()
        let offline = Self.offline, unknown = Self.unknown
        var status = 200
        var json = #"{"events":[]}"#
        if path.hasSuffix("events"), request.httpMethod == "POST", !offline {
            Self.posts += 1
            let events = ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any])?["events"] as? [[String: Any]] ?? []
            let strange = events.filter { $0["type"] as? String == "obs.face_signs" }
            if unknown == .wholeBatchRefused, !strange.isEmpty {
                status = 422; json = #"{"detail":"unknown type"}"#
            } else {
                let kept = unknown == .namedInRejected ? events.filter { $0["type"] as? String != "obs.face_signs" } : events
                Self.posted += kept
                let rejected = unknown == .namedInRejected ? strange.map { ["id": $0["id"] ?? "", "error": "unknown type"] } : []
                json = String(decoding: try! JSONSerialization.data(withJSONObject: ["accepted": kept.count, "duplicates": 0, "rejected": rejected]), as: UTF8.self)
            }
        } else if path.hasSuffix("session") {
            json = #"{"session_id":"face-signs-check-in","model":"m","voice":"v","system_instruction":"s","tools":[],"context_card":{"time_of_day":"morning"},"persona_version":"p","safety_phrases_version":"s","chat_shape":{"purpose":"check_in","depth":"brief","open_items":[]},"live_token":{"token":"t","expires_at":"2099-01-01T00:00:00Z","new_session_expires_at":"2099-01-01T00:00:00Z"}}"#
        } else if path.hasSuffix("tool") {
            json = #"{"ok":true,"name":"end_session","result":{"ok":true}}"#
        } else if path.hasSuffix("episode") {
            json = #"{"ok":true,"id":"face-signs-check-in"}"#
        } else if path.hasSuffix("close") {
            json = #"{"ok":true}"#
        }
        Self.lock.unlock()
        if offline { client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet)); return }
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(json.utf8)); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

private final class LineAudio: ConversationAudioIO, @unchecked Sendable {
    var onPCM: ((Data) -> Void)?
    var onBuffer: ((AVAudioPCMBuffer) -> Void)?
    var onLevel: ((Float) -> Void)?
    var onPlaying: ((Bool) -> Void)?
    var onFailure: (() -> Void)?
    var isPlaying = false
    func start() throws {}
    func stop() {}
    func setMic(_ on: Bool) {}
    func setCapture(_ on: Bool) {}
    func play(_ pcm: Data) {}
    func flush() {}
}

private final class Line: ConversationTransport, @unchecked Sendable {
    var event: (@Sendable (LiveSession.Event) -> Void)?
    func connect(token: String, session: CompanionSessionResponse, options: LiveSession.Options) {}
    func close() {}
    func sendAudio(_ pcm: Data) {}
    func audioStreamEnd() {}
    func sendText(_ text: String) {}
    func sendContext(_ event: String) {}
    func respond(id: String, name: String, result: JSONValue) {}
}

@MainActor final class FaceSignsFlowTests: XCTestCase {
    private var grace: TimeInterval = 0
    private var dir = URL(fileURLWithPath: NSTemporaryDirectory())

    override func setUp() async throws {
        grace = Conversation.closeGrace
        Conversation.closeGrace = 0
        FaceSignsHTTP.reset()
        L10n.shared.language = .en
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("face-signs-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    override func tearDown() async throws {
        Conversation.closeGrace = grace
        try? FileManager.default.removeItem(at: dir)
    }

    private let pairing = Pairing(baseURL: URL(string: "https://face-signs.test")!, homeID: "synthetic", token: "synthetic-pairing-token")

    /// An app with the camera choice as asked for: `nil` = never turned on; otherwise the wording it was agreed under.
    private func makeApp(camera wording: Int? = CameraChoice.wording, defaults given: UserDefaults? = nil, paired: Bool = true) -> AppModel {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [FaceSignsHTTP.self]
        let api = APIClient(pairing: paired ? pairing : nil, maxAttempts: 1, session: URLSession(configuration: config))
        let defaults = given ?? UserDefaults(suiteName: UUID().uuidString)!
        defaults.set(true, forKey: "kaikuMute")
        if let wording, given == nil {
            defaults.set(["camera": true, "checkins": true], forKey: "kaiku.consents")
            if wording > 0 { defaults.set(wording, forKey: CameraChoice.wordingKey) }
        }
        return AppModel(defaults: defaults, pairing: paired ? pairing : nil, api: api, queue: OfflineQueue(url: dir.appendingPathComponent("events.json")),
                        episodes: EpisodeOutbox(url: dir.appendingPathComponent("episodes.json")))
    }

    private func settle() async { try? await Task.sleep(nanoseconds: 80_000_000) }

    private func lantern() -> PlaySession {
        var s = PlaySession(game: .firefly, device: KaikuPlatform.device, duration_s: 60)
        s.reaction_ms_median = 420; s.reaction_ms_iqr = 80; s.lapses = 1; s.false_taps = 0
        return s
    }

    /// What `GameShell` does around one round, without the view: begin at the start, finish at the end, record.
    private func play(_ app: AppModel, _ camera: TaskCamera, _ source: FakeFaceSource, seconds: Double = 60,
                      face make: @escaping (Double) -> FaceReading? = { _ in rest() }, during: () -> Void = {}) async {
        await camera.begin(allowed: app.cameraOn)
        source.feed(seconds: seconds, make)
        during()
        let seen = camera.finish()
        await app.recordPlay(lantern(), camera: seen)
    }

    // MARK: a game

    func testAGameWithTheCameraOnEndsWithOneGameRecordAndOneFaceSignsThatPointsAtIt() async throws {
        FaceSignsHTTP.offline = true                       // nothing leaves the queue: it can be read
        let app = makeApp(), source = FakeFaceSource(), camera = TaskCamera(source: source, permission: { true })
        XCTAssertTrue(app.cameraOn)
        let blinks = stride(from: 2.0, to: 60.0, by: 4.0).map { ($0, 0.2) }
        await play(app, camera, source, face: { t in
            var r = rest(); r.eyeClosed = within(t, blinks) ? 0.95 : 0.1; r.smile = within(t, [(20, 3.0)]) ? 0.7 : 0.05; return r
        })
        XCTAssertFalse(source.running, "the camera closed when the game ended")
        let queued = await app.queue.pending
        XCTAssertEqual(queued.map(\.type), ["obs.play_session", "obs.face_signs"])
        let game = queued[0], signs = queued[1]
        XCTAssertEqual(signs.payload["ref"]?.string, game.id)
        XCTAssertEqual(signs.payload["task"]?.string, "firefly"); XCTAssertEqual(signs.payload["task"]?.string, game.payload["game"]?.string)
        XCTAssertEqual(signs.payload["device"]?.string, game.payload["device"]?.string)
        XCTAssertEqual(signs.payload["method"]?.string, "arkit_blendshapes")
        XCTAssertEqual(signs.payload["samples"]?.int, 1800)
        XCTAssertEqual(signs.payload["duration_s"]?.double ?? 0, 60, accuracy: 0.1)
        XCTAssertEqual(signs.payload["coverage"]?.double, 1); XCTAssertEqual(signs.quality, 1, "the envelope's quality is the coverage")
        XCTAssertEqual(signs.payload["smiles"]?.int, 1)
        XCTAssertEqual(signs.payload["smile_share"]?.double ?? 0, 0.05, accuracy: 0.002)
        XCTAssertEqual(signs.payload["blinks_per_min"]?.double ?? 0, 15, accuracy: 0.11)
        XCTAssertEqual(signs.payload["gaze_on_share"]?.double, 1)
        XCTAssertEqual(signs.sim, false); XCTAssertEqual(signs.source, KaikuPlatform.source.rawValue); XCTAssertEqual(signs.home_id, "synthetic")
        // The game's own record keeps its two older camera numbers, with their own method word.
        XCTAssertEqual(game.payload["camera_method"]?.string, "vision_landmarks")
        XCTAssertEqual(game.payload["camera_samples"]?.int, 300)
        XCTAssertNotNil(game.payload["expressivity_index"]); XCTAssertEqual(game.payload["reaction_ms_median"]?.double, 420)
        XCTAssertEqual(app.cameraChoice.sentToday().map(\.id), [signs.id]); XCTAssertEqual(app.cameraChoice.sentToday().first?.ref, game.id)
    }

    func testAFaceHalfOutOfThePictureLowersCoverageAndQuality() async {
        FaceSignsHTTP.offline = true
        let app = makeApp(), source = FakeFaceSource(), camera = TaskCamera(source: source, permission: { true })
        await play(app, camera, source, face: { t in t < 30 ? rest() : nil })
        let signs = await app.queue.pending.first { $0.type == "obs.face_signs" }
        XCTAssertEqual(signs?.payload["coverage"]?.double ?? 0, 0.5, accuracy: 0.002)
        XCTAssertEqual(signs?.quality ?? 0, 0.5, accuracy: 0.002)
    }

    func testWithTheChoiceOffNothingIsSampledAndNothingOfTheCameraIsSent() async {
        FaceSignsHTTP.offline = true
        let app = makeApp(camera: nil), source = FakeFaceSource()
        var asked = false
        let camera = TaskCamera(source: source, permission: { asked = true; return true })
        XCTAssertFalse(app.cameraOn)
        await play(app, camera, source)
        XCTAssertFalse(asked, "the system is not even asked for the camera"); XCTAssertEqual(source.starts, 0)
        let queued = await app.queue.pending
        XCTAssertEqual(queued.map(\.type), ["obs.play_session"])
        for key in ["camera_method", "camera_samples", "camera_face_coverage", "expressivity_index", "face_movement"] { XCTAssertNil(queued[0].payload[key], key) }
        XCTAssertTrue(app.cameraChoice.sentToday().isEmpty)
    }

    func testAChoiceSwitchedOffOrPausedDuringAGameSendsNothingOfTheCamera() async {
        FaceSignsHTTP.offline = true
        for stop in ["choice", "pause", "checkins"] {
            let app = makeApp(), source = FakeFaceSource(), camera = TaskCamera(source: source, permission: { true })
            await play(app, camera, source, during: {
                switch stop {
                case "choice": app.consents[.camera] = false
                case "pause": app.pausedAll = true
                default: app.consents[.checkins] = false
                }
            })
            let queued = await app.queue.pending
            XCTAssertFalse(queued.contains { $0.type == "obs.face_signs" }, stop)
            XCTAssertNil(queued.first { $0.type == "obs.play_session" }?.payload["camera_method"], stop)
            XCTAssertTrue(app.cameraChoice.sentToday().isEmpty, stop)
            await app.queue.clear()
        }
    }

    func testHerTapOnTheIndicatorStopsSamplingAndSendsNoFaceSigns() async {
        FaceSignsHTTP.offline = true
        let app = makeApp(), source = FakeFaceSource(), camera = TaskCamera(source: source, permission: { true })
        await camera.begin(allowed: app.cameraOn)
        source.feed(seconds: 20)
        camera.stopForThisTask()                           // the chip's tap
        XCTAssertFalse(source.running); XCTAssertEqual(camera.state, .stopped)
        source.feed(seconds: 20)
        await app.recordPlay(lantern(), camera: camera.finish())
        let queued = await app.queue.pending
        XCTAssertEqual(queued.map(\.type), ["obs.play_session"]); XCTAssertNil(queued[0].payload["camera_samples"])
        XCTAssertTrue(app.consents[.camera] == true, "off for this task only: the choice itself stays as it was")
    }

    func testAStandInCameraSendsEverythingAsSimulated() async {
        FaceSignsHTTP.offline = true
        let app = makeApp(), source = FakeFaceSource(rules: .vision), camera = TaskCamera(source: source, permission: { true })
        source.simulated = true
        await camera.begin(allowed: app.cameraOn)
        source.feed(seconds: 30, hz: 15) { _ in rest(.vision) }
        await app.recordPlay(lantern(), camera: camera.finish())
        let queued = await app.queue.pending
        XCTAssertEqual(queued.map(\.sim), [true, true], "the game's record carries made-up camera numbers too")
        XCTAssertEqual(queued[1].payload["method"]?.string, "vision_landmarks")
        XCTAssertNil(queued[1].payload["smile_share"]); XCTAssertNil(queued[1].payload["gaze_on_share"])
        XCTAssertEqual(app.cameraChoice.sentToday().first?.sim, true)
    }

    func testNotConnectedNothingIsNotedOrQueued() async {
        let app = makeApp(paired: false), source = FakeFaceSource(), camera = TaskCamera(source: source, permission: { true })
        app.consents[.camera] = true; app.cameraChoice.agree()
        await play(app, camera, source)
        let n = await app.queue.count
        XCTAssertEqual(n, 0); XCTAssertTrue(app.cameraChoice.sentToday().isEmpty, "a receipt never lists what was not sent")
    }

    // MARK: the payload

    func testThePayloadIsNumbersWithTheAgreedNamesAndNothingElse() throws {
        var a = FaceSignsAccumulator(rules: .arkit)
        for i in 0...3600 { let t = Double(i) / 30; var r = rest(); r.smile = t > 100 && t < 104 ? 0.7 : 0.05; a.add(at: t, r) }
        let full = try JSONSerialization.jsonObject(with: JSONEncoder().encode(
            FaceSigns(a.summary, task: "lantern", device: .phone, ref: "0193a3c0-0000-7000-8000-000000000000"))) as! [String: Any]
        let names: Set<String> = ["task", "device", "method", "duration_s", "samples", "coverage", "smile_share", "smiles", "brow_raise_share",
                                  "brow_furrow_share", "mouth_open_share", "blinks_per_min", "gaze_on_share", "head_movement", "expression_range", "ref"]
        XCTAssertEqual(Set(full.keys), names, "ARKit fills every field")
        for (key, value) in full where !["task", "device", "method", "ref"].contains(key) { XCTAssertTrue(value is NSNumber, key) }
        for key in ["coverage", "smile_share", "brow_raise_share", "brow_furrow_share", "mouth_open_share", "gaze_on_share", "expression_range"] {
            XCTAssertTrue((0...1).contains(full[key] as! Double), key)
        }
        // Vision leaves out what it does not measure, and a check-in has no game to point at: the keys are absent.
        var v = FaceSignsAccumulator(rules: .vision)
        for i in 0...450 { v.add(at: Double(i) / 15, rest(.vision)) }
        let thin = try JSONSerialization.jsonObject(with: JSONEncoder().encode(
            FaceSigns(v.summary, task: FaceSigns.checkIn, device: .mac, ref: nil))) as! [String: Any]
        XCTAssertEqual(Set(thin.keys), ["task", "device", "method", "duration_s", "samples", "coverage", "mouth_open_share", "blinks_per_min",
                                        "head_movement", "expression_range"])
        XCTAssertEqual(thin["task"] as? String, "check_in")
        // No word for a feeling and no picture can ride on it: the payload has no field to put one in.
        for key in names { for word in ["emotion", "mood", "happy", "sad", "image", "frame", "photo", "pixels", "identity"] { XCTAssertFalse(key.contains(word), key) } }
        // When the contract's schema is in the tree, the payload is checked against it as every other payload is.
        let schema = repoRoot.appendingPathComponent("contracts/schemas/obs/face_signs.schema.json")
        guard FileManager.default.fileExists(atPath: schema.path) else { return }
        let s = try JSONSerialization.jsonObject(with: Data(contentsOf: schema)) as! [String: Any]
        let d = (s["$defs"] as! [String: Any])["FaceSigns"] as! [String: Any]
        let properties = d["properties"] as! [String: Any], required = Set(d["required"] as? [String] ?? [])
        for body in [full, thin] {
            XCTAssertTrue(Set(body.keys).isSubset(of: Set(properties.keys)), "extra \(Set(body.keys).subtracting(properties.keys))")
            XCTAssertTrue(required.isSubset(of: Set(body.keys)), "missing \(required.subtracting(body.keys))")
        }
        if let methods = (properties["method"] as? [String: Any])?["enum"] as? [String] {
            XCTAssertTrue(Set([FaceSignRules.arkit.method, FaceSignRules.vision.method]).isSubset(of: Set(methods)))
        }
        if let tasks = (properties["task"] as? [String: Any])?["enum"] as? [String] {
            // photo_time is the robot's own task (its camera, device "robot"): in the contract, never sent by this app.
            XCTAssertEqual(Set(tasks).subtracting(["photo_time"]), Set(PlayGame.allCases.map(\.rawValue) + [FaceSigns.checkIn]),
                           "every task this app can send, and no other")
        }
        if let devices = (properties["device"] as? [String: Any])?["enum"] as? [String] {
            XCTAssertTrue(Set([PlayDevice.phone.rawValue, PlayDevice.mac.rawValue]).isSubset(of: Set(devices)))
        }
    }

    /// The contract refuses a record that claims signs without a usable face. A camera that saw a face in a frame
    /// or two out of thousands sends its coverage as nothing, and then no sign with it.
    func testNoFaceToSpeakOfMeansNoSigns() throws {
        var a = FaceSignsAccumulator(rules: .arkit)
        for i in 0..<6000 { var r = rest(); r.smile = 0.9; a.add(at: Double(i) / 30, i == 100 ? r : nil) }
        XCTAssertEqual(a.summary.smileShare, 1, "the one frame with a face was smiling")
        let body = try JSONSerialization.jsonObject(with: JSONEncoder().encode(FaceSigns(a.summary, task: "lantern", device: .phone, ref: nil))) as! [String: Any]
        XCTAssertEqual(body["coverage"] as? Double, 0)
        XCTAssertEqual(Set(body.keys), ["task", "device", "method", "duration_s", "samples", "coverage"])
        var none = FaceSignsAccumulator(rules: .vision)
        for i in 0..<300 { none.add(at: Double(i) / 15, nil) }
        let empty = try JSONSerialization.jsonObject(with: JSONEncoder().encode(FaceSigns(none.summary, task: "check_in", device: .mac, ref: nil))) as! [String: Any]
        XCTAssertEqual(Set(empty.keys), ["task", "device", "method", "duration_s", "samples", "coverage"])
        XCTAssertEqual(empty["samples"] as? Int, 300)
    }

    // MARK: the check-in

    private func checkIn(_ app: AppModel, _ source: FakeFaceSource, permission: Bool = true) -> (CheckInChat, Line) {
        let audio = LineAudio(), live = Line()
        let talk = TalkModel(opening: CheckInChat.opening) {
            Conversation(surface: .iphone, intent: .checkin, audio: audio, transport: { event in live.event = event; return live },
                         permission: { true }, localListener: false, purpose: .check_in, typedWithoutMic: true)
        }
        return (CheckInChat(talk: talk, camera: TaskCamera(source: source, permission: { permission })), live)
    }

    private func open(_ chat: CheckInChat, _ app: AppModel, _ live: Line) async {
        chat.talk.screenAppeared()
        await chat.start(app: app)
        live.event?(.ready); await settle()
        live.event?(.kaikuText("Oh, hello. How is today going?")); live.event?(.kaikuTranscriptComplete); live.event?(.turnComplete)
        await settle()
    }

    func testACheckInWithTheCameraOnSendsOneFaceSignsWhenItEnds() async {
        let app = makeApp(), source = FakeFaceSource()
        let (chat, live) = checkIn(app, source)
        await open(chat, app, live)
        XCTAssertEqual(chat.camera.state, .capturing, "the camera runs beside the check-in"); XCTAssertEqual(source.starts, 1)
        source.feed(seconds: 40) { t in var r = rest(); r.mouthOpen = t > 10 && t < 20 ? 0.4 : 0.02; return r }
        live.event?(.userText("Fine. A normal day.")); live.event?(.userTranscriptComplete); await settle()
        live.event?(.kaikuText("Good to see you. Take care.")); live.event?(.kaikuTranscriptComplete)
        live.event?(.toolCall(id: "1", name: "end_session", args: ["outcome": .string("completed")])); await settle()
        XCTAssertEqual(chat.state.end, .chat)
        XCTAssertEqual(chat.camera.state, .off); XCTAssertFalse(source.running, "an end screen has no camera behind it")
        await settle()
        let sent = FaceSignsHTTP.accepted.filter { $0["type"] as? String == "obs.face_signs" }
        XCTAssertEqual(sent.count, 1)
        let payload = sent[0]["payload"] as? [String: Any]
        XCTAssertEqual(payload?["task"] as? String, "check_in"); XCTAssertNil(payload?["ref"], "there is no game record to point at")
        XCTAssertEqual(payload?["samples"] as? Int, 1200)
        XCTAssertEqual(payload?["mouth_open_share"] as? Double ?? 0, 0.25, accuracy: 0.01)
        XCTAssertFalse(FaceSignsHTTP.accepted.contains { $0["type"] as? String == "obs.play_session" })
        XCTAssertEqual(app.cameraChoice.sentToday().count, 1)
        source.feed(seconds: 5); await settle()
        XCTAssertEqual(FaceSignsHTTP.accepted.filter { $0["type"] as? String == "obs.face_signs" }.count, 1)
    }

    func testTheDialsAloneCountAndSendTheirFaceSigns() async {
        let app = makeApp(), source = FakeFaceSource()
        let (chat, live) = checkIn(app, source)
        await open(chat, app, live)
        source.feed(seconds: 15)
        await chat.submitDials()
        await settle()
        XCTAssertFalse(source.running)
        let types = FaceSignsHTTP.accepted.compactMap { $0["type"] as? String }
        XCTAssertEqual(types.filter { $0 == "obs.self_report" }.count, 3); XCTAssertEqual(types.filter { $0 == "obs.face_signs" }.count, 1)
    }

    func testACheckInOnlyOpenedAndLeftSendsNothing() async {
        let app = makeApp(), source = FakeFaceSource()
        let (chat, live) = checkIn(app, source)
        await open(chat, app, live)
        source.feed(seconds: 10)
        chat.leave()                                        // she never said or dialled anything
        await settle()
        XCTAssertFalse(source.running); XCTAssertEqual(chat.camera.state, .off)
        XCTAssertFalse(FaceSignsHTTP.accepted.contains { $0["type"] as? String == "obs.face_signs" })
        XCTAssertTrue(app.cameraChoice.sentToday().isEmpty)
    }

    func testLeavingACheckInSheTookPartInSendsItsFaceSignsAndClosesTheCamera() async {
        let app = makeApp(), source = FakeFaceSource()
        let (chat, live) = checkIn(app, source)
        await open(chat, app, live)
        source.feed(seconds: 10)
        live.event?(.userText("A bit tired today.")); live.event?(.userTranscriptComplete); await settle()
        chat.leave(); await settle()
        XCTAssertFalse(source.running)
        XCTAssertEqual(FaceSignsHTTP.accepted.filter { $0["type"] as? String == "obs.face_signs" }.count, 1)
    }

    func testTurnedOffInTheCheckInItStaysOffAlsoWhenSheKeepsTalking() async {
        let app = makeApp(), source = FakeFaceSource()
        let (chat, live) = checkIn(app, source)
        await open(chat, app, live)
        source.feed(seconds: 10)
        chat.camera.stopForThisTask()                       // the chip's tap
        XCTAssertFalse(source.running)
        live.event?(.userText("Fine.")); live.event?(.userTranscriptComplete); await settle()
        chat.enough(); await settle()
        XCTAssertFalse(FaceSignsHTTP.accepted.contains { $0["type"] as? String == "obs.face_signs" })
        await chat.keepTalking(); await settle()
        XCTAssertEqual(source.starts, 1, "the same check-in: her off still holds"); XCTAssertNotEqual(chat.camera.state, .capturing)
    }

    func testWithTheChoiceOffTheCheckInOpensNoCameraAndSendsNoFaceSigns() async {
        let app = makeApp(camera: nil), source = FakeFaceSource()
        let (chat, live) = checkIn(app, source)
        await open(chat, app, live)
        XCTAssertEqual(source.starts, 0); XCTAssertEqual(chat.camera.state, .off)
        live.event?(.userText("Fine.")); live.event?(.userTranscriptComplete); await settle()
        chat.enough(); await settle()
        XCTAssertFalse(FaceSignsHTTP.accepted.contains { $0["type"] as? String == "obs.face_signs" })
        // Turned on in the middle of a check-in (the one-time question answered): it begins then.
        let (second, line) = checkIn(app, source)
        await open(second, app, line)
        app.consents[.camera] = true; app.cameraChoice.agree()
        await second.cameraChoiceChanged(on: app.cameraOn)
        XCTAssertEqual(second.camera.state, .capturing)
        app.pausedAll = true                                // "pause everything" closes it and keeps nothing
        await second.cameraChoiceChanged(on: app.cameraOn)
        XCTAssertEqual(second.camera.state, .off); XCTAssertFalse(source.running)
    }

    func testWithoutPermissionTheCheckInSimplyGoesOn() async {
        let app = makeApp(), source = FakeFaceSource()
        let (chat, live) = checkIn(app, source, permission: false)
        await open(chat, app, live)
        XCTAssertEqual(chat.camera.state, .unavailable); XCTAssertEqual(source.starts, 0)
        live.event?(.userText("Fine.")); live.event?(.userTranscriptComplete); await settle()
        chat.enough(); await settle()
        XCTAssertEqual(chat.state.end, .chat, "the check-in itself is untouched")
        XCTAssertFalse(FaceSignsHTTP.accepted.contains { $0["type"] as? String == "obs.face_signs" })
    }

    // MARK: the choice and its wording

    func testAChoiceMadeUnderTheOlderWordingIsAskedAgainBeforeTheCameraRuns() async {
        FaceSignsHTTP.offline = true
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        defaults.set(["camera": true, "checkins": true], forKey: "kaiku.consents")      // on, from a build before this one
        let app = makeApp(defaults: defaults), source = FakeFaceSource(), camera = TaskCamera(source: source, permission: { true })
        XCTAssertTrue(app.consents[.camera] == true); XCTAssertTrue(app.cameraNeedsConfirm); XCTAssertFalse(app.cameraOn)
        await play(app, camera, source)
        XCTAssertEqual(source.starts, 0, "not before she has seen what it now notices")
        let before = await app.queue.pending
        XCTAssertEqual(before.map(\.type), ["obs.play_session"]); XCTAssertNil(before[0].payload["camera_method"])
        app.confirmCamera(keep: true)                       // "Keep it on"
        XCTAssertFalse(app.cameraNeedsConfirm); XCTAssertTrue(app.cameraOn)
        XCTAssertTrue(makeApp(defaults: defaults).cameraOn, "asked once: the answer is kept")
        await play(app, camera, source)
        let n = await app.queue.pending.filter { $0.type == "obs.face_signs" }.count
        XCTAssertEqual(n, 1)
        // "Turn it off" is the switch itself.
        let other = UserDefaults(suiteName: UUID().uuidString)!
        other.set(["camera": true, "checkins": true], forKey: "kaiku.consents")
        let second = makeApp(defaults: other)
        second.confirmCamera(keep: false)
        XCTAssertEqual(second.consents[.camera], false); XCTAssertFalse(second.cameraNeedsConfirm); XCTAssertFalse(second.cameraOn)
    }

    func testOnlyASwitchBesideTheWholeTextIsAgreement() {
        // A game's start screen and the day's receipt show the short line: turned on there, she is still shown the whole text once.
        let short = makeApp(camera: nil)
        short.consents[.camera] = true
        XCTAssertTrue(short.cameraNeedsConfirm); XCTAssertFalse(short.cameraOn)
        // Setup's "Your choices" and You → Sharing show the whole text: that switch is the agreement.
        let whole = makeApp(camera: nil)
        whole.choiceBinding(.camera).wrappedValue = true
        XCTAssertFalse(whole.cameraNeedsConfirm); XCTAssertTrue(whole.cameraOn)
        whole.choiceBinding(.camera).wrappedValue = false
        XCTAssertFalse(whole.cameraOn)
        whole.choiceBinding(.voice).wrappedValue = true
        XCTAssertEqual(whole.consents[.voice], true); XCTAssertEqual(whole.consents[.camera], false, "another switch is only itself")
        XCTAssertFalse(Signal.camera.defaultOn)
    }

    func testTheWordsSayExactlyWhatIsDerived() {
        for lang in [KaikuLanguage.en, .fi] {
            let text = L10n.shared.string("sig.camera.d", lang: lang).lowercased()
            for part in ["smiles", "eyebrow", "mouth", "blinks", "toward the screen", "head", "numbers", "this device", "no pictures are kept or sent", "does not label emotions"] {
                XCTAssertTrue(text.contains(part), "\(lang): \(part)")
            }
            XCTAssertFalse(text.contains("geometry"), "the older wording is gone in \(lang)")
            XCTAssertLessThanOrEqual(L10n.shared.string("sig.camera.s", lang: lang).count, 70)
        }
        XCTAssertEqual(T("task.camera.active"), "Camera on: face movement only")
        for key in ["task.camera.active.short", "task.camera.active.a11y", "task.camera.off", "task.camera.off.hint", "task.camera.stopped",
                    "task.camera.keepoff", "task.camera.keepoff.hint", "task.camera.keptoff", "task.camera.unavailable", "task.camera.optin",
                    "camera.confirm.t", "camera.confirm.keep", "camera.confirm.off", "evidence.camera", "evidence.camera.n",
                    "evidence.camera.note", "saw.camera.n", "saw.camera.none"] {
            XCTAssertTrue(L10n.shared.has(key, .en) && L10n.shared.has(key, .fi), key)
            // Nothing the camera says names a feeling or alarms.
            for word in ["happy", "sad", "angry", "mood", "recording", "watching you", "error", "failed", "denied"] {
                XCTAssertFalse(T(key).lowercased().contains(word), "\(key): \(word)")
            }
        }
    }

    // MARK: the receipt

    private func event(_ type: String, source: String = "phone", id: String = UUID().uuidString, payload: [String: JSONValue] = [:], sim: Bool = false) -> AnyEnvelope {
        let p = String(decoding: try! JSONEncoder().encode(JSONValue.object(payload)), as: UTF8.self)
        let json = "{\"v\":1,\"id\":\"\(id)\",\"ts\":\"2026-11-14T10:00:00.000Z\",\"home_id\":\"synthetic\",\"source\":\"\(source)\",\"type\":\"\(type)\",\"payload\":\(p),\"sim\":\(sim)}"
        return try! JSONDecoder().decode(AnyEnvelope.self, from: Data(json.utf8))
    }

    func testTheDaysReceiptListsTheCameraTruthfullyBeforeTheServiceKnowsTheType() async {
        // The service takes the game records and refuses the type it does not know: the device's own list still says what it sent.
        FaceSignsHTTP.unknown = .namedInRejected
        let app = makeApp(), source = FakeFaceSource(), camera = TaskCamera(source: source, permission: { true })
        for _ in 0..<3 { await play(app, camera, source, seconds: 5) }
        XCTAssertEqual(FaceSignsHTTP.accepted.filter { $0["type"] as? String == "obs.play_session" }.count, 3)
        XCTAssertFalse(FaceSignsHTTP.accepted.contains { $0["type"] as? String == "obs.face_signs" })
        // What the service holds: the three game records (each with its two older camera numbers).
        let held = FaceSignsHTTP.accepted.map { e in
            event(e["type"] as! String, source: e["source"] as! String, id: e["id"] as! String, payload: ["camera_samples": .number(25)])
        }
        let day = DayEvidence.build(events: held, talks: 0, transcriptsKept: false, camera: app.cameraChoice.sentToday())
        let item = day.items.first { $0.kind == .camera }
        XCTAssertEqual(item?.facts, ["Activities with the camera on: 3"], "three tasks, each once: not six")
        XCTAssertEqual(item?.sources, [KaikuPlatform.isPhone ? "evidence.src.phone" : "evidence.src.laptop"])
        XCTAssertEqual(item?.sharing, .numbers); XCTAssertEqual(item?.practice, false)
        let note = (item?.note ?? "").lowercased()
        XCTAssertTrue(note.contains("numbers") && note.contains("no pictures") && note.contains("this device"))
        XCTAssertEqual(T("evidence.camera"), "Camera during activities")
        XCTAssertEqual(DayEvidence.cameraTasks(events: held, sent: app.cameraChoice.sentToday())?.count, 3)
        XCTAssertEqual(T("saw.camera.n", n: 3), "Activities with the camera on: 3. Face movement as numbers, no pictures.")
    }

    func testTheReceiptCountsEachTaskOnceFromWhateverTheServiceHolds() {
        let play = "0193a3c0-0000-7000-8000-00000000000a", signs = "0193a3c0-0000-7000-8000-00000000000b"
        let local = [CameraChoice.Sent(id: signs, ref: play, sim: false, day: AppModel.dayKey(Date()))]
        // The service knows the type: the stored record and the device's note of it are one task.
        let known = [event("obs.play_session", id: play, payload: ["camera_samples": .number(300)]),
                     event("obs.face_signs", id: signs, payload: ["ref": .string(play), "task": .string("lantern")])]
        XCTAssertEqual(DayEvidence.cameraTasks(events: known, sent: local)?.count, 1)
        // Another device's task, and a game record with camera numbers of its own and no face signs (another kind of app).
        let more = known + [event("obs.face_signs", source: "laptop", payload: ["task": .string("check_in")]),
                            event("obs.play_session", source: "laptop", payload: ["camera_samples": .number(40)]),
                            event("obs.play_session", payload: [:])]
        let all = DayEvidence.cameraTasks(events: more, sent: local)
        XCTAssertEqual(all?.count, 3); XCTAssertEqual(all?.sources, ["evidence.src.phone", "evidence.src.laptop"])
        // Nothing with the camera on: no line claims it.
        XCTAssertNil(DayEvidence.cameraTasks(events: [event("obs.play_session"), event("obs.self_report")], sent: []))
        XCTAssertFalse(DayEvidence.build(events: [event("obs.play_session")], talks: 0, transcriptsKept: false).items.contains { $0.kind == .camera })
        // Made-up numbers are labelled as such, and only when everything behind the line is made up.
        let pretend = [CameraChoice.Sent(id: "x", ref: nil, sim: true, day: AppModel.dayKey(Date()))]
        XCTAssertEqual(DayEvidence.cameraTasks(events: [], sent: pretend)?.practice, true)
        XCTAssertEqual(DayEvidence.cameraTasks(events: [], sent: pretend + local)?.practice, false)
        XCTAssertEqual(DayEvidence.cameraTasks(events: [event("obs.face_signs", id: "x", sim: true)], sent: pretend)?.practice, true)
    }

    func testWhatWasSentIsKeptForTodayOnlyAndNeverForAnotherHome() async {
        let defaults = UserDefaults(suiteName: UUID().uuidString)!
        let choice = CameraChoice(defaults: defaults)
        choice.note(id: "b", ref: nil, sim: true, now: Date().addingTimeInterval(-3 * 86_400))
        XCTAssertTrue(CameraChoice(defaults: defaults).sentToday().isEmpty, "what was sent on another day is not today's")
        choice.note(id: "a", ref: "g", sim: false)
        choice.note(id: "a", ref: "g", sim: false)        // the same envelope again is the same task
        XCTAssertEqual(CameraChoice(defaults: defaults).sentToday().map(\.id), ["a"], "kept across a relaunch, the older day dropped")
        XCTAssertEqual(CameraChoice(defaults: defaults).agreedWording, 0)
        choice.agree()
        XCTAssertEqual(CameraChoice(defaults: defaults).agreedWording, CameraChoice.wording)
        // Pairing with another home: what was sent belongs to the previous one. Her choice is a device preference and stays.
        FaceSignsHTTP.offline = true
        let app = makeApp(), source = FakeFaceSource(), camera = TaskCamera(source: source, permission: { true })
        await play(app, camera, source, seconds: 5)
        XCTAssertEqual(app.cameraChoice.sentToday().count, 1)
        await app.updatePairing(Pairing(baseURL: URL(string: "https://face-signs.test")!, homeID: "another-home", token: nil))
        XCTAssertTrue(app.cameraChoice.sentToday().isEmpty); XCTAssertTrue(app.cameraOn)
    }

    // MARK: a type the service does not know never holds the queue

    private func queueFixture() throws -> (OfflineQueue, APIClient, [AnyEnvelope]) {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [FaceSignsHTTP.self]
        let api = APIClient(pairing: pairing, maxAttempts: 1, session: URLSession(configuration: config))
        let queue = OfflineQueue(url: dir.appendingPathComponent("outbox-\(UUID().uuidString).json"))
        var a = FaceSignsAccumulator(rules: .vision); a.add(at: 0, rest(.vision)); a.add(at: 0.1, rest(.vision))
        let events = [
            try AnyEnvelope(Envelope(home_id: "synthetic", source: .phone, type: "obs.self_report", payload: SelfReport(item: .mood, value: 4, channel: .phone))),
            try AnyEnvelope(Envelope(home_id: "synthetic", source: .phone, type: "obs.face_signs", payload: FaceSigns(a.summary, task: "check_in", device: .phone, ref: nil))),
            try AnyEnvelope(Envelope(home_id: "synthetic", source: .phone, type: "obs.play_session", payload: PlaySession(game: .breathe, device: .phone, duration_s: 60))),
        ]
        return (queue, api, events)
    }

    func testAServiceThatNamesTheUnknownTypeAsRejectedStillTakesTheRest() async throws {
        FaceSignsHTTP.unknown = .namedInRejected            // how the Kaiku service answers today: 200 with `rejected`
        let (queue, api, events) = try queueFixture()
        for e in events { await queue.enqueue(e, server: pairing.baseURL) }
        let ok = await queue.flush(using: api)
        let left = await queue.count
        XCTAssertTrue(ok); XCTAssertEqual(left, 0, "nothing waits behind an envelope the service will never take")
        XCTAssertEqual(FaceSignsHTTP.accepted.compactMap { $0["type"] as? String }, ["obs.self_report", "obs.play_session"])
    }

    func testAServiceThatRefusesTheWholeBatchLosesOnlyTheOneEnvelope() async throws {
        FaceSignsHTTP.unknown = .wholeBatchRefused          // a stricter service: 422 for any batch with the type in it
        let (queue, api, events) = try queueFixture()
        for e in events { await queue.enqueue(e, server: pairing.baseURL) }
        let ok = await queue.flush(using: api)
        let left = await queue.count
        XCTAssertTrue(ok); XCTAssertEqual(left, 0)
        XCTAssertEqual(FaceSignsHTTP.accepted.compactMap { $0["type"] as? String }, ["obs.self_report", "obs.play_session"],
                       "the two it can read are delivered, each alone; only the one it cannot is dropped")
        // And what is recorded afterwards goes out as always.
        let later = try AnyEnvelope(Envelope(home_id: "synthetic", source: .phone, type: "obs.self_report", payload: SelfReport(item: .sleep, value: 3, channel: .phone)))
        await queue.enqueue(later, server: pairing.baseURL)
        let again = await queue.flush(using: api)
        XCTAssertTrue(again); XCTAssertEqual(FaceSignsHTTP.accepted.count, 3)
        // A single refused envelope alone is dropped without being sent again and again.
        let (single, api2, more) = try queueFixture()
        await single.enqueue(more[1], server: pairing.baseURL)
        let posts = FaceSignsHTTP.posts
        let done = await single.flush(using: api2)
        let none = await single.count
        XCTAssertTrue(done); XCTAssertEqual(none, 0); XCTAssertEqual(FaceSignsHTTP.posts, posts + 1)
    }

    func testOfflineEverythingWaitsInOrderAndGoesOutLater() async throws {
        FaceSignsHTTP.offline = true
        let app = makeApp(), source = FakeFaceSource(), camera = TaskCamera(source: source, permission: { true })
        await play(app, camera, source, seconds: 5)
        XCTAssertTrue(app.offline); XCTAssertEqual(app.queued, 2)
        FaceSignsHTTP.offline = false
        await app.flush()
        XCTAssertEqual(FaceSignsHTTP.accepted.compactMap { $0["type"] as? String }, ["obs.play_session", "obs.face_signs"])
        XCTAssertEqual(FaceSignsHTTP.accepted[1]["quality"] as? Double, 1)
        XCTAssertEqual((FaceSignsHTTP.accepted[1]["payload"] as? [String: Any])?["ref"] as? String, FaceSignsHTTP.accepted[0]["id"] as? String)
    }

    // MARK: History

    func testHistoryKnowsTheCameraGroupAndAnUnknownGroupStaysNeutral() {
        let camera = HistoryGroup(key: "camera", title: "Camera during activities", measures: [])
        XCTAssertEqual(camera.symbol, "camera.fill"); XCTAssertEqual(camera.tone, .sage)
        let unknown = HistoryGroup(key: "something_new", title: "Something new", measures: [])
        XCTAssertEqual(unknown.symbol, "chart.bar.fill"); XCTAssertEqual(unknown.tone, .ink, "drawn, in a neutral style: never left out")
        for key in ["robot", "games", "walks", "checkins", "sleep_body", "mac", "camera"] {
            XCTAssertFalse(HistoryGroup(key: key, title: key, measures: []).symbol.isEmpty)
        }
    }
}
