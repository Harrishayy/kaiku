import SwiftUI

/// Buttons from the design library. Labels always wrap (never truncate); primary is ≥ 52 pt tall and full width on
/// iPhone; every target is ≥ 44 pt. Press = 0.97 scale within a frame (no scale on crisis); hover on Mac shades the
/// fill and shows the pointing hand. `night` / `nightGhost` are for the Firefly night scene.
public enum KButtonKind { case primary, secondary, ghost, crisis, night, nightGhost }

public struct KButtonStyle: ButtonStyle {
    let kind: KButtonKind
    let fullWidth: Bool

    public init(_ kind: KButtonKind, fullWidth: Bool = true) {
        self.kind = kind
        self.fullWidth = fullWidth
    }

    public func makeBody(configuration: Configuration) -> some View {
        KButtonBody(kind: kind, fullWidth: fullWidth, configuration: configuration)
    }
}

private struct KButtonBody: View {
    let kind: KButtonKind
    let fullWidth: Bool
    let configuration: ButtonStyleConfiguration
    @Environment(\.isEnabled) private var enabled
    @Environment(\.accessibilityReduceMotion) private var rm
    @State private var hover = false

    var colors: (Color, Color) {
        switch kind {
        case .primary: return (KaikuTokens.Colors.clay, KaikuTokens.Colors.clayInk)
        case .secondary: return (KaikuTokens.Colors.surface2, KaikuTokens.Colors.ink)
        case .ghost: return (.clear, KaikuTokens.Colors.clay)
        case .crisis: return (KaikuTokens.Colors.crisis, KaikuTokens.Colors.crisisInk)
        case .night: return (KaikuTokens.Colors.firefly, KaikuTokens.Colors.nightA)
        case .nightGhost: return (.clear, KaikuTokens.Colors.nightInk)
        }
    }

    var ghost: Bool { kind == .ghost || kind == .nightGhost }
    var lifted: Bool { kind == .primary || kind == .night }

    var body: some View {
        let (bg, fg) = colors
        let pressed = configuration.isPressed
        configuration.label
            .kText(ghost ? .body : .callout, weight: .semibold)
            .multilineTextAlignment(.center)
            .wraps()
            .foregroundStyle(fg)
            .padding(.horizontal, KaikuTokens.Space.s5)
            .padding(.vertical, KaikuTokens.Space.s3)
            .frame(maxWidth: fullWidth ? .infinity : nil, minHeight: ghost ? KaikuTokens.Size.tapMin : KaikuTokens.Size.buttonMin)
            .background(
                ZStack {
                    RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(bg)
                    // Hover/press shade: a darker veil on filled buttons, a wash of the label colour on ghosts.
                    RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous)
                        .fill(ghost ? fg.opacity(pressed ? 0.12 : hover ? 0.07 : 0)
                                    : Color.black.opacity(pressed ? 0.12 : hover ? 0.05 : 0))
                }
                .shadow(color: lifted && enabled ? bg.opacity(0.28) : .clear, radius: pressed ? 2 : 8, y: pressed ? 1 : 4)
            )
            .contentShape(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous))
            .opacity(enabled ? 1 : 0.42)
            .scaleEffect(pressed && kind != .crisis && !rm ? 0.97 : 1)
            .animation(.easeOut(duration: pressed ? KaikuTokens.Feedback.press : KaikuTokens.Feedback.release), value: pressed)
            .animation(.easeOut(duration: KaikuTokens.Feedback.hover), value: hover)
            .kPointer(enabled && kind != .crisis)
            .onHover { hover = $0 && enabled && kind != .crisis }
    }
}

public extension ButtonStyle where Self == KButtonStyle {
    static var kPrimary: KButtonStyle { KButtonStyle(.primary) }
    static var kSecondary: KButtonStyle { KButtonStyle(.secondary) }
    static var kGhost: KButtonStyle { KButtonStyle(.ghost) }
    static var kCrisis: KButtonStyle { KButtonStyle(.crisis) }
}

/// "I'm not OK" — on every screen (header on iPhone, sidebar on Mac). Never shrinks; opens Crisis. No haptics.
public struct NotOKPill: View {
    @Environment(AppModel.self) private var app
    var onDark = false
    public init(onDark: Bool = false) { self.onDark = onDark }
    public var body: some View {
        Button { app.crisis(trigger: "manual") } label: {
            Text(T("common.notok"))
                .kText(.footnote, weight: .semibold)
                // Ink on clay-soft (AA at footnote size); the clay heart keeps the pill recognisable.
                .foregroundStyle(onDark ? KaikuTokens.Colors.nightInk : KaikuTokens.Colors.ink)
                .lineLimit(1)
                .fixedSize()
                .padding(.horizontal, KaikuTokens.Space.s4)
                .frame(minHeight: KaikuTokens.Size.control)
                .background(Capsule().fill(onDark ? Color.clear : KaikuTokens.Colors.claySoft))
                .overlay(Capsule().strokeBorder(onDark ? KaikuTokens.Colors.nightInk.opacity(0.35) : .clear, lineWidth: 1.5))
                .frame(minHeight: KaikuTokens.Size.tapMin)
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .kPointer()
        .accessibilityHint(T("help.body"))
    }
}

/// A round icon button (composer send / mic, back). 44 pt target, accessible label required.
public struct IconButton: View {
    let symbol: String
    let label: String
    let filled: Bool
    let action: () -> Void
    public init(_ symbol: String, label: String, filled: Bool = false, action: @escaping () -> Void) {
        self.symbol = symbol; self.label = label; self.filled = filled; self.action = action
    }
    public var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .kText(.body, weight: .semibold)
                .foregroundStyle(filled ? KaikuTokens.Colors.clayInk : KaikuTokens.Colors.ink)
                .frame(width: KaikuTokens.Size.tapMin, height: KaikuTokens.Size.tapMin)
                .background(Circle().fill(filled ? KaikuTokens.Colors.clay : KaikuTokens.Colors.surface2))
                .contentShape(Circle())
        }
        .buttonStyle(.kPress)
        .accessibilityLabel(label)
    }
}
