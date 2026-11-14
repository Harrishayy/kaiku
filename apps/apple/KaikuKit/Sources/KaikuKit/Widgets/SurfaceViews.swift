import SwiftUI

/// The content of the walk / breathe Live Activities and the Kaiku widget, kept in KaikuKit so the widget extension
/// and the app's layout snapshots (`-kaikuSurfaceSnapshot`) render the very same views. Kaiku is the hero wherever
/// there is room (lead feedback: small state details — z's, legs, breath, scarf — must read).
public enum SurfaceSize {
    public static let lockMascot: CGFloat = 112
    public static let islandMascot: CGFloat = 76
    public static let glyph: CGFloat = 26
    public static let pad: CGFloat = 16
    public static let smallWidgetMascot: CGFloat = 104
    public static let mediumWidgetMascot: CGFloat = 120
}

/// The walk's spotting game on a small surface: its own thing and target ("Trees 1 of 3"). Nil when no game is on.
public struct WalkGoalLine: Equatable, Sendable {
    public let thing: String
    public let target: Int
    public let found: Int
    public init?(thing: String?, target: Int?, found: Int) {
        guard let thing, !thing.isEmpty, let target, target > 0 else { return nil }
        self.thing = thing; self.target = target; self.found = min(max(0, found), target)
    }
    public func text(_ lang: KaikuLanguage) -> String {
        thing + " " + TL("walk.goal.count", lang, ["n": "\(found)", "m": "\(target)"])
    }
}

public struct FoundDotsRow: View {
    let found: Int
    let target: Int
    let onDark: Bool
    public init(found: Int, target: Int = 3, onDark: Bool) { self.found = found; self.target = target; self.onDark = onDark }
    public var body: some View {
        HStack(spacing: 7) {
            ForEach(0..<max(1, target), id: \.self) { i in
                Circle()
                    .fill(i < found ? KaikuTokens.Colors.sage : (onDark ? Color.white.opacity(0.18) : KaikuTokens.Colors.surface))
                    .overlay(Circle().strokeBorder(KaikuTokens.Colors.sage, lineWidth: 1.5))
                    .frame(width: 13, height: 13)
            }
        }
    }
}

/// Lock Screen walk (design/ia.md): big walking Kaiku, "Walking with Kaiku" (1 line, truncates), the spotting
/// game's own thing and count with its dots when one is on (nothing about a game otherwise), minutes. No buttons
/// here (they live in the expanded island) so Kaiku can fill the 160 pt height.
public struct WalkLockContent: View {
    let lang: KaikuLanguage
    let minutes: Int
    let goal: WalkGoalLine?
    public init(lang: KaikuLanguage, minutes: Int, goal: WalkGoalLine?) {
        self.lang = lang; self.minutes = minutes; self.goal = goal
    }

