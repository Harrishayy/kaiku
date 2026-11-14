@preconcurrency import AVFoundation
@preconcurrency import Vision
import Foundation
import Observation

// The optional camera during tasks ("Camera during activities"): the controller and the Vision source.
// Nothing is recorded. A frame is looked at in memory on this device and let go; only numbers leave this file
// (`FaceSigns.swift` turns them into one summary a task). The ARKit source is in `ARKitFaceSource.swift`.

/// Scalar face geometry only (the two older numbers in obs.play_session). Pixels, identity,
/// expressions-as-emotions and words are never retained.
struct TaskFaceFrame: Sendable {
    var centerX: Double
    var centerY: Double
    var mouthAspect: Double
    var eyeAspect: Double
}

struct TaskCameraSummary: Equatable, Sendable {
    var expressivity: Double?
    var movement: Double?
    var coverage: Double
    var samples: Int
}

/// Online geometry variability, not an emotion classifier. Vision values must only be compared with the same
/// task and camera_method; they are not interchangeable with web blendshape values.
struct TaskCameraFeatures {
    private(set) var samples = 0
    private var faces = 0
    private var mouthMean = 0.0, mouthM2 = 0.0, eyeMean = 0.0, eyeM2 = 0.0
    private var previous: TaskFaceFrame?
    private var distance = 0.0, movements = 0

    mutating func add(_ frame: TaskFaceFrame?) {
        samples += 1
        guard let f = frame, [f.centerX, f.centerY, f.mouthAspect, f.eyeAspect].allSatisfy(\.isFinite),
              (0...1).contains(f.centerX), (0...1).contains(f.centerY),
              (0...1).contains(f.mouthAspect), (0...1).contains(f.eyeAspect) else { previous = nil; return }
        faces += 1
        let md = f.mouthAspect - mouthMean; mouthMean += md / Double(faces); mouthM2 += md * (f.mouthAspect - mouthMean)
        let ed = f.eyeAspect - eyeMean; eyeMean += ed / Double(faces); eyeM2 += ed * (f.eyeAspect - eyeMean)
        if let p = previous {
            distance += min(1, hypot(f.centerX - p.centerX, f.centerY - p.centerY)); movements += 1
        }
        previous = f
    }

    var summary: TaskCameraSummary {
        let variability = faces >= 2 ? min(1, (sqrt(max(0, mouthM2) / Double(faces - 1)) + sqrt(max(0, eyeM2) / Double(faces - 1))) / 2) : nil
        return TaskCameraSummary(expressivity: variability, movement: movements > 0 ? distance / Double(movements) : nil,
                                 coverage: samples > 0 ? Double(faces) / Double(samples) : 0, samples: samples)
    }
}

/// What a source hands over for one frame it looked at: numbers only.
struct TaskCameraSample: Sendable {
    /// The older landmark geometry rides on five of the samples a second (its movement number is per 0.2 s step).
    enum Geometry: Sendable { case none, missing, face(TaskFaceFrame) }
    /// Seconds on the source's own clock.
    var t: Double
    /// The face signs of this frame; nil when it did not hold exactly one usable face.
    var face: FaceReading?
    var geometry: Geometry = .none
}

protocol TaskCameraSource: AnyObject, Sendable {
    /// The thresholds its readings go with, and with them the `method` word.
    var rules: FaceSignRules { get }
    /// True only for a stand-in that opens no camera (layout pictures, UI tests). What it yields goes out as
    /// simulated, never as a person's numbers.
    var simulated: Bool { get }
    func start(sample: @escaping @Sendable (TaskCameraSample) -> Void, failed: @escaping @Sendable () -> Void) async -> Bool
    func stop()
}

extension TaskCameraSource {
    var simulated: Bool { false }
}

/// One task's camera time, finished: the face signs, the two older numbers for obs.play_session when Vision
/// measured them (always Vision landmarks, whatever `signs.method` says), and whether a stand-in made them.
struct TaskCameraResult: Equatable, Sendable {
    var signs: FaceSignsSummary
    var geometry: TaskCameraSummary?
    var simulated: Bool
}

/// The running numbers of one task session. Samples arrive in order on the source's queue; the controller reads
/// on the main actor. Only samples of the generation it is told to accept are counted.
private final class TaskCameraTally: @unchecked Sendable {
    private let lock = NSLock()
    private let rules: FaceSignRules
    private var signs: FaceSignsAccumulator
    private var features = TaskCameraFeatures()
    private var accepting: Int?

