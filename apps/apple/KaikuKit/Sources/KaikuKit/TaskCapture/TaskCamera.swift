@preconcurrency import AVFoundation
@preconcurrency import Vision
import Foundation
import Observation

/// Scalar face geometry only. Pixels, identity, expressions-as-emotions and words are never retained.
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

protocol TaskCameraSource: AnyObject, Sendable {
    func start(frame: @escaping @Sendable (TaskFaceFrame?) -> Void, failed: @escaping @Sendable () -> Void) async -> Bool
    func stop()
}

@Observable @MainActor final class TaskCamera {
    enum State: Equatable { case off, requesting, capturing, unavailable }
    private(set) var state: State = .off
    @ObservationIgnored private let source: any TaskCameraSource
    @ObservationIgnored private let permission: () async -> Bool
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var features = TaskCameraFeatures()

    convenience init() {
        self.init(source: VisionTaskCamera(), permission: {
            switch AVCaptureDevice.authorizationStatus(for: .video) {
            case .authorized: return true
            case .notDetermined: return await AVCaptureDevice.requestAccess(for: .video)
            default: return false
            }
        })
    }
    init(source: any TaskCameraSource, permission: @escaping () async -> Bool) { self.source = source; self.permission = permission }

    func begin(allowed: Bool) async {
        cancel()
        guard allowed, !Task.isCancelled else { return }
        let current = generation
        state = .requesting
        let granted = await permission()
        guard generation == current, !Task.isCancelled else { return }
        guard granted else { state = .unavailable; return }
        features = TaskCameraFeatures()
        let ready = await source.start(frame: { [weak self] frame in Task { @MainActor in
            guard let self, self.generation == current, self.state == .capturing else { return }
            self.features.add(frame)
        } }, failed: { [weak self] in Task { @MainActor in
            guard let self, self.generation == current else { return }
            self.cancel(); self.state = .unavailable
        } })
        guard generation == current, !Task.isCancelled else { source.stop(); return }
        state = ready ? .capturing : .unavailable
    }

    func finish() -> TaskCameraSummary? {
        let result = features.summary
        cancel()
        return result.samples > 0 ? result : nil
    }
    func cancel() { generation += 1; source.stop(); state = .off; features = TaskCameraFeatures() }
}

/// A video-only AVFoundation session. Vision processes sampled frames on this serial queue in memory.
/// No capture output writes a file or sends media over the network. No audio input is attached.
final class VisionTaskCamera: NSObject, TaskCameraSource, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    private let queue = DispatchQueue(label: "fi.kaiku.task-camera", qos: .utility)
    private var session: AVCaptureSession?
    private var frame: (@Sendable (TaskFaceFrame?) -> Void)?
    private var failed: (@Sendable () -> Void)?
    private var previousSample = -Double.infinity
    private var observer: NSObjectProtocol?

    func start(frame: @escaping @Sendable (TaskFaceFrame?) -> Void, failed: @escaping @Sendable () -> Void) async -> Bool {
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
                self.frame = frame; self.failed = failed; self.previousSample = -.infinity; self.session = session
                self.observer = NotificationCenter.default.addObserver(forName: .AVCaptureSessionRuntimeError, object: session, queue: nil) { _ in failed() }
                session.startRunning()
                continuation.resume(returning: session.isRunning)
            }
        }
    }

    func stop() { queue.async { self.stopOnQueue() } }
    private func stopOnQueue() {
        if let observer { NotificationCenter.default.removeObserver(observer) }; observer = nil
        session?.stopRunning(); session = nil; frame = nil; failed = nil
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput buffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        let time = CMSampleBufferGetPresentationTimeStamp(buffer).seconds
        // Fixed sampling cadence defines the movement proxy, rather than a device-dependent video frame rate.
        guard time - previousSample >= 0.2, let pixels = CMSampleBufferGetImageBuffer(buffer) else { return }
        previousSample = time
        autoreleasepool {
            let request = VNDetectFaceLandmarksRequest()
            do { try VNImageRequestHandler(cvPixelBuffer: pixels, orientation: .up).perform([request]) }
            catch { frame?(nil); return }
            guard let faces = request.results, faces.count == 1, let face = faces.first,
                  let mouth = Self.aspect(face.landmarks?.outerLips),
                  let left = Self.aspect(face.landmarks?.leftEye), let right = Self.aspect(face.landmarks?.rightEye) else { frame?(nil); return }
            frame?(TaskFaceFrame(centerX: face.boundingBox.midX, centerY: face.boundingBox.midY,
                                 mouthAspect: mouth, eyeAspect: (left + right) / 2))
        }
    }

    private static func aspect(_ region: VNFaceLandmarkRegion2D?) -> Double? {
        guard let points = region?.normalizedPoints, points.count >= 3,
              let left = points.map(\.x).min(), let right = points.map(\.x).max(),
              let bottom = points.map(\.y).min(), let top = points.map(\.y).max(), right > left else { return nil }
        return min(1, max(0, (top - bottom) / (right - left)))
    }
}
