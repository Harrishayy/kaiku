import SwiftUI
#if os(macOS)
import AppKit
#endif

/// Category tones (design artifact `.ic-*` / `.tint-*`): every tone has a strong ink and a soft fill from the
/// tokens. Icons sit on the soft fill in the strong ink; tinted cards use the soft fill with no border.
public enum KTone: Sendable, CaseIterable {
    case clay, sage, sky, honey, ink

    public var ink: Color {
        switch self {
        case .clay: return KaikuTokens.Colors.clay
        case .sage: return KaikuTokens.Colors.sage
        case .sky: return KaikuTokens.Colors.sky
        case .honey: return KaikuTokens.Colors.honey
        case .ink: return KaikuTokens.Colors.ink2
        }
    }

    public var soft: Color {
        switch self {
        case .clay: return KaikuTokens.Colors.claySoft
        case .sage: return KaikuTokens.Colors.sageSoft
        case .sky: return KaikuTokens.Colors.skySoft
        case .honey: return KaikuTokens.Colors.honeySoft
        case .ink: return KaikuTokens.Colors.surface2
        }
    }

    /// The tone whose ink is `c` (token colours are shared static instances, so equality is identity).
    public static func of(_ c: Color) -> KTone? { allCases.first { $0.ink == c } }
}

/// Press + hover feedback for anything clickable that is not a KButton (rows, cards, tiles): scales to 0.98 on
/// press within a frame, lifts a hair and shows the pointing hand on hover (Mac). Reduce Motion: no scale.
public struct KPressStyle: ButtonStyle {
    var hoverFill: Color?
    var radius: CGFloat
    public init(hoverFill: Color? = nil, radius: CGFloat = KaikuTokens.Radius.lg) { self.hoverFill = hoverFill; self.radius = radius }
    public func makeBody(configuration: Configuration) -> some View {
        PressBody(configuration: configuration, hoverFill: hoverFill, radius: radius)
    }

    private struct PressBody: View {
        let configuration: Configuration
        let hoverFill: Color?
        let radius: CGFloat
        @State private var hover = false
        @Environment(\.accessibilityReduceMotion) private var rm
        @Environment(\.isEnabled) private var enabled
        var body: some View {
            configuration.label
                .background {
                    if let hoverFill, hover || configuration.isPressed {
                        RoundedRectangle(cornerRadius: radius, style: .continuous).fill(hoverFill)
                    }
                }
                .brightness(hover && !configuration.isPressed ? 0.012 : 0)
                .scaleEffect(configuration.isPressed && !rm ? 0.98 : 1)
                .animation(.easeOut(duration: configuration.isPressed ? KaikuTokens.Feedback.press : KaikuTokens.Feedback.release), value: configuration.isPressed)
                .animation(.easeOut(duration: KaikuTokens.Feedback.hover), value: hover)
                .kPointer(enabled)
                .onHover { hover = $0 && enabled }
        }
    }
}

public extension ButtonStyle where Self == KPressStyle {
    static var kPress: KPressStyle { KPressStyle() }
    static func kPressRow(_ radius: CGFloat = 0) -> KPressStyle { KPressStyle(hoverFill: KaikuTokens.Colors.surface2.opacity(0.6), radius: radius) }
}

public extension View {
    /// Pointing-hand cursor on Mac while hovering something clickable.
    @ViewBuilder func kPointer(_ on: Bool = true, cursor: KCursor = .hand) -> some View {
        #if os(macOS)
        self.onHover { inside in
            guard on else { return }
            if inside { cursor.ns.push() } else { NSCursor.pop() }
        }
        #else
        self
        #endif
    }
}

public enum KCursor {
    case hand, openHand
    #if os(macOS)
    var ns: NSCursor { self == .hand ? .pointingHand : .openHand }
    #endif
}