    init(rules: FaceSignRules) { self.rules = rules; signs = FaceSignsAccumulator(rules: rules) }

    func accept(_ generation: Int?) { lock.lock(); accepting = generation; lock.unlock() }
    func reset() { lock.lock(); accepting = nil; signs = FaceSignsAccumulator(rules: rules); features = TaskCameraFeatures(); lock.unlock() }
    func add(_ sample: TaskCameraSample, generation: Int) {
        lock.lock(); defer { lock.unlock() }
        guard accepting == generation else { return }
        signs.add(at: sample.t, sample.face)
        switch sample.geometry {
        case .none: break
        case .missing: features.add(nil)
        case .face(let frame): features.add(frame)
        }
    }
    var result: (FaceSignsSummary, TaskCameraSummary) { lock.lock(); defer { lock.unlock() }; return (signs.summary, features.summary) }
}

/// The camera of one task screen (a game, the check-in). It runs only between `begin` and the task's end, only
/// while that screen is in front, and never without the person's choice and the system's permission.
@Observable @MainActor final class TaskCamera {
    enum State: Equatable {
        case off            // not wanted, or no task running
        case requesting     // the system is asking for the camera
        case capturing      // sampling
        case suspended      // the task goes on but its screen is not in front: nothing is sampled
        case stopped        // the person turned it off for this task
        case unavailable    // no permission, no camera, in use elsewhere, or a call or walk is on: the task goes on without it
    }
    private(set) var state: State = .off
    /// True while something other than a task is using Kaiku's attention (a walk, a voice call that is not this
    /// task): the camera then stays off. Checked at every start and about once a second while sampling.
    @ObservationIgnored var blocked: () -> Bool = { false }
    @ObservationIgnored private let source: any TaskCameraSource
    @ObservationIgnored private let permission: () async -> Bool
    @ObservationIgnored private let tally: TaskCameraTally
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var watch: Task<Void, Never>?
    /// How often `blocked` is asked again while sampling.
    static var watchEvery: TimeInterval = 1

    convenience init() {
        let (source, permission) = Self.standard()
        self.init(source: source, permission: permission)
    }

    init(source: any TaskCameraSource, permission: @escaping () async -> Bool) {
        self.source = source
        self.permission = permission
        tally = TaskCameraTally(rules: source.rules)
    }

    /// The device's own source: ARKit face tracking where the iPhone has a TrueDepth camera, Vision landmarks on
    /// the Mac and on other iPhones. The system's permission question is asked here and nowhere earlier: the first
    /// time a task starts with the choice on.
    static func standard() -> (any TaskCameraSource, () async -> Bool) {
        #if DEBUG
        let defaults = UserDefaults.standard
        if defaults.string(forKey: "kaikuFaceSource") == "scripted" { return (ScriptedFaceSource(), { true }) }
        // A run that only takes pictures of the app or inspects its layout never opens a camera.
        if AppPresence.pictureRun || defaults.bool(forKey: "kaikuInspectOnly") { return (VisionTaskCamera(), { false }) }
        #endif
        let ask: () async -> Bool = {
            switch AVCaptureDevice.authorizationStatus(for: .video) {
            case .authorized: return true
            case .notDetermined: return await AVCaptureDevice.requestAccess(for: .video)
            default: return false
            }
        }
        #if canImport(ARKit) && os(iOS)
        if ARKitFaceSource.isSupported { return (ARKitFaceSource(), ask) }
        #endif
        return (VisionTaskCamera(), ask)
    }

    /// A new task session. Nothing is asked for, opened or kept unless `allowed`.
    func begin(allowed: Bool) async {
        cancel()
        guard allowed, !Task.isCancelled else { return }
        await open()
    }

    /// The task's screen is no longer in front (another app, the app switcher, a locked or sleeping screen): the
    /// camera closes at once. The numbers so far stay; `resume` goes on from them.
    func suspend() {
        guard state == .capturing || state == .requesting else { return }
        close(.suspended)
    }

    /// Back in front: the camera comes back if it was only waiting for that.
    func resume() async {
        guard state == .suspended else { return }
        await open()
    }

