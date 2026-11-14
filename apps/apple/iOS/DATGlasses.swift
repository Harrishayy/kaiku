import AVFoundation
import CoreImage
import Foundation
import KaikuKit
import UIKit

#if canImport(MWDATCore) && canImport(MWDATMotion) && canImport(MWDATCamera)
import MWDATCamera
import MWDATCore
import MWDATMotion
#if DEBUG && canImport(MWDATMockDevice)
import MWDATMockDevice
#endif

/// Meta glasses through the Wearables Device Access Toolkit (MWDAT 1.0.1, SPM).
///
/// One device session per walk carries two optional capabilities:
///   Motion (IMU, experimental) → cadence / gait numbers;
///   Camera stream (`addCamera` → `camera.stream`, raw frames, lowest resolution, 2 fps) → about one JPEG a second
///   handed to the walk as `GlassesEvent.frame`, in memory only, and only after `setCamera(true)` (the person's
///   "Let Kaiku see" choice + the camera permission granted in the Meta AI app).
/// Microphone and speakers are NOT part of the toolkit session: they are ordinary Bluetooth hands-free audio
/// (`TalkAudio`), and that route must be settled before this session starts (Meta docs, "Microphones and speakers").
/// `useMockDeviceKit` pairs simulated Ray-Ban Meta glasses with a synthetic walking feed and a generated video, so
/// the real SDK path runs without glasses. Every step and every failure goes to `GlassesLog`.
final class DATGlasses: GlassesAdapter, @unchecked Sendable {
    let kind: String
    private let useMockDeviceKit: Bool
    private let lock = NSLock()
    private var session: DeviceSession?
    private var motion: Motion?
    private var camera: Camera?
    private var cameraTokens: [any AnyListenerToken] = []
    private var deviceTokens: [any AnyListenerToken] = []
    private var tasks: [Task<Void, Never>] = []
    private var events: (@Sendable (GlassesEvent) -> Void)?
    private var wantCamera = false
    private var started = false
    private var lastFrame = Date.distantPast
    private var encoding = false
    private static var configured = false
    /// A walk owns the session: the self-test must not start a second one.
    private(set) static var walkActive = false

    init(useMockDeviceKit: Bool) {
        self.useMockDeviceKit = useMockDeviceKit
        kind = useMockDeviceKit ? "dat-mock" : "dat"
    }

    static func configureSDK() throws {
        if !configured { try Wearables.configure(); configured = true }
    }

    /// Explicit setup action: opens Meta AI registration without starting audio or a walk.
    static func register() async -> Bool {
        do {
            try configureSDK()
            if Wearables.shared.registrationState != .registered { try await Wearables.shared.startRegistration() }
            GlassesLog.shared.log("dat_registration", ["state": word(Wearables.shared.registrationState)])
            return Wearables.shared.registrationState == .registered
        } catch {
            GlassesLog.shared.log("error", ["where": "registration", "error": "\(error)"])
            return false
        }
    }

