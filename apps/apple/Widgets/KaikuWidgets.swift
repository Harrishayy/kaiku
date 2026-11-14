import ActivityKit
import KaikuKit
import SwiftUI
import WidgetKit

/// Widget extension: Walk + Breathe Live Activities (Dynamic Island + Lock Screen) and the Kaiku widget
/// (Home Screen small/medium, Lock Screen rectangular/circular). Look per design/ia.md → Walk surfaces; the island
/// is black in both themes (design/layout.md). Content views live in KaikuKit (`SurfaceViews.swift`) so the app's
/// layout snapshots render the same thing; the tiny compact/minimal slots use the high-contrast `KaikuGlyph`.
@main
struct KaikuWidgetBundle: WidgetBundle {
    var body: some Widget {
        KaikuHomeWidget()
        WalkLiveActivity()
        BreatheLiveActivity()
        CallLiveActivity()
    }
}

// MARK: - Walk

struct WalkLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: WalkActivityAttributes.self) { ctx in
            let lang = KaikuLanguage(rawValue: ctx.attributes.lang) ?? .en
            WalkLockContent(lang: lang, minutes: ctx.state.minutes,
                            goal: WalkGoalLine(thing: ctx.state.thing, target: ctx.state.target, found: ctx.state.found))
            .activityBackgroundTint(KaikuTokens.Colors.bg)
            .activitySystemActionForegroundColor(KaikuTokens.Colors.ink)
            .widgetURL(URL(string: "kaiku://walk"))
        } dynamicIsland: { ctx in
            let lang = KaikuLanguage(rawValue: ctx.attributes.lang) ?? .en
            let st = ctx.state
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    MascotView(state: .walking, size: SurfaceSize.islandMascot, tappable: false)
                        .frame(width: SurfaceSize.islandMascot, height: SurfaceSize.islandMascot)
                        .padding(.leading, 6)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    IslandMinutes(lang: lang, minutes: st.minutes).padding(.trailing, 6)
                }
                DynamicIslandExpandedRegion(.center) {
                    WalkIslandCenter(lang: lang, goal: WalkGoalLine(thing: st.thing, target: st.target, found: st.found))
                }
                DynamicIslandExpandedRegion(.bottom) {
                    HStack(spacing: 10) {
                        Button(intent: FoundOneIntent()) { Text(TL("lh.found", lang)).frame(maxWidth: .infinity) }
                            .tint(KaikuTokens.Colors.sage)
                        Button(intent: EndWalkIntent()) { Text(TL("lh.end", lang)).frame(maxWidth: .infinity) }
                            .tint(.white.opacity(0.25))
                    }
                    .font(.system(.subheadline, design: .rounded).weight(.semibold))
                    .buttonStyle(.borderedProminent)
                    .padding(.horizontal, 6)
                    .padding(.top, 6)
                }
            } compactLeading: {
                KaikuGlyph(state: .walking, size: SurfaceSize.glyph, phase: Double(st.minutes % 2))
            } compactTrailing: {
                Text(TL("la.min", lang, ["n": "\(st.minutes)"]))
                    .font(.system(.caption, design: .rounded).weight(.semibold))
                    .foregroundStyle(KaikuTokens.Colors.sage)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            } minimal: {
                KaikuGlyph(state: .walking, size: SurfaceSize.glyph - 2)
            }
            .widgetURL(URL(string: "kaiku://walk"))
            .keylineTint(KaikuTokens.Colors.sage)
        }
    }
}

// MARK: - Breathe

struct BreatheLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: BreatheActivityAttributes.self) { ctx in
            BreatheLockContent(lang: KaikuLanguage(rawValue: ctx.attributes.lang) ?? .en, breath: ctx.state.breath)
                .activityBackgroundTint(KaikuTokens.Colors.bg)
                .widgetURL(URL(string: "kaiku://breathe"))
        } dynamicIsland: { ctx in
            let lang = KaikuLanguage(rawValue: ctx.attributes.lang) ?? .en
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    MascotView(state: .breathing, size: SurfaceSize.islandMascot, tappable: false)
                        .frame(width: SurfaceSize.islandMascot, height: SurfaceSize.islandMascot)
                        .padding(.leading, 6)
                }
                DynamicIslandExpandedRegion(.center) {
                    BreatheIslandCenter(lang: lang, breath: ctx.state.breath)
                }
            } compactLeading: {
                KaikuGlyph(state: .breathing, size: SurfaceSize.glyph, phase: Double(ctx.state.breath % 2))
            } compactTrailing: {
                Text("\(ctx.state.breath)/\(ctx.state.total)")
                    .font(.system(.caption, design: .rounded).weight(.semibold)).foregroundStyle(KaikuTokens.Colors.sage)
            } minimal: {
                KaikuGlyph(state: .breathing, size: SurfaceSize.glyph - 2)
            }
            .widgetURL(URL(string: "kaiku://breathe"))
            .keylineTint(KaikuTokens.Colors.sage)
        }
    }
}

