import Foundation
#if os(iOS) && canImport(ActivityKit)
import ActivityKit
#endif

/// What the call shows outside the app (iPhone Lock Screen and Dynamic Island): the one short state, whether the
/// microphone is really open, whether Kaiku's voice is muted, and the last few words. Never audio, never stored.
public struct CallSurfaceState: Codable, Hashable, Sendable {
    public var status: CallStatus
    public var micOn: Bool
    public var voiceMuted: Bool
    public var caption: String?
    public var captionMine: Bool
    public init(status: CallStatus, micOn: Bool, voiceMuted: Bool, caption: String? = nil, captionMine: Bool = false) {
        self.status = status; self.micOn = micOn; self.voiceMuted = voiceMuted; self.caption = caption; self.captionMine = captionMine
    }
}

/// The call's controls for buttons that live outside the views (Lock Screen, Dynamic Island, intents): they act on
/// the call that is open right now, in the app's process. `end()` really ends the session and closes the microphone.
@MainActor
public enum KaikuCall {
    public static var isOpen: Bool { TalkModel.active?.hasLive == true }
    public static func toggleMic() { TalkModel.active?.toggleMic() }
    public static func toggleVoice() { TalkModel.active?.toggleVoice() }
    public static func end() { TalkModel.active?.end() }
    /// At launch: a call bar left behind by a process that was killed mid-call is taken down (no call is open).
    public static func clearLeftovers() { if !isOpen { CallSurface.end() } }
}

#if os(iOS) && canImport(ActivityKit)
/// Live Activity for a call with Kaiku (follows the walk's pattern in Walk/KaikuActivities.swift; local updates, no push).
public struct CallActivityAttributes: ActivityAttributes {
    public typealias ContentState = CallSurfaceState
    public var startedAt: Date
    public var lang: String
    public init(startedAt: Date, lang: String) { self.startedAt = startedAt; self.lang = lang }
}
#endif

/// Starts / updates / ends the call's Live Activity. State changes go out at once; captions at most once a second
/// (they arrive word by word). It goes stale at the session's length limit, so a killed app never leaves a
/// "listening" bar on the Lock Screen.
@MainActor
enum CallSurface {
    private static var sent: CallSurfaceState?
    private static var sentAt = Date.distantPast
    private static var pending: Task<Void, Never>?
    private static var latest: (since: Date, state: CallSurfaceState, limit: TimeInterval)?

    static func show(since: Date, lang: String, state: CallSurfaceState, limit: TimeInterval) {
        #if os(iOS) && canImport(ActivityKit)
        guard ActivityAuthorizationInfo().areActivitiesEnabled, state != sent else { return }
        latest = (since, state, limit)
        var onlyCaption = sent
        onlyCaption?.caption = state.caption; onlyCaption?.captionMine = state.captionMine
        if onlyCaption == state, Date().timeIntervalSince(sentAt) < 1 {
            guard pending == nil else { return }
            pending = Task {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                pending = nil
                if let l = latest { push(since: l.since, lang: lang, state: l.state, limit: l.limit) }
            }
            return
        }
        push(since: since, lang: lang, state: state, limit: limit)
        #endif
    }

    /// The newest words of a caption for a small surface: a long line keeps its end, from a word boundary, led by
    /// an ellipsis (pure; tested).
    nonisolated static func tail(_ text: String, limit: Int = 110) -> String {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.count > limit else { return t }
        var end = Substring(t.suffix(limit))
        if let space = end.firstIndex(of: " ") { end = end[end.index(after: space)...] }
        return "…" + end
    }

    static func end() {
        #if os(iOS) && canImport(ActivityKit)
        pending?.cancel(); pending = nil; latest = nil; sent = nil
        for a in Activity<CallActivityAttributes>.activities { Task { await a.end(nil, dismissalPolicy: .immediate) } }
        #endif
    }

    #if os(iOS) && canImport(ActivityKit)
    private static func push(since: Date, lang: String, state: CallSurfaceState, limit: TimeInterval) {
        guard latest != nil else { return }
        sent = state; sentAt = Date()
        let content = ActivityContent(state: state, staleDate: since.addingTimeInterval(limit + 30))
        let running = Activity<CallActivityAttributes>.activities
        if running.isEmpty {
            _ = try? Activity.request(attributes: CallActivityAttributes(startedAt: since, lang: lang), content: content, pushType: nil)
        } else {
            for a in running { Task { await a.update(content) } }
        }
    }
    #endif
}