    func start(_ events: @escaping @Sendable (GlassesEvent) -> Void) async {
        lock.withLock { self.events = events }
        Self.walkActive = true
        events(.state(.searching))
        do {
            // configure() first: enabling Mock Device Kit before it makes configure() throw (tried, 1.0.1)
            try Self.configureSDK()
            #if DEBUG && canImport(MWDATMockDevice)
            if useMockDeviceKit { try await Self.prepareMock() }
            #endif
            let wearables = Wearables.shared
            GlassesLog.shared.log("dat_start", ["registration": Self.word(wearables.registrationState), "devices": wearables.devices.count])
            if !useMockDeviceKit && wearables.registrationState != .registered {
                events(.state(.registrationRequired))
                try await wearables.startRegistration()
                // Meta AI approval returns through KaikuApp.handleUrl. Registration is not device connection.
                for _ in 0..<300 {
                    if Task.isCancelled { return }
                    if wearables.registrationState == .registered { break }
                    try await Task.sleep(nanoseconds: 200_000_000)
                }
                guard wearables.registrationState == .registered else { return }
                events(.state(.searching))
            }
            // devices arrive asynchronously (real glasses over BLE, or the mock pairing): wait up to 8 s
            for _ in 0..<40 where wearables.devices.isEmpty { try? await Task.sleep(nanoseconds: 200_000_000) }
            guard !Task.isCancelled, let id = wearables.devices.first else {
                events(.problem("No glasses found by the Meta toolkit. Open the Meta AI app, check the glasses are connected there, unfolded and on."))
                events(.state(.disconnected)); return
            }
            if let device = wearables.deviceForIdentifier(id) {
                let t = device.addDeviceStateListener { st in
                    GlassesLog.shared.log("dat_device", ["link": Self.word(st.linkState), "worn": Self.word(st.donState),
                                                         "hinge": Self.word(st.hingeState), "battery": st.batteryLevel ?? -1])
                    if st.donState != .unknown { events(.worn(st.donState == .donned)) }
                }
                lock.withLock { deviceTokens.append(t) }
            }
            let s = try await Self.makeSession()
            lock.withLock { session = s }
            let states = s.stateStream()
            let errors = s.errorStream()
            try s.start()
            let watcher = Task { [weak self] in
                for await st in states {
                    GlassesLog.shared.log("dat_session", ["state": st.description])
                    switch st {
                    case .started:
                        self?.lock.withLock { self?.started = true }
                        self?.attachMotion(events)
                        self?.applyCamera()
                    case .paused:
                        self?.lock.withLock { self?.started = false }
                        events(.state(.searching))
                        if self?.lock.withLock({ self?.wantCamera }) == true { events(.camera(.paused, note: nil)) }
                    case .stopped:
                        self?.lock.withLock { self?.started = false }
                        events(.camera(.off, note: nil))
                        events(.state(.disconnected)); return
                    default: break
                    }
                }
            }
            let errWatcher = Task {
                for await e in errors { events(.problem("Glasses session: \(e.description)")) }
            }
            lock.withLock { tasks.append(contentsOf: [watcher, errWatcher]) }
        } catch {
            events(.problem("Glasses session could not start: \((error as? any DatError)?.description ?? "\(error)")"))
            events(.state(.disconnected))
        }
    }

    private func attachMotion(_ events: @escaping @Sendable (GlassesEvent) -> Void) {
        guard lock.withLock({ motion == nil }), let session = lock.withLock({ session }) else { return }
        do {
            guard let m = try session.addMotion(configuration: MotionConfiguration(samplingRate: .hz30)) else {
                // The session is up even when Motion is not offered: the glasses are connected, steps come from the phone.
                GlassesLog.shared.log("dat_motion", ["available": false])
                events(.state(.connected)); return
            }
            lock.withLock { motion = m }
            m.start()
            events(.state(.connected))
            let reader = Task {
                var batch: [IMUSample] = []
                var first = true
                for await s in m.samples {
                    guard let a = s.accelerometer else { continue }
                    if first { first = false; GlassesLog.shared.log("dat_motion", ["available": true, "samples": true]) }
                    batch.append(IMUSample(t: Double(s.timestampNs) / 1e9, accel: SIMD3(a.x, a.y, a.z)))
                    if batch.count >= 6 { events(.imu(batch)); batch.removeAll(keepingCapacity: true) }
                }
            }
            lock.withLock { tasks.append(reader) }
        } catch {
            GlassesLog.shared.log("dat_motion", ["available": false, "error": "\(error)"])
            events(.state(.connected))
        }
    }

    // MARK: camera

    func setCamera(_ on: Bool) async {
        let changed = lock.withLock { () -> Bool in let c = wantCamera != on; wantCamera = on; return c }
        guard changed else { return }
        GlassesLog.shared.log("dat_camera_wanted", ["on": on])
        if on {
            // Permission lives in the Meta AI app. Never open it mid-walk: say what is missing instead.
            let status = await Self.cameraPermission()
            guard status == "granted" else {
                lock.withLock { wantCamera = false }
                lock.withLock { events }?(.camera(.needsPermission, note: status)); return
            }
        }
        applyCamera()
    }

