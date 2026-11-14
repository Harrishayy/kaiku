@preconcurrency import AVFoundation
import Foundation

/// The Talk audio session (plan 05 §2): play-and-record, voice-chat mode (voice-processing I/O = echo
/// cancellation), Bluetooth HFP allowed so Meta glasses / AirPods work as mic + speaker, speaker by default.
/// Also turns AVAudioSession interruptions (phone call, Siri, alarm) and route changes into simple events.
public enum TalkAudio {
    public enum Event: Equatable, Sendable {
        case interrupted
        case resumed(shouldResume: Bool)
        /// The output moved (glasses / AirPods connected or gone). `name` is the new output's name.
        case routeChanged(name: String)
    }

    /// Where sound comes in and goes out right now, in the system's own words.
    public struct Route: Equatable, Sendable {
        public var input = ""
        public var inputType = ""
        public var output = ""
        public var outputType = ""
        public init() {}
        /// The microphone is a Bluetooth hands-free device (Meta glasses, AirPods).
        public var headsetMic: Bool { inputType == "BluetoothHFP" }
        public var headsetOut: Bool { ["BluetoothHFP", "BluetoothA2DPOutput", "BluetoothLE"].contains(outputType) }
        /// Both directions go through the same hands-free device: the voice-in-the-ear case.
        public var inTheEar: Bool { headsetMic && outputType == "BluetoothHFP" }
        public var active: Bool { !input.isEmpty || !output.isEmpty }
    }

    public static var route: Route {
        var r = Route()
        #if os(iOS)
        let cur = AVAudioSession.sharedInstance().currentRoute
        if let i = cur.inputs.first { r.input = i.portName; r.inputType = i.portType.rawValue }
        if let o = cur.outputs.first { r.output = o.portName; r.outputType = o.portType.rawValue }
        #endif
        return r
    }

    /// A hands-free Bluetooth microphone the system could use (name), without opening the microphone.
    /// Sets the conversation category so the system lists Bluetooth inputs; does not activate the session.
    public static var headsetAvailable: String? {
        #if os(iOS)
        let s = AVAudioSession.sharedInstance()
        if s.category != .playAndRecord { try? configure(s) }
        return s.availableInputs?.first(where: { $0.portType == .bluetoothHFP })?.portName
        #else
        return nil
        #endif
    }

    #if os(iOS)
    private static func configure(_ s: AVAudioSession) throws {
        var opts: AVAudioSession.CategoryOptions = [.defaultToSpeaker]
        if #available(iOS 26.0, *) { opts.insert(.allowBluetoothHFP) } else { opts.insert(.allowBluetooth) }
        try s.setCategory(.playAndRecord, mode: .voiceChat, options: opts)
    }
    #endif

    /// Waits until the hands-free route is really carrying the microphone (Meta DAT docs, "Wait for the route to
    /// settle": start the camera stream only after this). False = no headset, the phone carries the conversation.
    public static func settleHeadset(timeout: TimeInterval = 3) async -> Bool {
        #if os(iOS)
        guard AVAudioSession.sharedInstance().availableInputs?.contains(where: { $0.portType == .bluetoothHFP }) == true else { return false }
        let end = Date().addingTimeInterval(timeout)
        while Date() < end {
            if route.headsetMic { return true }
            preferHeadsetInput()
            try? await Task.sleep(nanoseconds: 250_000_000)
        }
        return route.headsetMic
        #else
        return false
        #endif
    }

    public static func activate() throws {
        #if os(iOS)
        let s = AVAudioSession.sharedInstance()
        try configure(s)
        try s.setActive(true)
        #endif
    }

    /// Meta glasses (or another HFP headset) connected → take their mic (Meta DAT docs: pick the `.bluetoothHFP`
    /// port with `setPreferredInput`; the glasses beamform to the wearer's voice). No headset → system default.
    public static func preferHeadsetInput() {
        #if os(iOS)
        let s = AVAudioSession.sharedInstance()
        if let hfp = s.availableInputs?.first(where: { $0.portType == .bluetoothHFP }) {
            try? s.setPreferredInput(hfp)
        }
        #endif
    }

    /// The output is a pair of Meta glasses (port name from the Bluetooth device, e.g. "Ray-Ban Meta").
    public static var glassesConnected: Bool {
        #if os(iOS)
        let r = AVAudioSession.sharedInstance().currentRoute
        return (r.inputs + r.outputs).contains { $0.portType == .bluetoothHFP && $0.portName.localizedCaseInsensitiveContains("meta") }
        #else
        return false
        #endif
    }

    public static func deactivate() {
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        #endif
    }

    /// The current output's name ("Speaker", "Ray-Ban Meta", "AirPods").
    public static var outputName: String {
        #if os(iOS)
        return AVAudioSession.sharedInstance().currentRoute.outputs.first?.portName ?? ""
        #else
        return ""
        #endif
    }

    /// Observes interruptions and route changes until the returned token is released.
    public static func observe(_ handler: @escaping @MainActor (Event) -> Void) -> [NSObjectProtocol] {
        #if os(iOS)
        let nc = NotificationCenter.default
        let a = nc.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { n in
            guard let raw = n.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                  let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
            let optRaw = n.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0
            let resume = AVAudioSession.InterruptionOptions(rawValue: optRaw).contains(.shouldResume)
            MainActor.assumeIsolated { handler(type == .began ? .interrupted : .resumed(shouldResume: resume)) }
        }
        let b = nc.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil, queue: .main) { n in
            guard let raw = n.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt,
                  let reason = AVAudioSession.RouteChangeReason(rawValue: raw),
                  [.newDeviceAvailable, .oldDeviceUnavailable, .override, .routeConfigurationChange].contains(reason) else { return }
            let name = outputName
            MainActor.assumeIsolated { handler(.routeChanged(name: name)) }
        }
        return [a, b]
        #else
        return []
        #endif
    }
}