/// Screen backdrop: paper bg with a soft time-of-day wash at the top (warmth and depth, never a gradient
/// spectacle). The wash uses the chest glow colour at a low opacity and changes once a minute.
public struct KBackdrop: View {
    var tone: Color?
    public init(tone: Color? = nil) { self.tone = tone }
    public var body: some View {
        TimelineView(.everyMinute) { tl in
            let (glow, k) = GlowClock.current(tl.date)
            ZStack {
                KaikuTokens.Colors.bg
                RadialGradient(colors: [(tone ?? glow).opacity(0.10 + 0.08 * k), .clear],
                               center: UnitPoint(x: 0.22, y: -0.05), startRadius: 0, endRadius: 520)
                LinearGradient(colors: [.clear, KaikuTokens.Colors.surface2.opacity(0.35)], startPoint: .center, endPoint: .bottom)
            }
            .animation(.easeInOut(duration: KaikuTokens.Duration.slow), value: tl.date)
        }
        .ignoresSafeArea()
        .accessibilityHidden(true)
    }
}

/// A soft glow pool behind Kaiku in the time-of-day colour (the artifact's hero stage).
public struct MascotHalo: View {
    var size: CGFloat
    public init(size: CGFloat) { self.size = size }
    public var body: some View {
        TimelineView(.everyMinute) { tl in
            let (glow, k) = GlowClock.current(tl.date)
            Circle()
                .fill(RadialGradient(colors: [glow.opacity(0.22 + 0.2 * k), glow.opacity(0)], center: .center,
                                     startRadius: 0, endRadius: size * 0.62))
                .frame(width: size * 1.3, height: size * 1.3)
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

/// Kaiku standing in its glow pool.
public struct GlowingMascot: View {
    let state: MascotState
    let size: CGFloat
    var dial: Double?
    var tappable = true
    public init(state: MascotState, size: CGFloat, dial: Double? = nil, tappable: Bool = true) {
        self.state = state; self.size = size; self.dial = dial; self.tappable = tappable
    }
    public var body: some View {
        ZStack {
            MascotHalo(size: size)
            MascotView(state: state, size: size, dial: dial, tappable: tappable)
        }
        .frame(width: size, height: size)
    }
}

private struct PaneWidthKey: EnvironmentKey { static let defaultValue: CGFloat = 390 }
public extension EnvironmentValues {
    /// Width of the current screen's content column (set by KScreen), for adaptive one/two-column layouts.
    var kaikuPaneWidth: CGFloat {
        get { self[PaneWidthKey.self] }
        set { self[PaneWidthKey.self] = newValue }
    }
}

/// Two columns when the pane is wide enough (Mac window), one column otherwise (iPhone, accessibility sizes).
public struct KAdaptiveColumns<Leading: View, Trailing: View>: View {
    var minWidth: CGFloat
    var spacing: CGFloat
    var leadingFraction: CGFloat
    /// The gap between the things stacked in a column (sections take the page's own section gap, `space.5`).
    var stack: CGFloat
    let leading: Leading
    let trailing: Trailing
    @Environment(\.dynamicTypeSize) private var dts
    @Environment(\.kaikuPaneWidth) private var width

    public init(minWidth: CGFloat = 600, spacing: CGFloat = KaikuTokens.Space.s6, leadingFraction: CGFloat = 0.46,
                stack: CGFloat = KaikuTokens.Space.s4,
                @ViewBuilder leading: () -> Leading, @ViewBuilder trailing: () -> Trailing) {
        self.minWidth = minWidth; self.spacing = spacing; self.leadingFraction = leadingFraction; self.stack = stack
        self.leading = leading(); self.trailing = trailing()
    }

    public static func isWide(_ width: CGFloat, _ dts: DynamicTypeSize, min: CGFloat = 600) -> Bool {
        width >= min && !dts.isAccessibilitySize
    }

    public var body: some View {
        if Self.isWide(width, dts, min: minWidth) {
            HStack(alignment: .top, spacing: spacing) {
                VStack(alignment: .leading, spacing: stack) { leading }
                    .frame(width: (width - spacing) * leadingFraction, alignment: .topLeading)
                VStack(alignment: .leading, spacing: stack) { trailing }
                    .frame(maxWidth: .infinity, alignment: .topLeading)
            }
        } else {
            VStack(alignment: .leading, spacing: stack) {
                leading
                trailing
            }
        }
    }
}

/// Tiny non-score progress: a thin capsule that fills (games). Never a number.
struct ProgressBar: View {
    let progress: Double
    var color: Color = KaikuTokens.Colors.honey
    var track: Color = KaikuTokens.Colors.line
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(track)
                Capsule().fill(color).frame(width: max(6, g.size.width * max(0, min(1, progress))))
            }
        }
        .frame(height: 5)
        .accessibilityHidden(true)
    }
}