    private func applyCamera() {
        let (want, up, s, ev, cam) = lock.withLock { (wantCamera, started, session, events, camera) }
        guard let ev else { return }
        if !want {
            guard let cam else { return }
            cam.stream.stop(); cam.stop()
            let tokens = lock.withLock { () -> [any AnyListenerToken] in camera = nil; defer { cameraTokens = [] }; return cameraTokens }
            Task { for t in tokens { await t.cancel() } }
            ev(.camera(.off, note: nil))
            return
        }
        guard up, let s, cam == nil else { return }
        do {
            // Lowest resolution and frame rate the toolkit offers: Live takes one picture a second at most.
            // `.raw` frames are delivered only while the app is in the foreground (toolkit reference, VideoCodec):
            // with the phone locked the voice goes on and seeing pauses; the walk says so.
            guard let c = try s.addCamera(config: StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 2)) else {
                ev(.camera(.failed, note: "These glasses did not offer a camera stream.")); return
            }
            ev(.camera(.starting, note: nil))
            let stream = c.stream
            let a = stream.statePublisher.listen { st in
                GlassesLog.shared.log("dat_stream", ["state": "\(st)"])
                switch st {
                case .streaming: break   // reported with the first frame that really arrives
                case .paused: ev(.camera(.paused, note: nil))
                case .stopped: ev(.camera(.off, note: nil))
                default: break
                }
            }
            let b = stream.errorPublisher.listen { e in
                ev(.problem("Glasses camera: \(e.description)"))
                ev(.camera(.failed, note: e.description))
            }
            let f = stream.videoFramePublisher.listen { [weak self] frame in self?.take(frame, ev) }
            lock.withLock { camera = c; cameraTokens = [a, b, f] }
            stream.start()
        } catch {
            ev(.problem("Glasses camera could not be added: \(error.description)"))
            ev(.camera(.failed, note: error.description))
        }
    }

    /// About one frame a second leaves this method as a small JPEG; every other frame is dropped at once.
    private func take(_ frame: VideoFrame, _ ev: @Sendable (GlassesEvent) -> Void) {
        let now = Date()
        let go = lock.withLock { () -> Bool in
            guard wantCamera, !encoding, now.timeIntervalSince(lastFrame) >= GlassesVision.minInterval else { return false }
            encoding = true; lastFrame = now; return true
        }
        guard go else { return }
        defer { lock.withLock { encoding = false } }
        guard let cg = Self.cgImage(frame), let out = GlassesVision.encode(cg) else { return }
        ev(.frame(out))
    }

    func stop() async {
        let (ts, m, c, s, cts, dts) = lock.withLock { () -> ([Task<Void, Never>], Motion?, Camera?, DeviceSession?, [any AnyListenerToken], [any AnyListenerToken]) in
            defer { tasks = []; motion = nil; camera = nil; session = nil; cameraTokens = []; deviceTokens = []; wantCamera = false; started = false; events = nil }
            return (tasks, motion, camera, session, cameraTokens, deviceTokens)
        }
        ts.forEach { $0.cancel() }
        m?.stop()
        c?.stream.stop(); c?.stop()
        s?.stop()
        for t in cts + dts { await t.cancel() }
        Self.walkActive = false
        GlassesLog.shared.log("dat_stop")
    }

    private static let ci = CIContext()
    /// The toolkit's own conversion first; raw pixel buffers through Core Image when that gives nothing.
    static func cgImage(_ frame: VideoFrame) -> CGImage? {
        if let cg = frame.makeUIImage()?.cgImage { return cg }
        guard let pb = CMSampleBufferGetImageBuffer(frame.sampleBuffer) else { return nil }
        let image = CIImage(cvPixelBuffer: pb)
        return ci.createCGImage(image, from: image.extent)
    }

    /// The selector reports its active device a moment after the glasses link comes up; creating a session
    /// before that throws `noEligibleDevice` (seen with Mock Device Kit). Wait for it, then fall back to the
    /// first known device by id.
    static func makeSession() async throws -> DeviceSession {
        let w = Wearables.shared
        let auto = AutoDeviceSelector(wearables: w)
        for _ in 0..<30 where auto.activeDevice == nil { try? await Task.sleep(nanoseconds: 200_000_000) }
        GlassesLog.shared.log("dat_selector", ["active": auto.activeDevice != nil, "devices": w.devices.count])
        do { return try w.createSession(deviceSelector: auto) }
        catch DeviceSessionError.noEligibleDevice {
            guard let id = w.devices.first else { throw DeviceSessionError.noEligibleDevice }
            return try w.createSession(deviceSelector: SpecificDeviceSelector(device: id))
        }
    }

    // MARK: words for the check screen and the log

    static func word(_ s: RegistrationState) -> String {
        switch s {
        case .registered: return "registered"
        case .registering: return "registering"
        case .available: return "not registered"
        case .unavailable: return "unavailable (is the Meta AI app installed?)"
        @unknown default: return "unknown"
        }
    }
    static func word(_ s: LinkState) -> String { s == .connected ? "connected" : s == .connecting ? "connecting" : "disconnected" }
    static func word(_ s: DonState) -> String { s == .donned ? "on" : s == .doffed ? "off" : "unknown" }
    static func word(_ s: HingeState) -> String { s == .open ? "open" : s == .closed ? "folded" : "unknown" }

    static func cameraPermission() async -> String {
        do { return try await Wearables.shared.checkPermissionStatus(.camera) == .granted ? "granted" : "not granted" }
        catch { return "unknown (\(error.description))" }
    }

    #if DEBUG && canImport(MWDATMockDevice)
    /// Mock Device Kit: one simulated pair of Ray-Ban Meta glasses, worn, with a 10-minute synthetic walking feed
    /// and a generated video as the camera feed, staged before the capabilities start.
    @MainActor private static var mockReady = false
    @MainActor
    static func prepareMock() async throws {
        if mockReady { return }
        mockReady = true
        let kit = MockDeviceKit.shared
        if !kit.isEnabled { kit.enable(config: MockDeviceKitConfig(initiallyRegistered: true, initialPermissionsGranted: true)) }
        let glasses: any MWDATMockDevice.MockGlasses
        if let g = kit.pairedDevices.first as? any MWDATMockDevice.MockGlasses { glasses = g } else { glasses = try kit.pairGlasses(model: .rayBanMeta) }
        glasses.powerOn()
        glasses.unfold()
        glasses.don()
        var gen = MockGait(cadence: 106)
        let samples = gen.next(seconds: 600).map { s in
            MWDATMockDevice.MotionSample(timestampNs: Int64(s.t * 1e9),
                                         accelerometer: MWDATMockDevice.Vector3(x: s.accel.x, y: s.accel.y, z: s.accel.z),
                                         source: .glasses)
        }
        glasses.services.motion.setMotionFeed(samples)
        let video = await MockFeed.video()
        if let video { glasses.services.camera.setCameraFeed(fileURL: video) }
        GlassesLog.shared.log("dat_mock_feed", ["video": video != nil])
        GlassesLog.shared.log("dat_mock_ready")
    }
    #endif
}