// MARK: - Call (Talk / check-in chat)

/// The call with Kaiku outside the app: how long, the one short state, whether the microphone is open, the last
/// few words, and buttons that act without opening the app (mute me, mute Kaiku, end).
struct CallLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: CallActivityAttributes.self) { ctx in
            let lang = KaikuLanguage(rawValue: ctx.attributes.lang) ?? .en
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 10) {
                    KaikuGlyph(state: ctx.state.status == .speaking ? .speaking : .listening, size: SurfaceSize.glyph + 6)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(TL("call.la.title", lang)).font(.system(.subheadline, design: .rounded).weight(.semibold))
                            .foregroundStyle(KaikuTokens.Colors.ink)
                        CallStateLine(state: ctx.state, lang: lang, tint: KaikuTokens.Colors.ink2, style: .footnote)
                    }
                    Spacer(minLength: 6)
                    CallClock(since: ctx.attributes.startedAt, stale: ctx.isStale).foregroundStyle(KaikuTokens.Colors.ink)
                }
                if let caption = ctx.state.caption, !caption.isEmpty {
                    Text(caption).font(.system(.footnote, design: .rounded)).foregroundStyle(KaikuTokens.Colors.ink2)
                        .lineLimit(2).frame(maxWidth: .infinity, alignment: ctx.state.captionMine ? .trailing : .leading)
                }
                CallButtons(state: ctx.state, lang: lang, tint: KaikuTokens.Colors.clay)
            }
            .padding(14)
            .activityBackgroundTint(KaikuTokens.Colors.bg)
            .activitySystemActionForegroundColor(KaikuTokens.Colors.ink)
            .widgetURL(URL(string: "kaiku://talk"))
        } dynamicIsland: { ctx in
            let lang = KaikuLanguage(rawValue: ctx.attributes.lang) ?? .en
            let st = ctx.state
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    MascotView(state: st.status == .speaking ? .speaking : .listening, size: SurfaceSize.islandMascot, tappable: false)
                        .frame(width: SurfaceSize.islandMascot, height: SurfaceSize.islandMascot)
                        .padding(.leading, 6)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    CallClock(since: ctx.attributes.startedAt, stale: ctx.isStale).foregroundStyle(.white).padding(.trailing, 6)
                }
                DynamicIslandExpandedRegion(.center) {
                    VStack(spacing: 2) {
                        CallStateLine(state: st, lang: lang, tint: .white)
                        if let caption = st.caption, !caption.isEmpty {
                            Text(caption).font(.system(.caption, design: .rounded)).foregroundStyle(.white.opacity(0.7)).lineLimit(1)
                        }
                    }
                }
                DynamicIslandExpandedRegion(.bottom) {
                    CallButtons(state: st, lang: lang, tint: KaikuTokens.Colors.sage).padding(.horizontal, 6).padding(.top, 6)
                }
            } compactLeading: {
                KaikuGlyph(state: st.status == .speaking ? .speaking : .listening, size: SurfaceSize.glyph)
            } compactTrailing: {
                Image(systemName: st.micOn ? "mic.fill" : "mic.slash.fill")
                    .font(.system(.caption, design: .rounded).weight(.semibold))
                    .foregroundStyle(st.micOn ? KaikuTokens.Colors.sage : .white.opacity(0.6))
            } minimal: {
                Image(systemName: st.micOn ? "mic.fill" : "mic.slash.fill")
                    .font(.system(.caption2).weight(.semibold))
                    .foregroundStyle(st.micOn ? KaikuTokens.Colors.sage : .white.opacity(0.6))
            }
            .widgetURL(URL(string: "kaiku://talk"))
            .keylineTint(KaikuTokens.Colors.sage)
        }
    }
}

