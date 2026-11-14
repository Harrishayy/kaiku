import SwiftUI

// A conversation with Kaiku is a call: you can mute yourself, you can mute Kaiku, and the words of both keep
// coming as captions. These are the pieces every surface of that call shares (Talk, the check-in chat, the Mac
// quick-talk panel, the iPhone Live Activity): the one short state, the call bar and the activity card.

/// The call's one short state (pure; the same words on the call bar, the Lock Screen and the Dynamic Island).
public enum CallStatus: String, Codable, Sendable, CaseIterable {
    case connecting, listening, speaking, thinking, muted, micOff, paused

    /// Paused and connecting first; then what Kaiku is doing; then the person's own mute.
    public init(phase: Conversation.Phase, listens: Bool, micMuted: Bool, kaikuSpeaking: Bool) {
        switch phase {
        case .connecting, .idle, .unavailable: self = .connecting
        case .paused: self = .paused
        default:
            if kaikuSpeaking || phase == .speaking { self = .speaking }
            else if !listens { self = .micOff }
            else if micMuted || phase == .muted { self = .muted }
            else if phase == .thinking { self = .thinking }
            else { self = .listening }
        }
    }

    @MainActor public init(_ c: Conversation) {
        self.init(phase: c.phase, listens: c.listens, micMuted: c.micMuted, kaikuSpeaking: c.kaikuSpeaking)
    }

    public var key: String { "call.state.\(rawValue)" }
    public var symbol: String {
        switch self {
        case .connecting: return "ellipsis"
        case .listening: return "waveform"
        case .speaking: return "speaker.wave.2.fill"
        case .thinking: return "ellipsis.bubble"
        case .muted, .micOff: return "mic.slash.fill"
        case .paused: return "pause.fill"
        }
    }
}

/// The call bar: how long it has been going, the one short state, mute me, mute Kaiku, type, end.
public struct CallBar: View {
    let since: Date?
    let status: CallStatus
    let micOn: Bool
    let voiceMuted: Bool
    /// Nil hides the control (no keyboard on this surface).
    var typing: Bool? = nil
    let toggleMic: () -> Void
    let toggleVoice: () -> Void
    var toggleTyping: (() -> Void)? = nil
    let end: () -> Void

    public init(since: Date?, status: CallStatus, micOn: Bool, voiceMuted: Bool, typing: Bool? = nil,
                toggleMic: @escaping () -> Void, toggleVoice: @escaping () -> Void, toggleTyping: (() -> Void)? = nil,
                end: @escaping () -> Void) {
        self.since = since; self.status = status; self.micOn = micOn; self.voiceMuted = voiceMuted; self.typing = typing
        self.toggleMic = toggleMic; self.toggleVoice = toggleVoice; self.toggleTyping = toggleTyping; self.end = end
    }

    /// Not yet on the line, or everything paused: the microphone and typing wait (shown dimmed, never as "muted").
    private var waiting: Bool { status == .connecting || status == .paused }

    public var body: some View {
        VStack(spacing: KaikuTokens.Space.s2) {
            HStack(spacing: KaikuTokens.Space.s2) {
                Image(systemName: status.symbol).foregroundStyle(micOn ? KaikuTokens.Colors.sage : KaikuTokens.Colors.muted)
                    .accessibilityHidden(true)
                Text(T(status.key) + (voiceMuted && status == .speaking ? " · " + T("call.kaiku.muted") : ""))
                    .foregroundStyle(KaikuTokens.Colors.ink).lineLimit(1).minimumScaleFactor(0.8)
                if let since {
                    Text(since, style: .timer).monospacedDigit().foregroundStyle(KaikuTokens.Colors.muted)
                        .accessibilityLabel(T("call.a11y.time"))
                }
            }
            .kText(.footnote, weight: .medium)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("call.state")
            HStack(spacing: KaikuTokens.Space.s4) {
                IconButton(micOn || waiting ? "mic.fill" : "mic.slash.fill", label: T(micOn || waiting ? "call.mute.me" : "call.unmute.me"),
                           filled: !micOn && !waiting, action: toggleMic)
                    .disabled(waiting).opacity(waiting ? 0.45 : 1)
                    .accessibilityIdentifier("call.mic")
                IconButton(voiceMuted ? "speaker.slash.fill" : "speaker.wave.2.fill",
                           label: T(voiceMuted ? "call.unmute.kaiku" : "call.mute.kaiku"), filled: voiceMuted, action: toggleVoice)
                    .accessibilityIdentifier("call.voice")
                if let typing, let toggleTyping {
                    IconButton(typing ? "keyboard.chevron.compact.down" : "keyboard", label: T("call.type"), action: toggleTyping)
                        .disabled(waiting).opacity(waiting ? 0.45 : 1)
                        .accessibilityIdentifier("call.type")
                }
                Button(action: end) {
                    Image(systemName: "phone.down.fill").kText(.body, weight: .semibold)
                        .foregroundStyle(KaikuTokens.Colors.bg)
                        .frame(width: KaikuTokens.Size.tapMin * 1.4, height: KaikuTokens.Size.tapMin)
                        .background(Capsule().fill(KaikuTokens.Colors.ink))
                        .contentShape(Capsule())
                }
                .buttonStyle(.kPress)
                .accessibilityLabel(T("call.end"))
                .accessibilityIdentifier("call.end")
            }
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .frame(maxWidth: .infinity)
        .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.surface)
            .kaikuShadow(KaikuTokens.Elevation.card))
        .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
    }
}

