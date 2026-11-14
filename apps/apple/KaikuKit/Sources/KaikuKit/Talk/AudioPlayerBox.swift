import AVFoundation

/// Plays a short wav (Kaiku's voice sample from GET /v1/voice/{key}). Kept in memory only.
final class AVAudioPlayerBox {
    private let player: AVAudioPlayer?
    init(_ data: Data) { player = try? AVAudioPlayer(data: data) }
    func play() { player?.play() }
}
