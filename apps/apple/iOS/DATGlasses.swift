import Foundation
import KaikuKit

#if canImport(MWDATCore) && canImport(MWDATMotion)
import MWDATCore
import MWDATMotion
#if DEBUG && canImport(MWDATMockDevice)
import MWDATMockDevice
#endif

/// Meta glasses through the Wearables Device Access Toolkit (MWDAT 1.0.x, SPM). Motion (IMU) is a dev/beta-channel
/// capability. `useMockDeviceKit` pairs a simulated Ray-Ban Display from Mock Device Kit and replays a synthetic
/// walking feed, so the real SDK path (configure → session → addMotion → samples) runs without glasses.
/// Camera brightness (daylight minutes) is not wired yet: frames would need the camera capability + Wi-Fi setup.
final class DATGlasses: GlassesAdapter, @unchecked Sendable {
    let kind: String
    private let useMockDeviceKit: Bool
    private var session: DeviceSession?
    private var motion: Motion?
    private var tasks: [Task<Void, Never>] = []
    private static var configured = false

    init(useMockDeviceKit: Bool) {
        self.useMockDeviceKit = useMockDeviceKit
        kind = useMockDeviceKit ? "dat-mock" : "dat"
    }

    func start(_ events: @escaping @Sendable (GlassesEvent) -> Void) async {
        events(.state(.searching))
        do {
            // configure() first: enabling Mock Device Kit before it makes configure() throw (tried, 1.0.1)
            if !Self.configured { try Wearables.configure(); Self.configured = true }
            #if DEBUG && canImport(MWDATMockDevice)
            if useMockDeviceKit { try await Self.prepareMock() }
            #endif
            let wearables = Wearables.shared
            // devices arrive asynchronously (real glasses over BLE, or the mock pairing): wait up to 8 s
            for _ in 0..<40 where wearables.devices.isEmpty { try? await Task.sleep(nanoseconds: 200_000_000) }
            let s = try wearables.createSession(deviceSelector: AutoDeviceSelector(wearables: wearables))
            session = s
            let states = s.stateStream()
            try s.start()
            let watcher = Task { [weak self] in
                for await st in states {
                    switch st {
                    case .started:
                        self?.attachMotion(events)
                        events(.state(.connected))
                    case .paused: events(.state(.searching))
                    case .stopped: events(.state(.disconnected)); return
                    default: break
                    }
                }
            }
            tasks.append(watcher)
        } catch {
            kaikuDATLog("dat_start_failed \(error)")
            events(.state(.disconnected))
        }
    }

    private func attachMotion(_ events: @escaping @Sendable (GlassesEvent) -> Void) {
        guard motion == nil, let session else { return }
        do {
            guard let m = try session.addMotion(configuration: MotionConfiguration(samplingRate: .hz30)) else { return }
            motion = m
            m.start()
            let reader = Task {
                var batch: [IMUSample] = []
                for await s in m.samples {
                    guard let a = s.accelerometer else { continue }
                    batch.append(IMUSample(t: Double(s.timestampNs) / 1e9, accel: SIMD3(a.x, a.y, a.z)))
                    if batch.count >= 6 { events(.imu(batch)); batch.removeAll(keepingCapacity: true) }
                }
            }
            tasks.append(reader)
        } catch {
            kaikuDATLog("dat_motion_failed \(error)")
        }
    }

    func stop() async {
        tasks.forEach { $0.cancel() }
        tasks = []
        motion?.stop()
        motion = nil
        session?.stop()
        session = nil
    }

    #if DEBUG && canImport(MWDATMockDevice)
    /// Mock Device Kit: one simulated pair of glasses, worn, with a 10-minute synthetic walking feed staged
    /// before Motion starts (iOS ignores a feed set mid-stream).
    @MainActor
    static func prepareMock() async throws {
        let kit = MockDeviceKit.shared
        if !kit.isEnabled { kit.enable(config: MockDeviceKitConfig(initiallyRegistered: true, initialPermissionsGranted: true)) }
        let glasses: any MWDATMockDevice.MockGlasses
        if let g = kit.pairedDevices.first as? any MWDATMockDevice.MockGlasses { glasses = g } else { glasses = try kit.pairGlasses(model: .metaRayBanDisplay) }
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
    }
    #endif
}

func kaikuDATLog(_ s: String) { NSLog("kaiku %@", s) }
#endif

/// Which adapter a walk uses: `-kaikuGlasses mock|datmock|dat|none` (default: mock in the simulator, DAT on a
/// device when the SDK is linked).
enum GlassesChoice {
    static func make() -> GlassesAdapter? {
        let choice = UserDefaults.standard.string(forKey: "kaikuGlasses") ?? defaultChoice
        let drop = UserDefaults.standard.double(forKey: "kaikuGlassesDropAfter")
        switch choice {
        case "none": return nil
        #if canImport(MWDATCore) && canImport(MWDATMotion)
        case "dat": return DATGlasses(useMockDeviceKit: false)
        case "datmock": return DATGlasses(useMockDeviceKit: true)
        #endif
        default: return KaikuKit.MockGlasses(dropAfter: drop > 0 ? drop : nil)
        }
    }

    static var defaultChoice: String {
        #if targetEnvironment(simulator)
        return "mock"
        #else
        #if canImport(MWDATCore) && canImport(MWDATMotion)
        return "dat"
        #else
        return "mock"
        #endif
        #endif
    }
}