    public var body: some View {
            HStack(alignment: .center, spacing: 14) {
                MascotView(state: .walking, size: SurfaceSize.lockMascot, tappable: false)
                    .frame(width: SurfaceSize.lockMascot, height: SurfaceSize.lockMascot)
                VStack(alignment: .leading, spacing: 5) {
                    Text(TL("lh.walking", lang))
                        .font(.system(.headline, design: .rounded))
                        .foregroundStyle(KaikuTokens.Colors.ink)
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                        .truncationMode(.tail)
                    if let goal {
                        Text(goal.text(lang))
                            .font(.system(.subheadline, design: .rounded))
                            .foregroundStyle(KaikuTokens.Colors.ink2)
                            .lineLimit(1)
                            .minimumScaleFactor(0.7)
                        FoundDotsRow(found: goal.found, target: goal.target, onDark: false)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Text(TL("la.min", lang, ["n": "\(minutes)"]))
                    .font(.system(.title3, design: .rounded).weight(.semibold))
                    .foregroundStyle(KaikuTokens.Colors.sage)
                    .lineLimit(1)
                    .fixedSize()
            }
        .padding(SurfaceSize.pad)
    }
}

/// Expanded Dynamic Island, centre region: title, and the spotting game's thing, count and dots when one is on.
public struct WalkIslandCenter: View {
    let lang: KaikuLanguage
    let goal: WalkGoalLine?
    public init(lang: KaikuLanguage, goal: WalkGoalLine?) { self.lang = lang; self.goal = goal }
    public var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(TL("lh.walking", lang)).font(.system(.headline, design: .rounded)).foregroundStyle(.white)
                .lineLimit(1).minimumScaleFactor(0.8)
            if let goal {
                Text(goal.text(lang)).font(.system(.subheadline, design: .rounded)).foregroundStyle(.white.opacity(0.85))
                    .lineLimit(1).minimumScaleFactor(0.7)
                FoundDotsRow(found: goal.found, target: goal.target, onDark: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

public struct IslandMinutes: View {
    let lang: KaikuLanguage
    let minutes: Int
    public init(lang: KaikuLanguage, minutes: Int) { self.lang = lang; self.minutes = minutes }
    public var body: some View {
        Text(TL("la.min", lang, ["n": "\(minutes)"]))
            .font(.system(.title3, design: .rounded).weight(.semibold))
            .foregroundStyle(KaikuTokens.Colors.sage)
            .lineLimit(1)
            .minimumScaleFactor(0.7)
    }
}

public struct BreatheLockContent: View {
    let lang: KaikuLanguage
    let breath: Int
    public init(lang: KaikuLanguage, breath: Int) { self.lang = lang; self.breath = breath }
    public var body: some View {
        HStack(spacing: 14) {
            MascotView(state: .breathing, size: SurfaceSize.lockMascot, tappable: false)
                .frame(width: SurfaceSize.lockMascot, height: SurfaceSize.lockMascot)
            VStack(alignment: .leading, spacing: 5) {
                Text(TL("la.breathe", lang)).font(.system(.headline, design: .rounded)).foregroundStyle(KaikuTokens.Colors.ink)
                    .lineLimit(1).minimumScaleFactor(0.85)
                Text(TL("br.count", lang, ["n": "\(breath)"])).font(.system(.subheadline, design: .rounded))
                    .foregroundStyle(KaikuTokens.Colors.ink2).lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(SurfaceSize.pad)
    }
}

public struct BreatheIslandCenter: View {
    let lang: KaikuLanguage
    let breath: Int
    public init(lang: KaikuLanguage, breath: Int) { self.lang = lang; self.breath = breath }
    public var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(TL("la.breathe", lang)).font(.system(.headline, design: .rounded)).foregroundStyle(.white).lineLimit(1)
                .minimumScaleFactor(0.8)
            Text(TL("br.count", lang, ["n": "\(breath)"])).font(.system(.subheadline, design: .rounded))
                .foregroundStyle(.white.opacity(0.85)).lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The Kaiku widget at each size (Home Screen small/medium, Lock Screen rectangular/circular).
public struct HomeWidgetContent: View {
    public enum Family: String, CaseIterable, Sendable { case small, medium, rectangular, circular }
    let snap: WidgetSnapshot
    let date: Date
    let family: Family
    public init(snap: WidgetSnapshot, date: Date, family: Family) { self.snap = snap; self.date = date; self.family = family }

    var state: MascotState {
        let h = Calendar.current.component(.hour, from: date)
        if (h >= 23 || h < 5) && snap.state != .cozy { return .sleepy }
        return snap.state
    }
    var lang: KaikuLanguage { snap.language }
    var action: String { snap.checkedIn ? TL("widget.done", lang) : TL("widget.checkin", lang) }

    public var body: some View {
        switch family {
        case .circular:
            KaikuGlyph(state: state, size: 44, tint: .white)
        case .rectangular:
            HStack(spacing: 8) {
                KaikuGlyph(state: state, size: 46, tint: .white)
                VStack(alignment: .leading, spacing: 1) {
                    Text(TL("widget.name", lang)).font(.system(.headline, design: .rounded)).lineLimit(1)
                    Text(action).font(.system(.caption, design: .rounded)).lineLimit(2).minimumScaleFactor(0.85)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        case .medium:
            HStack(spacing: 14) {
                MascotView(state: state, size: SurfaceSize.mediumWidgetMascot, tappable: false)
                    .frame(width: SurfaceSize.mediumWidgetMascot, height: SurfaceSize.mediumWidgetMascot)
                VStack(alignment: .leading, spacing: 10) {
                    Text(TL(snap.suggestionKey, lang))
                        .font(.system(.subheadline, design: .rounded))
                        .foregroundStyle(KaikuTokens.Colors.ink)
                        .lineLimit(3)
                        .minimumScaleFactor(0.8)
                    Text(action)
                        .font(.system(.footnote, design: .rounded).weight(.semibold))
                        .foregroundStyle(snap.checkedIn ? KaikuTokens.Colors.sage : Color.white)
                        .padding(.horizontal, 12).padding(.vertical, 6)
                        .background(Capsule().fill(snap.checkedIn ? KaikuTokens.Colors.sageSoft : KaikuTokens.Colors.clay))
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        case .small:
            VStack(spacing: 4) {
                MascotView(state: state, size: SurfaceSize.smallWidgetMascot, tappable: false)
                    .frame(width: SurfaceSize.smallWidgetMascot, height: SurfaceSize.smallWidgetMascot)
                Text(action)
                    .font(.system(.footnote, design: .rounded).weight(.semibold))
                    .foregroundStyle(KaikuTokens.Colors.ink)
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
            }
        }
    }
}
