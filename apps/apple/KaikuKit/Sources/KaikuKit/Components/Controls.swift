import SwiftUI

/// Segmented control that wraps: equal segments in a row, or a vertical list when the labels don't fit
/// (Finnish at XL). Selected segment = surface with a clay outline.
public struct KSegmented<V: Hashable>: View {
    let options: [(V, String)]
    @Binding var selection: V
    public init(_ options: [(V, String)], selection: Binding<V>) { self.options = options; _selection = selection }

    public var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 4) { segments(fixed: true) }
                .padding(4)
                .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.surface2))
            VStack(spacing: 4) { segments(fixed: false) }
                .padding(4)
                .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.md, style: .continuous).fill(KaikuTokens.Colors.surface2))
        }
    }

    @ViewBuilder private func segments(fixed: Bool) -> some View {
        ForEach(options, id: \.0) { value, label in
            let on = value == selection
            Button { selection = value } label: {
                Text(label)
                    .kText(.footnote, weight: .semibold)
                    .foregroundStyle(on ? KaikuTokens.Colors.ink : KaikuTokens.Colors.ink2)
                    .lineLimit(fixed ? 1 : nil)
                    .fixedSize(horizontal: fixed, vertical: !fixed)
                    .padding(.horizontal, KaikuTokens.Space.s3)
                    .frame(maxWidth: .infinity, minHeight: KaikuTokens.Size.tapMin)
                    .background(
                        RoundedRectangle(cornerRadius: KaikuTokens.Radius.sm, style: .continuous)
                            .fill(on ? KaikuTokens.Colors.surface : .clear)
                    )
                    .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.sm, style: .continuous)
                        .strokeBorder(on ? KaikuTokens.Colors.clay : .clear, lineWidth: 1.5))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityAddTraits(on ? .isSelected : [])
        }
    }
}

/// Toast (bottom, auto-hides after 2.4 s).
public struct ToastModifier: ViewModifier {
    @Binding var text: String?
    @Environment(\.accessibilityReduceMotion) private var rm
    public func body(content: Content) -> some View {
        content.overlay(alignment: .bottom) {
            if let t = text {
                Text(t)
                    .kText(.footnote, weight: .semibold)
                    .foregroundStyle(KaikuTokens.Colors.bg)
                    .multilineTextAlignment(.center)
                    .wraps()
                    .padding(.horizontal, KaikuTokens.Space.s4)
                    .padding(.vertical, KaikuTokens.Space.s3)
                    .background(Capsule().fill(KaikuTokens.Colors.ink))
                    .padding(.horizontal, KaikuTokens.Space.s5)
                    .padding(.bottom, KaikuTokens.Space.s6)
                    .transition(rm ? .opacity : .move(edge: .bottom).combined(with: .opacity))
                    .task(id: t) {
                        try? await Task.sleep(nanoseconds: 2_400_000_000)
                        withAnimation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.fast)) { text = nil }
                    }
                    .accessibilityAddTraits(.updatesFrequently)
            }
        }
        .animation(KaikuTokens.Easing.gentleOut(KaikuTokens.Duration.base), value: text)
    }
}

public extension View {
    func kToast(_ text: Binding<String?>) -> some View { modifier(ToastModifier(text: text)) }
}
