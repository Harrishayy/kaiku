import SwiftUI

private struct StaticLayoutKey: EnvironmentKey { static let defaultValue = false }
public extension EnvironmentValues {
    /// Layout snapshots (ImageRenderer can't draw a ScrollView): screens lay out their top viewport statically.
    var kaikuStaticLayout: Bool {
        get { self[StaticLayoutKey.self] }
        set { self[StaticLayoutKey.self] = newValue }
    }
}

/// Screen scaffold: background, vertical scroll (children never shrink), side padding, capped text column on wide
/// panes, header with title + "I'm not OK" (iPhone) that wraps onto two rows when the title needs the room.
public struct KScreen<Content: View>: View {
    let title: String?
    let back: (() -> Void)?
    let scrolls: Bool
    let content: Content
    @Environment(AppModel.self) private var app
    @Environment(\.dynamicTypeSize) private var dts
    @Environment(\.kaikuStaticLayout) private var staticLayout

    public init(_ title: String? = nil, back: (() -> Void)? = nil, scrolls: Bool = true, @ViewBuilder content: () -> Content) {
        self.title = title
        self.back = back
        self.scrolls = scrolls
        self.content = content()
    }

    public var body: some View {
        VStack(spacing: 0) {
            if staticLayout {
                inner.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            } else if scrolls {
                ScrollView {
                    inner.frame(maxWidth: .infinity)
                }
                .scrollDismissesKeyboard(.interactively)
            } else {
                inner.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            }
        }
        .background(KaikuTokens.Colors.bg.ignoresSafeArea())
        #if os(iOS)
        .toolbar(.hidden, for: .navigationBar)
        #endif
    }

    private var inner: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s5) {
            // Fixed (game) screens give the field the room at accessibility sizes: back + pill only.
            ScreenHeader(title: scrolls || !dts.isAccessibilitySize ? title : nil, back: back)
            content
        }
        .padding(.horizontal, KaikuPlatform.sidePadding)
        .padding(.top, KaikuTokens.Space.s2)
        .padding(.bottom, KaikuTokens.Space.s6)
        .frame(maxWidth: 680, alignment: .leading)
        .frame(maxWidth: .infinity, maxHeight: scrolls ? nil : .infinity, alignment: .top)
    }
}

public struct ScreenHeader: View {
    let title: String?
    let back: (() -> Void)?
    public init(title: String?, back: (() -> Void)? = nil) { self.title = title; self.back = back }

    public var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
            if back != nil || KaikuPlatform.isPhone {
                // Back + "I'm not OK" share a row; when they don't fit (Finnish at accessibility sizes) the back
                // label becomes an icon, then the two stack. The pill never shrinks.
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: KaikuTokens.Space.s3) { backButton(label: true); Spacer(minLength: 0); pill }
                    HStack(spacing: KaikuTokens.Space.s3) { backButton(label: false); Spacer(minLength: 0); pill }
                    VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) { backButton(label: false); pill }
                }
            }
            if let title {
                Text(title)
                    .kText(.title1)
                    .foregroundStyle(KaikuTokens.Colors.ink)
                    .wraps()
                    .accessibilityAddTraits(.isHeader)
            }
        }
    }

    @ViewBuilder private var pill: some View {
        if KaikuPlatform.isPhone { NotOKPill() }
    }

    @ViewBuilder private func backButton(label: Bool) -> some View {
        if let back {
            Button(action: back) {
                HStack(spacing: 4) {
                    Image(systemName: "chevron.left").font(.system(size: 17, weight: .semibold))
                    if label { Text(T("common.back")).kText(.body, weight: .medium).lineLimit(1).fixedSize() }
                }
                .foregroundStyle(KaikuTokens.Colors.clay)
                .frame(minWidth: KaikuTokens.Size.tapMin, minHeight: KaikuTokens.Size.tapMin, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(T("common.back"))
        }
    }
}

/// Surface card.
public struct KCard<Content: View>: View {
    let padding: CGFloat
    let tint: Color
    let content: Content
    public init(padding: CGFloat = KaikuTokens.Space.s4, tint: Color = KaikuTokens.Colors.surface, @ViewBuilder content: () -> Content) {
        self.padding = padding
        self.tint = tint
        self.content = content()
    }
    public var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) { content }
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(tint))
            .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
                .strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
    }
}

/// Grouped list section: optional caption title, rows separated by hairlines.
public struct KSection<Content: View>: View {
    let title: String?
    let content: Content
    public init(_ title: String? = nil, @ViewBuilder content: () -> Content) { self.title = title; self.content = content() }
    public var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
            if let title {
                Text(title).kText(.caption).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                    .padding(.horizontal, KaikuTokens.Space.s1)
                    .accessibilityAddTraits(.isHeader)
            }
            VStack(spacing: 0) { content }
                .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.surface))
                .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
                    .strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
                .clipShape(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous))
        }
    }
}

public struct KDivider: View {
    public init() {}
    public var body: some View { Rectangle().fill(KaikuTokens.Colors.line).frame(height: 1).padding(.leading, KaikuTokens.Space.s4) }
}

public enum KRowAccessory { case chevron, check, none, value(String) }

