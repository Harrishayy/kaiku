@preconcurrency import AVFoundation
import Foundation

/// Production boundaries shared with controller tests; neither path bypasses Conversation.
protocol ConversationAudioIO: AnyObject, Sendable {
    var onPCM: ((Data) -> Void)? { get set }
    var onBuffer: ((AVAudioPCMBuffer) -> Void)? { get set }
    var onLevel: ((Float) -> Void)? { get set }
    var onPlaying: ((Bool) -> Void)? { get set }
    var onFailure: (() -> Void)? { get set }
    var isPlaying: Bool { get }
    func start() throws
    func stop()
    func setMic(_ on: Bool)
    func play(_ pcm: Data)
    func flush()
    /// Start capture/playback again after a system interruption ended (phone call, Siri, alarm).
    func resumeAfterInterruption()
}
extension ConversationAudioIO { func resumeAfterInterruption() {} }
extension ConversationAudio: ConversationAudioIO {}
protocol ConversationTransport: AnyObject, Sendable {
    func connect(token: String, session: CompanionSessionResponse, options: LiveSession.Options)
    func close()
    func sendAudio(_ pcm: Data)
    func audioStreamEnd()
    func sendText(_ text: String)
    func sendVideo(_ jpeg: Data)
    func sendContext(_ event: String)
    func respond(id: String, name: String, result: JSONValue)
}
extension ConversationTransport { func sendVideo(_ jpeg: Data) {} }
extension LiveSession: ConversationTransport {}
