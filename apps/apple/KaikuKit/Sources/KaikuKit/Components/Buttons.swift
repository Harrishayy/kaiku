import SwiftUI

/// Buttons from the design library. Labels always wrap (never truncate); primary is ≥ 52 pt tall and full width on
/// iPhone; every target is ≥ 44 pt.
public enum KButtonKind { case primary, secondary, ghost, crisis }

public struct KButtonStyle: ButtonStyle {
    let kind: KButtonKind
    let fullWidth: Bool
    @Environment(\.isEnabled) private var enabled

    public init(_ kind: KButtonKind, fullWidth: Bool = true) {
        self.kind = kind
        self.fullWidth = fullWidth
    }

    public func makeBody(configuration: Configuration) -> some View {
        let (bg, fg): (Color, Color) = {
            switch kind {
            case .primary: return (KaikuTokens.Colors.clay, KaikuTokens.Colors.clayInk)
            case .secondary: return (KaikuTokens.Colors.surface2, KaikuTokens.Colors.ink)
            case .ghost: return (.clear, KaikuTokens.Colors.clay)
            case .crisis: return (KaikuTokens.Colors.crisis, KaikuTokens.Colors.crisisInk)
            }
        }()
        configuration.label
            .kText(kind == .ghost ? .body : .callout, weight: .semibold)
            .multilineTextAlignment(.center)
            .wraps()
            .foregroundStyle(fg)
            .padding(.horizontal, KaikuTokens.Space.s5)
            .padding(.vertical, KaikuTokens.Space.s3)
            .frame(maxWidth: fullWidth ? .infinity : nil, minHeight: kind == .ghost ? KaikuTokens.Size.tapMin : 52)
            .background(
                RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
                    .fill(bg)
            )
            .contentShape(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous))
            .opacity(enabled ? (configuration.isPressed ? 0.82 : 1) : 0.45)
            .scaleEffect(configuration.isPressed && kind != .crisis ? 0.98 : 1)
            .animation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast), value: configuration.isPressed)
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
    public init() {}
    public var body: some View {
        Button { app.crisis(trigger: "manual") } label: {
            Text(T("common.notok"))
                .kText(.footnote, weight: .semibold)
                .foregroundStyle(KaikuTokens.Colors.clay)
                .lineLimit(1)
                .fixedSize()
                .padding(.horizontal, KaikuTokens.Space.s4)
                .frame(minHeight: KaikuTokens.Size.tapMin)
                .background(Capsule().fill(KaikuTokens.Colors.claySoft))
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
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
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(filled ? KaikuTokens.Colors.clayInk : KaikuTokens.Colors.ink)
                .frame(width: KaikuTokens.Size.tapMin, height: KaikuTokens.Size.tapMin)
                .background(Circle().fill(filled ? KaikuTokens.Colors.clay : KaikuTokens.Colors.surface2))
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}