/// The toolkit for the Glasses check screen: what it reports, the camera permission request, one test frame.
final class DATControl: GlassesControl, @unchecked Sendable {
    let mock: Bool
    init(mock: Bool) { self.mock = mock }

    private func ready() async -> Bool {
        do {
            try DATGlasses.configureSDK()
            #if DEBUG && canImport(MWDATMockDevice)
            if mock { try await DATGlasses.prepareMock() }
            #endif
            return true
        } catch { return false }
    }

    func snapshot() async -> GlassesSnapshot {
        var s = GlassesSnapshot()
        guard await ready() else { s.sdk = "toolkit could not be configured"; return s }
        let w = Wearables.shared
        s.sdk = mock ? "ready (simulated glasses)" : "ready"
        s.registration = DATGlasses.word(w.registrationState)
        if let id = w.devices.first, let d = w.deviceForIdentifier(id) {
            s.device = d.nameOrId(); s.model = d.deviceType().rawValue
            s.link = DATGlasses.word(d.linkState); s.worn = DATGlasses.word(d.donState)
            s.hinge = DATGlasses.word(d.hingeState); s.battery = d.batteryLevel
        }
        s.camera = w.registrationState == .registered ? await DATGlasses.cameraPermission() : "register first"
        return s
    }

    func requestCamera() async -> String {
        guard await ready() else { return "toolkit could not be configured" }
        do {
            let r = try await Wearables.shared.requestPermission(.camera)
            GlassesLog.shared.log("dat_camera_permission", ["granted": r == .granted])
            return r == .granted ? "granted" : "denied"
        } catch {
            GlassesLog.shared.log("error", ["where": "camera permission", "error": error.description])
            return "unknown (\(error.description))"
        }
    }

