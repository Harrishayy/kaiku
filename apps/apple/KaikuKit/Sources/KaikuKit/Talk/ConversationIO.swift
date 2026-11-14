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
    /// Before `start()`: false = playback only, the microphone is never opened (typed conversation).
    func setCapture(_ on: Bool)
    /// Kaiku's voice on / off at once; the audio keeps flowing (and "speaking" keeps its timing), just unheard.
    func setOutputMuted(_ on: Bool)
}
extension ConversationAudioIO {
    func resumeAfterInterruption() {}
    func setCapture(_ on: Bool) {}
    func setOutputMuted(_ on: Bool) {}
}
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
    /// The results of calls that arrived in one `toolCall` frame, answered in ONE `toolResponse` frame.
    func respond(_ answers: [ToolAnswer])
}
extension ConversationTransport {
    func sendVideo(_ jpeg: Data) {}
    func respond(_ answers: [ToolAnswer]) { answers.forEach { respond(id: $0.id, name: $0.name, result: $0.result) } }
}

/// One function call's result on its way back to the model.
struct ToolAnswer: Equatable, Sendable {
    var id: String
    var name: String
    var result: JSONValue
}
extension LiveSession: ConversationTransport {}
