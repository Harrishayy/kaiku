import SwiftUI

/// Light hunt on a walk (iPhone): Kaiku walking, "Find three green things", three dots, minutes, Found one /
/// End walk. The same walk shows in the Dynamic Island and on the Lock Screen (Live Activity) and can be driven
/// from there, from Siri ("Start a walk with Kaiku") or a glasses tap.
public struct WalkView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    private var walk = WalkModel.shared
    public init() {}

    public var body: some View {
        KScreen(T("game.lighthunt.t"), back: walk.active ? nil : { dismiss() }) {
            if walk.active {
                walking
            } else if walk.finished != nil {
                done
            } else {
                intro
            }
        }
        .onAppear {
            if app.defaultsAutostartWalk, !walk.active, walk.finished == nil { start() }
        }
    }

    private func start() { walk.begin(app: app, adapter: app.makeGlasses?()) }

    private var intro: some View {
        VStack(spacing: KaikuTokens.Space.s4) {
            MascotWithBubble(state: .walking, text: T("game.lighthunt.d"))
            GlassesLine(state: app.makeGlasses == nil ? .off : .searching, idle: true)
            Button(T("walk.begin")) { start() }.buttonStyle(.kPrimary)
        }
    }

    private var walking: some View {
        VStack(spacing: KaikuTokens.Space.s4) {
            MascotView(state: .walking, size: KaikuTokens.Size.mascotL, tappable: false)
                .frame(maxWidth: .infinity)
            Text(T("lh.find")).kText(.title2).foregroundStyle(KaikuTokens.Colors.ink).multilineTextAlignment(.center).wraps()
            FoundDots(found: walk.found)
            TimelineView(.periodic(from: .now, by: 15)) { _ in
                Text(T("walk.minutes", n: walk.minutes)).kText(.body).foregroundStyle(KaikuTokens.Colors.muted).wraps()
            }
            GlassesLine(state: walk.glasses, idle: false)
            if walk.companion != nil {
                Button(walk.companionMuted ? T("walk.talk.unmute") : T("walk.talk.mute")) {
                    walk.setTalking(walk.companionMuted)
                }
                .buttonStyle(.kSecondary)
                .accessibilityHint(T("walk.talk.on"))
            }
            VStack(spacing: KaikuTokens.Space.s2) {
                Button(T("lh.found")) { walk.foundOne() }.buttonStyle(.kPrimary).disabled(walk.found >= WalkModel.goal)
                Button(T("lh.end")) { Task { await walk.end() } }.buttonStyle(.kSecondary)
            }
        }
    }

    private var done: some View {
        VStack(spacing: KaikuTokens.Space.s4) {
            MascotWithBubble(state: .happy, text: T("walk.thanks"))
            Button(T("common.done")) { dismiss() }.buttonStyle(.kPrimary)
        }
        .onDisappear { WalkModel.shared.reset() }
    }
}

/// Three soft dots: found ones filled sage.
struct FoundDots: View {
    let found: Int
    var body: some View {
        HStack(spacing: KaikuTokens.Space.s3) {
            ForEach(0..<WalkModel.goal, id: \.self) { i in
                Circle()
                    .fill(i < found ? KaikuTokens.Colors.sage : KaikuTokens.Colors.surface)
                    .overlay(Circle().strokeBorder(KaikuTokens.Colors.sage, lineWidth: 2))
                    .frame(width: 22, height: 22)
            }
        }
        .accessibilityElement()
        .accessibilityLabel(T("lh.progress", n: found))
    }
}

/// "Glasses · Connected" (or searching / not set up / disconnected → the walk goes on on the phone).
struct GlassesLine: View {
    let state: GlassesState
    let idle: Bool
    var body: some View {
        HStack(spacing: KaikuTokens.Space.s2) {
            Image(systemName: "eyeglasses").foregroundStyle(state == .connected ? KaikuTokens.Colors.sage : KaikuTokens.Colors.muted)
            Text(label).kText(.footnote).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }

    var label: String {
        switch state {
        case .off: return idle ? T("walk.phone") : T("walk.phone")
        case .searching: return T("dev.connecting")
        case .connected: return T("walk.glasses.on")
        case .batteryLow: return T("dev.attn")
        case .disconnected: return T("walk.glasses.lost")
        }
    }
}

extension AppModel {
    /// `-kaikuAutostart YES` also starts a walk straight away (screenshots, UI tests).
    var defaultsAutostartWalk: Bool { UserDefaults.standard.bool(forKey: "kaikuAutostart") }
}

extension WalkModel {
    /// Back to the intro (after the thank-you screen).
    public func reset() { if !active { clearFinished() } }
}