    func testFrame() async -> (frame: GlassesFrame?, note: String) {
        guard !DATGlasses.walkActive else { return (nil, "End the walk first.") }
        guard await ready() else { return (nil, "The glasses toolkit could not be configured.") }
        let w = Wearables.shared
        guard w.registrationState == .registered else { return (nil, "Kaiku is not registered in the Meta AI app yet.") }
        guard !w.devices.isEmpty else { return (nil, "No glasses found. Check they are connected in the Meta AI app, unfolded and on.") }
        let permission = await DATGlasses.cameraPermission()
        guard permission == "granted" else { return (nil, "Camera permission in Meta AI: \(permission).") }
        let box = FrameBox()
        var tokens: [any AnyListenerToken] = []
        var session: DeviceSession?
        var camera: Camera?
        var note = "No picture arrived within 15 seconds."
        do {
            let s = try await DATGlasses.makeSession()
            session = s
            let states = s.stateStream()
            try s.start()
            let begun = Date()
            var up = false
            for await st in states {
                GlassesLog.shared.log("selftest_session", ["state": st.description])
                if st == .started { up = true; break }
                if st == .stopped || Date().timeIntervalSince(begun) > 10 { break }
            }
            if up, let c = try s.addCamera(config: StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 2)) {
                camera = c
                tokens.append(c.stream.videoFramePublisher.listen { f in
                    guard box.frame == nil else { return }
                    guard let cg = DATGlasses.cgImage(f), let out = GlassesVision.encode(cg) else { box.note("a frame arrived but could not be decoded"); return }
                    box.set(out)
                })
                tokens.append(c.stream.errorPublisher.listen { e in box.note(e.description) })
                tokens.append(c.stream.statePublisher.listen { st in GlassesLog.shared.log("selftest_stream", ["state": "\(st)"]) })
                c.stream.start()
                let end = Date().addingTimeInterval(15)
                while box.frame == nil, box.error == nil, Date() < end { try? await Task.sleep(nanoseconds: 150_000_000) }
                if let e = box.error { note = "Glasses camera: \(e)" }
            } else {
                note = up ? "These glasses did not offer a camera stream." : "The glasses session did not start (are they on your face and unfolded?)."
            }
        } catch {
            note = "Glasses session: \((error as? any DatError)?.description ?? "\(error)")"
        }
        camera?.stream.stop(); camera?.stop()
        session?.stop()
        for t in tokens { await t.cancel() }
        return (box.frame, box.frame == nil ? note : "ok")
    }
}

private final class FrameBox: @unchecked Sendable {
    private let lock = NSLock()
    private var f: GlassesFrame?
    private var e: String?
    var frame: GlassesFrame? { lock.withLock { f } }
    var error: String? { lock.withLock { e } }
    func set(_ v: GlassesFrame) { lock.withLock { if f == nil { f = v } } }
    func note(_ v: String) { lock.withLock { e = v } }
}