    /// The person's own tap on the indicator: off for this task. What was sampled in it is thrown away.
    func stopForThisTask() {
        guard state == .capturing || state == .requesting || state == .suspended else { return }
        close(.stopped)
        tally.reset()
    }

    /// The task ended: the camera closes and the session's numbers are handed over (nil when nothing was sampled).
    func finish() -> TaskCameraResult? {
        let (signs, geometry) = tally.result
        close(.off)
        tally.reset()
        guard signs.samples > 0 else { return nil }
        return TaskCameraResult(signs: signs, geometry: geometry.samples > 0 ? geometry : nil, simulated: source.simulated)
    }

    /// Back, dismissal, a withdrawn choice, "pause everything": the camera closes and nothing is kept.
    func cancel() {
        close(.off)
        tally.reset()
    }

    // MARK: private

    private func open() async {
        generation += 1
        let current = generation
        state = .requesting
        let granted = await permission()
        guard generation == current else { return }      // cancelled, suspended, finished or begun again meanwhile
        guard !Task.isCancelled else { state = .off; return }
        guard granted, !blocked() else { state = .unavailable; return }
        tally.accept(current)
        let ready = await source.start(sample: { [tally] sample in tally.add(sample, generation: current) },
                                       failed: { [weak self] in Task { @MainActor in self?.lost(current) } })
        guard generation == current else {
            // Closed while the source was starting. A newer start may already be on its way: leave that one alone.
            if state != .requesting && state != .capturing { source.stop() }
            return
        }
        guard ready else { tally.accept(nil); state = .unavailable; return }
        state = .capturing
        watch = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(Self.watchEvery * 1_000_000_000))
                guard let self, !Task.isCancelled, self.generation == current else { return }
                if self.blocked() { self.lost(current) }
            }
        }
    }

    /// The camera went away by itself (taken by another app, a closed lid, an error), or a call or walk began.
    /// The task goes on; what was sampled until now is still this task's.
    private func lost(_ current: Int) {
        guard generation == current else { return }
        close(.unavailable)
    }

    private func close(_ next: State) {
        generation += 1
        watch?.cancel(); watch = nil
        tally.accept(nil)
        source.stop()
        state = next
    }
}

/// Vision face landmarks on one frame, in memory: numbers out. The pixels are not copied, kept or sent.
struct VisionFaceReader {
    private var leftOpen = OpenEyeLevel(), rightOpen = OpenEyeLevel()

    /// The face signs Vision's flat landmarks can honestly give (see `FaceSignRules.vision`), and on request the
    /// older geometry too. `size` is the picture's size as oriented.
    mutating func read(_ pixels: CVPixelBuffer, orientation: CGImagePropertyOrientation, at t: Double, geometry: Bool) -> TaskCameraSample {
        var out = TaskCameraSample(t: t, face: nil, geometry: geometry ? .missing : .none)
        guard let face = Self.oneFace(pixels, orientation: orientation), let marks = face.landmarks else { return out }
        if geometry, let frame = Self.geometry(face) { out.geometry = .face(frame) }
        var size = CGSize(width: CVPixelBufferGetWidth(pixels), height: CVPixelBufferGetHeight(pixels))
        if [.left, .right, .leftMirrored, .rightMirrored].contains(orientation) { size = CGSize(width: size.height, height: size.width) }
        guard let left = marks.leftEye?.pointsInImage(imageSize: size), let right = marks.rightEye?.pointsInImage(imageSize: size),
              let outer = marks.outerLips?.pointsInImage(imageSize: size), let inner = marks.innerLips?.pointsInImage(imageSize: size),
              let leftOpening = FaceGeometry.eyeOpening(left), let rightOpening = FaceGeometry.eyeOpening(right),
              let eyeLine = FaceGeometry.line(from: FaceGeometry.centre(left), to: FaceGeometry.centre(right)),
              let mouth = FaceGeometry.mouthOpening(inner: inner, outer: outer, eyeLine: eyeLine) else { return out }
        let between = eyeLine.length
        // Each eye against its own open level; both must be closing for a blink (a wink, or one eye hidden by
        // the nose in a turned face, is not one).
        let closedLeft = leftOpen.closedness(of: leftOpening), closedRight = rightOpen.closedness(of: rightOpening)
        // For the range of expression only: the mouth's width (halved: a mouth is about as wide as the eyes are
        // apart) and the brows' height over the eyes, both against the distance between the eyes.
        var shape: [Double] = []
        if let width = FaceGeometry.mouthWidth(outer: outer, eyeLine: eyeLine),
           let lb = marks.leftEyebrow?.pointsInImage(imageSize: size), let rb = marks.rightEyebrow?.pointsInImage(imageSize: size),
           let l = FaceGeometry.distance(FaceGeometry.centre(lb), FaceGeometry.centre(left)),
           let r = FaceGeometry.distance(FaceGeometry.centre(rb), FaceGeometry.centre(right)) {
            shape = [min(1, width / (2 * between)), min(1, (l + r) / 2 / between)]
        }
        let box = face.boundingBox
        out.face = FaceReading(eyeClosed: closedLeft.flatMap { l in closedRight.map { min(l, $0) } }, mouthOpen: min(1, mouth),
                               head: .place(x: box.midX * size.width, y: box.midY * size.height, width: box.width * size.width),
                               shape: shape)
        return out
    }

