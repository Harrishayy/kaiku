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
    }
}

// MARK: - Walk

struct WalkLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: WalkActivityAttributes.self) { ctx in
            let lang = KaikuLanguage(rawValue: ctx.attributes.lang) ?? .en
            WalkLockContent(lang: lang, minutes: ctx.state.minutes, found: ctx.state.found)
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
                    WalkIslandCenter(lang: lang, found: st.found)
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