/// List row: optional tinted icon, title + detail column (takes the rest, wraps), trailing accessory (flex: none).
public struct KRow: View {
    let icon: String?
    let tint: Color
    let title: String
    let detail: String?
    let accessory: KRowAccessory
    @Environment(\.dynamicTypeSize) private var dts
    public init(icon: String? = nil, tint: Color = KaikuTokens.Colors.clay, title: String, detail: String? = nil,
                accessory: KRowAccessory = .chevron) {
        self.icon = icon; self.tint = tint; self.title = title; self.detail = detail; self.accessory = accessory
    }
    public var body: some View {
        HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
            // At accessibility sizes the icon goes: the text column needs the width (layout.md → Wrapping).
            if let icon, !dts.isAccessibilitySize { RowIcon(symbol: icon, tint: tint) }
            VStack(alignment: .leading, spacing: 2) {
                Text(title).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                if let detail { Text(detail).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps() }
                if case .value(let v) = accessory, v.count > 14 {
                    Text(v).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps()
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .layoutPriority(1)
            switch accessory {
            case .chevron:
                Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundStyle(KaikuTokens.Colors.muted)
            case .check:
                Image(systemName: "checkmark.circle.fill").font(.system(size: 22)).foregroundStyle(KaikuTokens.Colors.sage)
            case .value(let v) where v.count <= 14:
                Text(v).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).lineLimit(1).fixedSize()
            default: EmptyView()
            }
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .frame(minHeight: 56)
        .contentShape(Rectangle())
    }
}

public struct RowIcon: View {
    let symbol: String
    let tint: Color
    public init(symbol: String, tint: Color) { self.symbol = symbol; self.tint = tint }
    public var body: some View {
        Image(systemName: symbol)
            .font(.system(size: 17, weight: .semibold))
            .foregroundStyle(tint)
            .frame(width: 36, height: 36)
            .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.sm, style: .continuous).fill(tint.opacity(0.14)))
            .accessibilityHidden(true)
    }
}

/// Switch row (consent, pauses). Text column wraps; the switch never moves off-screen.
public struct KToggleRow: View {
    let icon: String?
    let title: String
    let detail: String?
    @Binding var isOn: Bool
    public init(icon: String? = nil, title: String, detail: String? = nil, isOn: Binding<Bool>) {
        self.icon = icon; self.title = title; self.detail = detail; _isOn = isOn
    }
    @Environment(\.dynamicTypeSize) private var dts
    public var body: some View {
        Group {
            if dts.isAccessibilitySize {
                // Stacked: full-width text, the switch under it (long Finnish words never break mid-word).
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
                    labels
                    Toggle(isOn: $isOn) { Text(title) }.labelsHidden()
                }
                .accessibilityElement(children: .combine)
            } else {
                Toggle(isOn: $isOn) {
                    HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
                        if let icon { RowIcon(symbol: icon, tint: KaikuTokens.Colors.sage) }
                        labels
                    }
                }
            }
        }
        .toggleStyle(.switch)
        .tint(KaikuTokens.Colors.sage)
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .frame(minHeight: 56)
    }

    private var labels: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            if let detail { Text(detail).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps() }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Speech bubble (Kaiku or me). Wraps; never wider than the column.
public struct Bubble: View {
    public enum From { case kaiku, me }
    let text: String
    let from: From
    public init(_ text: String, from: From = .kaiku) { self.text = text; self.from = from }
    @Environment(\.dynamicTypeSize) private var dts
    public var body: some View {
        HStack {
            if from == .me { Spacer(minLength: dts.isAccessibilitySize ? 16 : 40) }
            Text(text)
                .kText(.body)
                .foregroundStyle(from == .me ? KaikuTokens.Colors.clayInk : KaikuTokens.Colors.ink)
                .wraps()
                .padding(.horizontal, KaikuTokens.Space.s4)
                .padding(.vertical, KaikuTokens.Space.s3)
                .background(
                    RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
                        .fill(from == .me ? KaikuTokens.Colors.clay : KaikuTokens.Colors.surface)
                )
                .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
                    .strokeBorder(from == .me ? .clear : KaikuTokens.Colors.line, lineWidth: 1))
            if from == .kaiku { Spacer(minLength: dts.isAccessibilitySize ? 0 : 24) }
        }
    }
}

/// Mascot + bubble: side by side, stacked at large text (layout.md). `dial` makes the ear follow a 1..5 value.
public struct MascotWithBubble: View {
    let state: MascotState
    let text: String
    let size: CGFloat
    let dial: Double?
    @Environment(\.dynamicTypeSize) private var dts
    public init(state: MascotState, text: String, size: CGFloat = 132, dial: Double? = nil) {
        self.state = state; self.text = text; self.size = size; self.dial = dial
    }
    public var body: some View {
        if dts.stacksMascot {
            VStack(spacing: KaikuTokens.Space.s3) {
                MascotView(state: state, size: size, dial: dial).frame(maxWidth: .infinity)
                Bubble(text)
            }
        } else {
            HStack(alignment: .center, spacing: KaikuTokens.Space.s2) {
                MascotView(state: state, size: size, dial: dial)
                Bubble(text).layoutPriority(1)
            }
        }
    }
}