    /// Only the older geometry (the ARKit source asks for it five times a second, to keep obs.play_session's
    /// camera fields the same measure on every device).
    func geometry(_ pixels: CVPixelBuffer, orientation: CGImagePropertyOrientation) -> TaskCameraSample.Geometry {
        guard let face = Self.oneFace(pixels, orientation: orientation), let frame = Self.geometry(face) else { return .missing }
        return .face(frame)
    }

    /// Exactly one face, or nothing: two faces in the picture are nobody's numbers.
    private static func oneFace(_ pixels: CVPixelBuffer, orientation: CGImagePropertyOrientation) -> VNFaceObservation? {
        let request = VNDetectFaceLandmarksRequest()
        guard (try? VNImageRequestHandler(cvPixelBuffer: pixels, orientation: orientation).perform([request])) != nil,
              let faces = request.results, faces.count == 1 else { return nil }
        return faces.first
    }

    private static func geometry(_ face: VNFaceObservation) -> TaskFaceFrame? {
        guard let mouth = aspect(face.landmarks?.outerLips),
              let left = aspect(face.landmarks?.leftEye), let right = aspect(face.landmarks?.rightEye) else { return nil }
        return TaskFaceFrame(centerX: face.boundingBox.midX, centerY: face.boundingBox.midY, mouthAspect: mouth, eyeAspect: (left + right) / 2)
    }

    private static func aspect(_ region: VNFaceLandmarkRegion2D?) -> Double? {
        guard let points = region?.normalizedPoints, points.count >= 3,
              let left = points.map(\.x).min(), let right = points.map(\.x).max(),
              let bottom = points.map(\.y).min(), let top = points.map(\.y).max(), right > left else { return nil }
        return min(1, max(0, (top - bottom) / (right - left)))
    }
}

