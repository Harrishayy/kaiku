import Foundation
import Observation
import SwiftUI

/// This device's own bookkeeping for the choice "Camera during activities": which wording of it the person has
/// agreed to, and which face-sign summaries this device sent today (for the day's receipt: the list is true
/// whether or not the service already knows the observation type). Numbers of the summaries are not kept here.
@Observable @MainActor final class CameraChoice {
    /// The wording of the choice now in the app (`sig.camera.d`). 1 said "face movement and expression geometry";
    /// 2 names what is derived: smiles, eyebrow and mouth movement, blinks, looking toward the screen, head and
    /// face movement; 3 adds who sees the numbers (she in History, her care team beside her record) and that they
    /// decide nothing; 4 adds the visible expression cues (D60): an expression that stays lower, more tense or
    /// brighter for a while, after which Kaiku may ask one gentle question. A choice made under an older wording does not cover the newer text: it is asked again
    /// once (`AppModel.cameraNeedsConfirm`), and until then the camera stays off.
    nonisolated static let wording = 4

    /// One summary this device sent: its envelope id, the game session it points at, and whether a stand-in made it.
    struct Sent: Codable, Equatable, Sendable {
        var id: String
        var ref: String?
        var sim: Bool
        var day: String
    }

    private(set) var agreedWording: Int { didSet { defaults.set(agreedWording, forKey: Self.wordingKey) } }
    private(set) var sent: [Sent] { didSet { defaults.set(try? JSONEncoder().encode(sent), forKey: Self.sentKey) } }
    @ObservationIgnored private let defaults: UserDefaults
    nonisolated static let wordingKey = "kaiku.camera.wording", sentKey = "kaiku.camera.sent"

    init(defaults: UserDefaults) {
        self.defaults = defaults
        agreedWording = defaults.integer(forKey: Self.wordingKey)
        let saved = defaults.data(forKey: Self.sentKey).flatMap { try? JSONDecoder().decode([Sent].self, from: $0) } ?? []
        sent = saved.filter { $0.day == AppModel.dayKey(Date()) }   // a receipt is for today
    }

    /// The person turned the choice on (or kept it on) with the whole current wording in front of them.
    func agree() { if agreedWording != Self.wording { agreedWording = Self.wording } }

    func sentToday(_ now: Date = Date()) -> [Sent] { let day = AppModel.dayKey(now); return sent.filter { $0.day == day } }

    func note(id: String, ref: String?, sim: Bool, now: Date = Date()) {
        let day = AppModel.dayKey(now)
        sent = sent.filter { $0.day == day && $0.id != id } + [Sent(id: id, ref: ref, sim: sim, day: day)]
    }

    /// Another home or service: what was sent belongs to the previous one.
    func clearSent() { if !sent.isEmpty { sent = [] } }
}

extension FaceSigns {
    /// The payload of one finished task's camera time. Shares to three places, a rate to one: more would be noise.
    /// A session with no usable face to speak of (a coverage that rounds to nothing) carries no sign at all, as
    /// the contract asks: a number from two frames out of thousands says nothing about the task.
    init(_ s: FaceSignsSummary, task: String, device: PlayDevice, ref: String?) {
        func places(_ v: Double?, _ n: Double) -> Double? { v.map { ($0 * n).rounded() / n } }
        func share(_ v: Double?) -> Double? { places(v.map { min(1, max(0, $0)) }, 1000) }
        let coverage = share(s.coverage) ?? 0
        let seen = coverage > 0
        self.init(task: task, device: device, method: s.method,
                  duration_s: min(86_400, max(0, (s.durationS * 10).rounded() / 10)), samples: s.samples, coverage: coverage,
                  smile_share: seen ? share(s.smileShare) : nil, smiles: seen ? s.smiles : nil,
                  brow_raise_share: seen ? share(s.browRaiseShare) : nil, brow_furrow_share: seen ? share(s.browFurrowShare) : nil,
                  mouth_open_share: seen ? share(s.mouthOpenShare) : nil,
                  blinks_per_min: seen ? places(s.blinksPerMin.map { max(0, $0) }, 10) : nil,
                  gaze_on_share: seen ? share(s.gazeOnShare) : nil,
                  head_movement: seen ? places(s.headMovement.map { max(0, $0) }, 100) : nil,
                  expression_range: seen ? share(s.expressionRange) : nil, ref: ref)
    }

    /// With the visible expression cues that held in the task (D60). None, or no usable face: the field is absent.
    init(_ result: TaskCameraResult, task: String, device: PlayDevice, ref: String?) {
        self.init(result.signs, task: task, device: device, ref: ref)
        if coverage > 0, !result.cues.isEmpty { cues = result.cues }
    }
}

extension AppModel {
    /// The choice is on, but not yet with the whole current wording in front of her: it was made under the older
    /// wording, or with a switch that shows only the short line (a game's start screen, the day's receipt). She is
    /// asked once, with the whole text (`CameraConfirmCard`), and until she answers the camera stays off.
    var cameraNeedsConfirm: Bool { (consents[.camera] ?? false) && cameraChoice.agreedWording < CameraChoice.wording }

    /// A switch for a choice on a screen that shows that choice's whole text (setup's "Your choices", You →
    /// Sharing and permissions with "In full" under the list). Turning the camera on there is agreeing to that text.
    func choiceBinding(_ signal: Signal) -> Binding<Bool> {
        Binding(get: { self.consents[signal] ?? false }, set: { on in
            self.consents[signal] = on
            if signal == .camera, on { self.cameraChoice.agree() }
        })
    }

    /// Whether a task may use the camera now: her choice (in its current wording), check-ins and games on, and
    /// nothing paused. The system's permission is the camera controller's own question.
    var cameraOn: Bool { allowed(.camera) && allowed(.checkins) && !cameraNeedsConfirm }

    /// Whether a few pictures of a check-in may go to Kaiku's own model (D65): her separate choice, on top of the
    /// camera choice. Off by default; either one off = no picture is ever made.
    var lookOn: Bool { cameraOn && allowed(.look) }

    /// Her answer to the one-time question: keep the choice on under the new wording, or turn it off.
    func confirmCamera(keep: Bool) {
        if keep { cameraChoice.agree() } else { consents[.camera] = false }
    }

    /// One task's face signs → obs.face_signs, through the same queue as every observation. `ref` is the id of
    /// the game session it belongs to. Nothing is sent unless the camera choice still stands at this moment.
    func recordFaceSigns(_ result: TaskCameraResult, task: String, ref: String? = nil) async {
        guard cameraOn, pairing != nil, result.signs.samples >= 1 else { return }
        let id = UUID7.make()
        cameraChoice.note(id: id, ref: ref, sim: result.simulated)
        await emit("obs.face_signs", FaceSigns(result, task: task, device: KaikuPlatform.device, ref: ref),
                   id: id, sim: result.simulated, quality: result.signs.coverage)
    }
}
