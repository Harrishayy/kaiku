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

/// The weather dial: five stops (1..5), drag or tap; label of the current value under the title. One haptic
/// tick per step. VoiceOver: adjustable.
public struct WeatherDial: View {
    let item: DialItem
    @Binding var value: Int
    var disabled: Bool
    var onFocus: (() -> Void)?
    @State private var dragging = false
    @FocusState private var focused: Bool

    public init(item: DialItem, value: Binding<Int>, disabled: Bool = false, onFocus: (() -> Void)? = nil) {
        self.item = item
        _value = value
        self.disabled = disabled
        self.onFocus = onFocus
    }

    var symbol: (String, String) {
        switch item {
        case .mood: return ("cloud.fill", "sun.max.fill")
        case .energy: return ("battery.0percent", "battery.100percent")
        case .sleep: return ("moon.zzz", "moon.stars.fill")
        }
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
            Text(T("wx.\(item.rawValue)")).kText(.callout).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            Text(T("wx.\(item.rawValue).\(value)"))
                .kText(.body)
                .foregroundStyle(KaikuTokens.Colors.ink2)
                .wraps()
                .contentTransition(.opacity)
            HStack(spacing: KaikuTokens.Space.s2) {
                Image(systemName: symbol.0).foregroundStyle(KaikuTokens.Colors.muted).frame(width: 24).accessibilityHidden(true)
                GeometryReader { geo in
                    let w = geo.size.width
                    let step = (w - 32) / 4
                    ZStack(alignment: .leading) {
                        Capsule().fill(KaikuTokens.Colors.surface2).frame(height: 10).padding(.horizontal, 16)
                        Capsule().fill(KaikuTokens.Colors.honey.opacity(0.55))
                            .frame(width: max(10, CGFloat(value - 1) * step + 10), height: 10)
                            .padding(.leading, 11)
                        ForEach(1...5, id: \.self) { i in
                            Circle().fill(i <= value ? KaikuTokens.Colors.honey : KaikuTokens.Colors.line)
                                .frame(width: 8, height: 8)
                                .position(x: 16 + CGFloat(i - 1) * step, y: geo.size.height / 2)
                        }
                        Circle()
                            .fill(KaikuTokens.Colors.surface)
                            .overlay(Circle().strokeBorder(focused ? KaikuTokens.Colors.focus : KaikuTokens.Colors.clay, lineWidth: dragging ? 4 : 3))
                            .shadow(color: .black.opacity(0.12), radius: dragging ? 6 : 3, y: 2)
                            .frame(width: 32, height: 32)
                            .scaleEffect(dragging ? 1.12 : 1)
                            .position(x: 16 + CGFloat(value - 1) * step, y: geo.size.height / 2)
                            .animation(KaikuTokens.Spring.gentle, value: value)
                            .animation(KaikuTokens.Spring.gentle, value: dragging)
                    }
                    .contentShape(Rectangle())
                    .gesture(
                        DragGesture(minimumDistance: 0)
                            .onChanged { g in
                                guard !disabled else { return }
                                if !dragging { dragging = true; onFocus?() }
                                let v = Int(((g.location.x - 16) / step).rounded()) + 1
                                set(min(5, max(1, v)))
                            }
                            .onEnded { _ in dragging = false }
                    )
                }
                .frame(height: KaikuTokens.Size.tapMin)
                Image(systemName: symbol.1).foregroundStyle(KaikuTokens.Colors.honey).frame(width: 24).accessibilityHidden(true)
            }
        }
        .opacity(disabled ? 0.45 : 1)
        .focusable(!disabled)
        .focused($focused)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(T("wx.\(item.rawValue)"))
        .accessibilityValue(T("wx.\(item.rawValue).\(value)"))
        .accessibilityAdjustableAction { dir in
            switch dir {
            case .increment: set(min(5, value + 1))
            case .decrement: set(max(1, value - 1))
            @unknown default: break
            }
        }
    }

    private func set(_ v: Int) {
        guard v != value else { return }
        value = v
        Haptics.dialStep()
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
