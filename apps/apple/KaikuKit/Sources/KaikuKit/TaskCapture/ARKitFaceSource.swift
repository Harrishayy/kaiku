#if canImport(ARKit) && os(iOS)
import ARKit
@preconcurrency import AVFoundation
import Foundation
import simd

/// ARKit face tracking on an iPhone with a TrueDepth camera: a session with no view. On each update it reads a
/// handful of blendshape coefficients, the head's pose and the look-at point. A frame's pixels are never copied,
/// stored or sent; five times a second they are handed to Vision in memory for the two older numbers in
/// obs.play_session (the same landmark measure as on the Mac), and let go. The Mac build does not contain this file.
final class ARKitFaceSource: NSObject, TaskCameraSource, ARSessionDelegate, @unchecked Sendable {
    static var isSupported: Bool { ARFaceTrackingConfiguration.isSupported }

    let rules = FaceSignRules.arkit
    /// ARKit updates up to 60 times a second. Thirty looks a second see every blink (0.1 to 0.4 s); the other
    /// updates are skipped unread.
    static let signsHz = 30.0

    private let queue = DispatchQueue(label: "fi.kaiku.task-face", qos: .utility)
    private var session: ARSession?
    private var sample: (@Sendable (TaskCameraSample) -> Void)?
    private var failed: (@Sendable () -> Void)?
    private var previousSample = -Double.infinity, previousGeometry = -Double.infinity
    private let reader = VisionFaceReader()

    func start(sample: @escaping @Sendable (TaskCameraSample) -> Void, failed: @escaping @Sendable () -> Void) async -> Bool {
        await withCheckedContinuation { continuation in
            queue.async {
                self.stopOnQueue()
                guard ARFaceTrackingConfiguration.isSupported, AVCaptureDevice.authorizationStatus(for: .video) == .authorized else {
                    continuation.resume(returning: false); return
                }
                let configuration = ARFaceTrackingConfiguration()
                configuration.maximumNumberOfTrackedFaces = 1
                configuration.isLightEstimationEnabled = false    // not used: one thing less to compute
                configuration.providesAudioData = false           // the microphone is never ARKit's
                // Face tracking itself runs on the depth camera; the picture is only read for the two older numbers.
                if let format = FaceSignLimits.lightest(ARFaceTrackingConfiguration.supportedVideoFormats.map {
                    (fps: $0.framesPerSecond, pixels: Int($0.imageResolution.width * $0.imageResolution.height), format: $0)
                }) { configuration.videoFormat = format }
                let session = ARSession()
                session.delegate = self
                session.delegateQueue = self.queue
                self.sample = sample; self.failed = failed; self.session = session
                self.previousSample = -.infinity; self.previousGeometry = -.infinity
                session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
                continuation.resume(returning: true)   // a camera that cannot start reports through the delegate
            }
        }
    }

    func stop() { queue.async { self.stopOnQueue() } }
    private func stopOnQueue() {
        session?.pause(); session?.delegate = nil; session = nil; sample = nil; failed = nil
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        let t = frame.timestamp
        guard t - previousSample >= 1 / Self.signsHz - VisionTaskCamera.slack else { return }
        previousSample = t
        var out = TaskCameraSample(t: t, face: Self.reading(frame))
        if t - previousGeometry >= VisionTaskCamera.geometryStep - VisionTaskCamera.slack {
            previousGeometry = t
            // ARKit's picture lies on its side in a phone held upright (the app is portrait only).
            autoreleasepool { out.geometry = reader.geometry(frame.capturedImage, orientation: .right) }
        }
        sample?(out)
    }

    func session(_ session: ARSession, didFailWithError error: Error) { failed?() }
    /// The system took the camera (another app, a phone call, the app left the foreground).
    func sessionWasInterrupted(_ session: ARSession) { failed?() }

    /// One tracked face as numbers, or nil. With `maximumNumberOfTrackedFaces = 1` ARKit follows at most one face.
    static func reading(_ frame: ARFrame) -> FaceReading? {
        let faces = frame.anchors.compactMap { $0 as? ARFaceAnchor }.filter(\.isTracked)
        guard faces.count == 1, let face = faces.first else { return nil }
        func shape(_ key: ARFaceAnchor.BlendShapeLocation) -> Double? { face.blendShapes[key]?.doubleValue }
        guard let smileLeft = shape(.mouthSmileLeft), let smileRight = shape(.mouthSmileRight),
              let browInner = shape(.browInnerUp), let browOuterLeft = shape(.browOuterUpLeft), let browOuterRight = shape(.browOuterUpRight),
              let browDownLeft = shape(.browDownLeft), let browDownRight = shape(.browDownRight),
              let blinkLeft = shape(.eyeBlinkLeft), let blinkRight = shape(.eyeBlinkRight),
              let jawOpen = shape(.jawOpen), let mouthClose = shape(.mouthClose) else { return nil }
        // For the visible expression cues only (D60); a coefficient ARKit does not give leaves that cue unseen.
        func both(_ l: ARFaceAnchor.BlendShapeLocation, _ r: ARFaceAnchor.BlendShapeLocation) -> Double? {
            guard let a = shape(l), let b = shape(r) else { return nil }
            return (a + b) / 2
        }
        // The head as the device sees it: the camera's own movement in the room is taken out.
        let relative = simd_mul(simd_inverse(frame.camera.transform), face.transform)
        let turn = simd_quatf(relative)
        return FaceReading(
            smile: (smileLeft + smileRight) / 2,
            browRaise: max(browInner, (browOuterLeft + browOuterRight) / 2),
            browFurrow: (browDownLeft + browDownRight) / 2,
            eyeClosed: min(blinkLeft, blinkRight),
            mouthOpen: max(0, jawOpen - mouthClose),
            gazeOn: gazeOn(face: face, relative: relative),
            head: .rotation(x: Double(turn.imag.x), y: Double(turn.imag.y), z: Double(turn.imag.z), w: Double(turn.real)),
            frown: both(.mouthFrownLeft, .mouthFrownRight), browInner: browInner,
            press: both(.mouthPressLeft, .mouthPressRight), squint: both(.eyeSquintLeft, .eyeSquintRight))
    }

    /// Looking toward the screen: the line from between the eyes to the look-at point, against the line from
    /// between the eyes to the camera (`FaceSignLimits.gazeConeDegrees`). Both in the device's space.
    static func gazeOn(face: ARFaceAnchor, relative: simd_float4x4) -> Bool? {
        let eyes = (face.leftEyeTransform.columns.3 + face.rightEyeTransform.columns.3) / 2     // in the face's space
        let look = face.lookAtPoint
        let direction = simd_mul(relative, simd_float4(look.x - eyes.x, look.y - eyes.y, look.z - eyes.z, 0))
        let place = simd_mul(relative, simd_float4(eyes.x, eyes.y, eyes.z, 1))
        return FaceSignLimits.gazeOn(direction: (Double(direction.x), Double(direction.y), Double(direction.z)),
                                     toCamera: (Double(-place.x), Double(-place.y), Double(-place.z)))
    }
}
#endif