/// A video-only AVFoundation session. Vision processes sampled frames on this serial queue in memory.
/// No capture output writes a file or sends media over the network. No audio input is attached.
final class VisionTaskCamera: NSObject, TaskCameraSource, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    let rules = FaceSignRules.vision
    /// Frames looked at a second. A blink lasts 0.1 to 0.4 s: fifteen looks a second see it, five would miss
    /// most. The camera's other frames are dropped unread.
    static let signsHz = 15.0
    /// The older two numbers keep their own cadence: their movement number is defined per 0.2 s step.
    static let geometryStep = 0.2
    /// Room for a frame that arrives a few milliseconds early.
    static let slack = 0.004

    private let queue = DispatchQueue(label: "fi.kaiku.task-camera", qos: .utility)
    private var session: AVCaptureSession?
    private var sample: (@Sendable (TaskCameraSample) -> Void)?
    private var failed: (@Sendable () -> Void)?
    private var previousSample = -Double.infinity, previousGeometry = -Double.infinity
    private var observers: [NSObjectProtocol] = []
    private var reader = VisionFaceReader()

    func start(sample: @escaping @Sendable (TaskCameraSample) -> Void, failed: @escaping @Sendable () -> Void) async -> Bool {
        await withCheckedContinuation { continuation in
            queue.async {
                self.stopOnQueue()
                guard AVCaptureDevice.authorizationStatus(for: .video) == .authorized else { continuation.resume(returning: false); return }
                #if os(iOS)
                let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front)
                #else
                let device = AVCaptureDevice.default(for: .video)
                #endif
                guard let device, let input = try? AVCaptureDeviceInput(device: device) else { continuation.resume(returning: false); return }
                let session = AVCaptureSession(), output = AVCaptureVideoDataOutput()
                #if os(iOS)
                session.automaticallyConfiguresApplicationAudioSession = false
                #endif
                session.beginConfiguration(); session.sessionPreset = .medium
                output.alwaysDiscardsLateVideoFrames = true
                output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
                guard session.canAddInput(input), session.canAddOutput(output) else { session.commitConfiguration(); continuation.resume(returning: false); return }
                session.addInput(input); session.addOutput(output)
                output.setSampleBufferDelegate(self, queue: self.queue)
                if let connection = output.connection(with: .video) {
                    #if os(iOS)
                    if connection.isVideoRotationAngleSupported(90) { connection.videoRotationAngle = 90 }
                    #endif
                    if connection.isVideoMirroringSupported { connection.automaticallyAdjustsVideoMirroring = false; connection.isVideoMirrored = false }
                }
                session.commitConfiguration()
                self.sample = sample; self.failed = failed; self.session = session
                self.previousSample = -.infinity; self.previousGeometry = -.infinity; self.reader = VisionFaceReader()
                // The camera can be taken away while a task runs (another app, a closed lid, the system): the task goes on.
                for name in [AVCaptureSession.runtimeErrorNotification, AVCaptureSession.wasInterruptedNotification] {
                    self.observers.append(NotificationCenter.default.addObserver(forName: name, object: session, queue: nil) { _ in failed() })
                }
                session.startRunning()
                continuation.resume(returning: session.isRunning)
            }
        }
    }

    func stop() { queue.async { self.stopOnQueue() } }
    private func stopOnQueue() {
        observers.forEach(NotificationCenter.default.removeObserver); observers = []
        session?.stopRunning(); session = nil; sample = nil; failed = nil
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput buffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        let time = CMSampleBufferGetPresentationTimeStamp(buffer).seconds
        guard time - previousSample >= 1 / Self.signsHz - Self.slack, let pixels = CMSampleBufferGetImageBuffer(buffer) else { return }
        previousSample = time
        let geometry = time - previousGeometry >= Self.geometryStep - Self.slack
        if geometry { previousGeometry = time }
        autoreleasepool { sample?(reader.read(pixels, orientation: .up, at: time, geometry: geometry)) }
    }
}

#if DEBUG
/// A stand-in for the camera (`-kaikuFaceSource scripted`): it opens no camera and looks at nobody. It plays
/// made-up readings on a timer so the indicator and the flow can be pictured and UI-tested where there is no
/// camera (a simulator, a picture run of the Mac app). Whatever it yields is sent with `sim: true` and shown as
/// "Simulated": never a person's numbers, never a recording of the product at work.
final class ScriptedFaceSource: TaskCameraSource, @unchecked Sendable {
    let rules = FaceSignRules.vision
    var simulated: Bool { true }
    private let queue = DispatchQueue(label: "fi.kaiku.task-camera.scripted", qos: .utility)
    private var timer: DispatchSourceTimer?

    func start(sample: @escaping @Sendable (TaskCameraSample) -> Void, failed: @escaping @Sendable () -> Void) async -> Bool {
        queue.sync {
            timer?.cancel()
            var n = 0
            let timer = DispatchSource.makeTimerSource(queue: queue)
            timer.schedule(deadline: .now(), repeating: 1 / VisionTaskCamera.signsHz)
            timer.setEventHandler {
                n += 1
                let t = Double(n) / VisionTaskCamera.signsHz
                let sway = sin(t)
                let face = FaceReading(eyeClosed: n % 45 == 0 ? 0.9 : 0.02, mouthOpen: 0.04 + 0.1 * abs(sway),
                                       head: .place(x: 320 + 6 * sway, y: 240, width: 200), shape: [0.45 + 0.02 * sway, 0.33])
                let frame = TaskFaceFrame(centerX: 0.5 + 0.01 * sway, centerY: 0.5, mouthAspect: 0.3 + 0.05 * abs(sway), eyeAspect: 0.28)
                sample(TaskCameraSample(t: t, face: face, geometry: n % 3 == 0 ? .face(frame) : .none))
            }
            timer.resume()
            self.timer = timer
        }
        return true
    }

    func stop() { queue.async { self.timer?.cancel(); self.timer = nil } }
}
#endif