#if DEBUG && canImport(MWDATMockDevice)
/// Mock Device Kit only takes h265 video (Meta docs, "Using a video file").
/// A four-second generated video (green ground, blue sky, a moving sun) for Mock Device Kit's camera feed.
enum MockFeed {
    static func video() async -> URL? {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("kaiku-mock-feed-hevc.mov")
        if FileManager.default.fileExists(atPath: url.path) { return url }
        guard let writer = try? AVAssetWriter(outputURL: url, fileType: .mov) else { return nil }
        let w = 360, h = 640
        let input = AVAssetWriterInput(mediaType: .video, outputSettings: [AVVideoCodecKey: AVVideoCodecType.hevc, AVVideoWidthKey: w, AVVideoHeightKey: h])
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA, kCVPixelBufferWidthKey as String: w, kCVPixelBufferHeightKey as String: h])
        writer.add(input)
        guard writer.startWriting() else { return nil }
        writer.startSession(atSourceTime: .zero)
        for i in 0..<60 {
            var pb: CVPixelBuffer?
            CVPixelBufferCreate(nil, w, h, kCVPixelFormatType_32BGRA, nil, &pb)
            guard let pb else { continue }
            CVPixelBufferLockBaseAddress(pb, [])
            if let ctx = CGContext(data: CVPixelBufferGetBaseAddress(pb), width: w, height: h, bitsPerComponent: 8,
                                   bytesPerRow: CVPixelBufferGetBytesPerRow(pb), space: CGColorSpaceCreateDeviceRGB(),
                                   bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue) {
                ctx.setFillColor(UIColor(red: 0.55, green: 0.78, blue: 0.95, alpha: 1).cgColor); ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
                ctx.setFillColor(UIColor(red: 0.35, green: 0.65, blue: 0.35, alpha: 1).cgColor); ctx.fill(CGRect(x: 0, y: 0, width: w, height: h / 3))
                ctx.setFillColor(UIColor(red: 1, green: 0.85, blue: 0.3, alpha: 1).cgColor)
                ctx.fillEllipse(in: CGRect(x: 40 + i * 4, y: h - 200, width: 90, height: 90))
            }
            CVPixelBufferUnlockBaseAddress(pb, [])
            while !input.isReadyForMoreMediaData { try? await Task.sleep(nanoseconds: 10_000_000) }
            adaptor.append(pb, withPresentationTime: CMTime(value: CMTimeValue(i), timescale: 15))
        }
        input.markAsFinished()
        await writer.finishWriting()
        return writer.status == .completed ? url : nil
    }
}
#endif
#endif

/// Which adapter a walk uses: `-kaikuGlasses mock|datmock|dat|none` (default: none in the simulator, DAT on a
/// device when the SDK is linked).
enum GlassesChoice {
    static func make() -> GlassesAdapter? {
        let choice = UserDefaults.standard.string(forKey: "kaikuGlasses") ?? defaultChoice
        let drop = UserDefaults.standard.double(forKey: "kaikuGlassesDropAfter")
        switch choice {
        case "none": return nil
        #if canImport(MWDATCore) && canImport(MWDATMotion) && canImport(MWDATCamera)
        case "dat": return DATGlasses(useMockDeviceKit: false)
        #if DEBUG && canImport(MWDATMockDevice)
        case "datmock": return DATGlasses(useMockDeviceKit: true)
        #endif
        #endif
        #if DEBUG
        case "mock": return KaikuKit.MockGlasses(dropAfter: drop > 0 ? drop : nil)
        #endif
        default: return nil
        }
    }

    static var defaultChoice: String {
        #if targetEnvironment(simulator)
        return "none"
        #else
        #if canImport(MWDATCore) && canImport(MWDATMotion) && canImport(MWDATCamera)
        return "dat"
        #else
        return "none"
        #endif
        #endif
    }
}

extension GlassesChoice {
    /// The toolkit handle for the Glasses check screen (nil where the SDK is not linked or glasses are off).
    static func control() -> (any GlassesControl)? {
        #if canImport(MWDATCore) && canImport(MWDATMotion) && canImport(MWDATCamera)
        switch UserDefaults.standard.string(forKey: "kaikuGlasses") ?? defaultChoice {
        case "dat": return DATControl(mock: false)
        #if DEBUG && canImport(MWDATMockDevice)
        case "datmock": return DATControl(mock: true)
        #endif
        default: return nil
        }
        #else
        return nil
        #endif
    }
}