/// One activity Kaiku suggests in a conversation, as a card: from the `suggest_activity` tool, or from what the
/// `feel` plan may offer. One at a time; a card that was put aside does not come back in that conversation.
public struct ActivityCard: Equatable, Sendable {
    /// breathe | tell | walk | lantern | seeds | watering | pebbles | firefly.
    public let kind: String
    /// Kaiku's own short line for it, when it gave one.
    public let line: String?
    /// Where the button goes.
    public let route: KaikuRoute

    public init?(kind raw: String, line: String? = nil, phone: Bool = KaikuPlatform.isPhone) {
        let kind = raw.lowercased()
        guard let route = Self.route(kind, phone: phone) else { return nil }
        self.kind = kind; self.route = route
        self.line = line?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
    }

    /// What the `feel` plan may offer, when it is an activity this device has a screen for. An offer without one
    /// (`offer_activity` null, or the robot's) stays Kaiku's spoken words: no card.
    public init?(plan: FeelPlan, phone: Bool = KaikuPlatform.isPhone) {
        guard let offered = plan.mayOffer?.trimmingCharacters(in: .whitespacesAndNewlines), !offered.isEmpty,
              let a = plan.offerActivity?.lowercased(), let r = Self.route(a, phone: phone) else { return nil }
        kind = a; route = r
        line = offered.prefix(1).uppercased() + offered.dropFirst() + (offered.hasSuffix("?") ? "" : "?")
    }

    /// The activities this device can open (contracts: companion_tools.Activity; the drum and the light hunt
    /// belong to the robot and the glasses walk, the Mac has no walk).
    public static func route(_ kind: String, phone: Bool = KaikuPlatform.isPhone) -> KaikuRoute? {
        switch kind {
        case "breathe": return .breathe
        case "tell": return .tell
        case "walk": return phone ? .walk : nil
        case "lantern": return .lantern
        case "seeds": return .seeds
        case "watering": return .watering
        case "pebbles": return .pebbles
        case "firefly": return .firefly
        default: return nil
        }
    }

    public var titleKey: String { kind == "walk" ? "card.walk.t" : "game.\(kind).t" }
    public var minutes: Int? {
        switch kind {
        case "walk": return 15
        default: return PlayGame(rawValue: kind).map { max(1, Int((Double(GameRotation.seconds($0)) / 60).rounded())) }
        }
    }
    public var icon: String {
        switch kind {
        case "breathe": return "wind"
        case "tell": return "ear.fill"
        case "walk": return "figure.walk"
        case "lantern": return "lightbulb.fill"
        case "seeds": return "leaf.fill"
        case "watering": return "drop.fill"
        case "pebbles": return "circle.grid.2x1.fill"
        default: return "sparkles"
        }
    }
    public var tone: KTone { ["walk": .sage, "breathe": .sage, "seeds": .sage, "lantern": .honey, "firefly": .honey, "tell": .clay, "watering": .clay][kind] ?? .sky }

    /// What Live is told (context text, not said by the person).
    public var openedText: String { "The person opened the \(kind) card." }
    public var asideText: String { "The person put the \(kind) card aside." }
}

/// The card: icon, name, minutes when known, one button that goes there, a small way to put it aside.
public struct ActivityCardView: View {
    let card: ActivityCard
    let open: () -> Void
    let putAside: () -> Void

    public init(card: ActivityCard, open: @escaping () -> Void, putAside: @escaping () -> Void) {
        self.card = card; self.open = open; self.putAside = putAside
    }

    public var body: some View {
        HStack(spacing: KaikuTokens.Space.s3) {
            Image(systemName: card.icon).kText(.callout, weight: .semibold).foregroundStyle(card.tone.ink)
                .frame(width: KaikuTokens.Size.iconTile, height: KaikuTokens.Size.iconTile)
                .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.sm, style: .continuous).fill(card.tone.soft))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 0) {
                Text(T(card.titleKey)).kText(.callout, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                if let minutes = card.minutes {
                    Text(T("game.time", n: minutes)).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted)
                }
            }
            Spacer(minLength: KaikuTokens.Space.s2)
            Button(T("card.open"), action: open)
                .buttonStyle(KButtonStyle(.primary, fullWidth: false))
                .accessibilityIdentifier("card.open")
            Button(action: putAside) {
                Image(systemName: "xmark").kText(.footnote, weight: .bold).foregroundStyle(KaikuTokens.Colors.muted)
                    .frame(width: KaikuTokens.Size.tapMin, height: KaikuTokens.Size.tapMin).contentShape(Rectangle())
            }
            .buttonStyle(.kPress)
            .accessibilityLabel(T("card.aside"))
            .accessibilityIdentifier("card.aside")
        }
        .padding(.leading, KaikuTokens.Space.s3)
        .padding(.vertical, KaikuTokens.Space.s2)
        .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.surface)
            .kaikuShadow(KaikuTokens.Elevation.card))
        .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("activity.card")
        .transition(.opacity)
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