/// "Listening" / "Kaiku is speaking" / "You are muted", with the microphone's true state as its icon.
struct CallStateLine: View {
    let state: CallSurfaceState
    let lang: KaikuLanguage
    let tint: Color
    var style: Font.TextStyle = .caption
    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: state.micOn ? "mic.fill" : "mic.slash.fill")
            Text(TL(state.status.key, lang) + (state.voiceMuted && state.status == .speaking ? " · " + TL("call.kaiku.muted", lang) : ""))
                .lineLimit(1).minimumScaleFactor(0.7)
        }
        .font(.system(style, design: .rounded).weight(.medium))
        .foregroundStyle(tint)
    }
}

/// How long the call has been going (it stops counting once the activity is stale: the call is over).
struct CallClock: View {
    let since: Date
    let stale: Bool
    var body: some View {
        Group {
            if stale { Image(systemName: "phone.down.fill") } else {
                Text(timerInterval: since...since.addingTimeInterval(4 * 3600), countsDown: false)
                    .monospacedDigit().multilineTextAlignment(.trailing).frame(maxWidth: 56)
            }
        }
        .font(.system(.subheadline, design: .rounded).weight(.semibold))
    }
}

/// Mute me · mute Kaiku · end: each acts on the open call in the app's process, without opening the app.
struct CallButtons: View {
    let state: CallSurfaceState
    let lang: KaikuLanguage
    let tint: Color
    var body: some View {
        HStack(spacing: 8) {
            Button(intent: ToggleCallMicIntent()) {
                Label(TL(state.micOn ? "call.la.mute" : "call.la.unmute", lang), systemImage: state.micOn ? "mic.slash.fill" : "mic.fill")
                    .frame(maxWidth: .infinity)
            }
            .tint(tint)
            .disabled(state.status == .micOff)
            Button(intent: ToggleCallVoiceIntent()) {
                Image(systemName: state.voiceMuted ? "speaker.slash.fill" : "speaker.wave.2.fill").frame(minWidth: 28)
            }
            .tint(.gray.opacity(0.45))
            .accessibilityLabel(TL(state.voiceMuted ? "call.unmute.kaiku" : "call.mute.kaiku", lang))
            Button(intent: EndCallIntent()) {
                Label(TL("call.la.end", lang), systemImage: "phone.down.fill").frame(maxWidth: .infinity)
            }
            .tint(.gray.opacity(0.45))
        }
        .font(.system(.subheadline, design: .rounded).weight(.semibold))
        .labelStyle(.titleAndIcon)
        .buttonStyle(.borderedProminent)
    }
}

// MARK: - Home / Lock Screen widget

struct SnapshotEntry: TimelineEntry {
    let date: Date
    let snap: WidgetSnapshot
}

struct SnapshotProvider: TimelineProvider {
    func placeholder(in context: Context) -> SnapshotEntry { SnapshotEntry(date: Date(), snap: .placeholder) }
    func getSnapshot(in context: Context, completion: @escaping (SnapshotEntry) -> Void) {
        completion(SnapshotEntry(date: Date(), snap: WidgetShared.read()))
    }
    func getTimeline(in context: Context, completion: @escaping (Timeline<SnapshotEntry>) -> Void) {
        // The app reloads timelines after each refresh; otherwise look again in an hour (sleepy at night).
        let e = SnapshotEntry(date: Date(), snap: WidgetShared.read())
        completion(Timeline(entries: [e], policy: .after(Date().addingTimeInterval(3600))))
    }
}

struct KaikuHomeWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "fi.kaiku.home", provider: SnapshotProvider()) { e in
            HomeWidgetView(entry: e)
                .containerBackground(KaikuTokens.Colors.bg, for: .widget)
        }
        .configurationDisplayName(TL("widget.name", KaikuLanguage.system))
        .description(TL("widget.desc", KaikuLanguage.system))
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryRectangular, .accessoryCircular])
    }
}

struct HomeWidgetView: View {
    let entry: SnapshotEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        let f: HomeWidgetContent.Family = switch family {
        case .systemMedium: .medium
        case .accessoryRectangular: .rectangular
        case .accessoryCircular: .circular
        default: .small
        }
        ZStack {
            if f == .circular { AccessoryWidgetBackground() }
            HomeWidgetContent(snap: entry.snap, date: entry.date, family: f)
        }
        .widgetURL(URL(string: entry.snap.checkedIn ? "kaiku://today" : "kaiku://checkin"))
    }
}
