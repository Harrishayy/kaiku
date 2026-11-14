import SwiftUI

private struct StaticLayoutKey: EnvironmentKey { static let defaultValue = false }
public extension EnvironmentValues {
    /// Layout snapshots (ImageRenderer can't draw a ScrollView): screens lay out their top viewport statically.
    var kaikuStaticLayout: Bool {
        get { self[StaticLayoutKey.self] }
        set { self[StaticLayoutKey.self] = newValue }
    }
}

/// Screen scaffold: warm backdrop, a body that only scrolls when it truly doesn't fit (accessibility sizes, SE),
/// side padding, a capped content column, and a compact header (title + "I'm not OK" share one row on iPhone;
/// pushed screens put back + title on one row). Publishes the column width for adaptive two-column layouts.
public struct KScreen<Content: View>: View {
    let title: String?
    let back: (() -> Void)?
    let scrolls: Bool
    let maxWidth: CGFloat
    let spacing: CGFloat
    let content: Content
    @Environment(\.dynamicTypeSize) private var dts
    @Environment(\.kaikuStaticLayout) private var staticLayout
    @State private var width: CGFloat = 0

    public init(_ title: String? = nil, back: (() -> Void)? = nil, scrolls: Bool = true, maxWidth: CGFloat = 680,
                spacing: CGFloat = KaikuTokens.Space.s5, @ViewBuilder content: () -> Content) {
        self.title = title
        self.back = back
        self.scrolls = scrolls
        self.maxWidth = maxWidth
        self.spacing = spacing
        self.content = content()
    }

    public var body: some View {
        VStack(spacing: 0) {
            if staticLayout || !scrolls {
                inner.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            } else {
                ScrollView {
                    inner.frame(maxWidth: .infinity)
                }
                .scrollBounceBehavior(.basedOnSize)
                .scrollDismissesKeyboard(.interactively)
            }
        }
        .background(KBackdrop())
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
        .environment(\.kaikuPaneWidth, max(0, min(width - 2 * KaikuPlatform.sidePadding, maxWidth)))
        #if os(iOS)
        .toolbar(.hidden, for: .navigationBar)
        #endif
    }

    private var inner: some View {
        VStack(alignment: .leading, spacing: spacing) {
            // Fixed (game) screens give the field the room at accessibility sizes: back + pill only.
            ScreenHeader(title: scrolls || !dts.isAccessibilitySize ? title : nil, back: back)
            content
        }
        .padding(.horizontal, KaikuPlatform.sidePadding)
        .padding(.top, KaikuPlatform.isPhone ? KaikuTokens.Space.s2 : KaikuTokens.Space.s5)
        .padding(.bottom, KaikuTokens.Space.s5)
        .frame(maxWidth: maxWidth, alignment: .leading)
        .frame(maxWidth: .infinity, maxHeight: scrolls ? nil : .infinity, alignment: .top)
    }
}

public struct ScreenHeader: View {
    let title: String?
    let back: (() -> Void)?
    public init(title: String?, back: (() -> Void)? = nil) { self.title = title; self.back = back }

    public var body: some View {
        // Title and the pill share a row; when the title needs the room (Finnish, large text) they wrap onto two
        // rows. The pill never shrinks (layout.md → Headers).
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
                backButton
                titleText.fixedSize()
                Spacer(minLength: KaikuTokens.Space.s2)
                pill
            }
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                if back != nil || KaikuPlatform.isPhone {
                    HStack(spacing: KaikuTokens.Space.s3) { backButton; Spacer(minLength: 0); pill }
                }
                titleText.wraps()
            }
        }
    }

    @ViewBuilder private var titleText: some View {
        if let title {
            Text(title)
                .kText(back == nil ? .title2 : .title3, weight: .semibold)
                .foregroundStyle(KaikuTokens.Colors.ink)
                .accessibilityAddTraits(.isHeader)
        }
    }

    @ViewBuilder private var pill: some View {
        if KaikuPlatform.isPhone { NotOKPill() }
    }

    @ViewBuilder private var backButton: some View {
        if let back { BackButton(action: back) }
    }
}

/// Round back button (40 pt disc in a 44 pt target). Esc goes back on Mac.
public struct BackButton: View {
    let action: () -> Void
    var onDark = false
    public init(onDark: Bool = false, action: @escaping () -> Void) { self.onDark = onDark; self.action = action }
    public var body: some View {
        Button(action: action) {
            Image(systemName: "chevron.left")
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(onDark ? KaikuTokens.Colors.nightInk : KaikuTokens.Colors.ink)
                .frame(width: 40, height: 40)
                .background(Circle().fill(onDark ? KaikuTokens.Colors.nightInk.opacity(0.12) : KaikuTokens.Colors.surface))
                .overlay(Circle().strokeBorder(onDark ? KaikuTokens.Colors.nightInk.opacity(0.25) : KaikuTokens.Colors.line, lineWidth: 1))
                .frame(minWidth: KaikuTokens.Size.tapMin, minHeight: KaikuTokens.Size.tapMin)
                .contentShape(Circle())
        }
        .buttonStyle(.kPress)
        .keyboardShortcut(.cancelAction)
        .accessibilityLabel(T("common.back"))
    }
}

/// Surface card. Plain surface cards get a hairline + a whisper of shadow; tinted (soft tone) cards are borderless.
public struct KCard<Content: View>: View {
    let padding: CGFloat
    let tint: Color
    let content: Content
    public init(padding: CGFloat = KaikuTokens.Space.s4, tint: Color = KaikuTokens.Colors.surface, @ViewBuilder content: () -> Content) {
        self.padding = padding
        self.tint = tint
        self.content = content()
    }
    public init(padding: CGFloat = KaikuTokens.Space.s4, tone: KTone, @ViewBuilder content: () -> Content) {
        self.init(padding: padding, tint: tone.soft, content: content)
    }
    var plain: Bool { tint == KaikuTokens.Colors.surface }
    public var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) { content }
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(tint)
                    .shadow(color: KaikuTokens.Colors.ink.opacity(plain ? 0.05 : 0), radius: 10, y: 4)
            )
            .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
                .strokeBorder(plain ? KaikuTokens.Colors.line : .clear, lineWidth: 1))
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
                .clipShape(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous))
                .background(
                    RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.surface)
                        .shadow(color: KaikuTokens.Colors.ink.opacity(0.05), radius: 10, y: 4)
                )
                .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
                    .strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
        }
    }
}

public struct KDivider: View {
    public init() {}
    public var body: some View { Rectangle().fill(KaikuTokens.Colors.line).frame(height: 1).padding(.leading, KaikuTokens.Space.s4) }
}

public enum KRowAccessory { case chevron, check, none, value(String) }

/// List row: optional tone icon tile, title + detail column (takes the rest, wraps), trailing accessory.
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
            VStack(alignment: .leading, spacing: 1) {
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
                Image(systemName: "chevron.right").font(.system(size: 13, weight: .bold)).foregroundStyle(KaikuTokens.Colors.muted)
            case .check:
                Image(systemName: "checkmark.circle.fill").font(.system(size: 22)).foregroundStyle(KaikuTokens.Colors.sage)
            case .value(let v) where v.count <= 14:
                Text(v).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).lineLimit(1).fixedSize()
            default: EmptyView()
            }
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3 - 2)
        .frame(minHeight: 54)
        .contentShape(Rectangle())
    }
}

/// Icon tile: the tone's ink on its soft fill (artifact `.row-ic.ic-*`).
public struct RowIcon: View {
    let symbol: String
    let tint: Color
    var side: CGFloat = 36
    public init(symbol: String, tint: Color, side: CGFloat = 36) { self.symbol = symbol; self.tint = tint; self.side = side }
    public var body: some View {
        Image(systemName: symbol)
            .font(.system(size: side * 0.47, weight: .semibold))
            .foregroundStyle(tint)
            .frame(width: side, height: side)
            .background(RoundedRectangle(cornerRadius: side * 0.31, style: .continuous).fill(KTone.of(tint)?.soft ?? tint.opacity(0.14)))
            .accessibilityHidden(true)
    }
}

/// Switch row (consent, pauses). Text column wraps; the switch never moves off-screen.
public struct KToggleRow: View {
    let icon: String?
    let tint: Color
    let title: String
    let detail: String?
    @Binding var isOn: Bool
    public init(icon: String? = nil, tint: Color = KaikuTokens.Colors.sage, title: String, detail: String? = nil, isOn: Binding<Bool>) {
        self.icon = icon; self.tint = tint; self.title = title; self.detail = detail; _isOn = isOn
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
                        if let icon { RowIcon(symbol: icon, tint: tint) }
                        labels
                    }
                }
            }
        }
        .toggleStyle(.switch)
        .tint(KaikuTokens.Colors.sage)
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3 - 2)
        .frame(minHeight: 54)
    }

    private var labels: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(title).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            if let detail { Text(detail).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps() }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Speech bubble (Kaiku or me). Kaiku's has the artifact's tucked corner toward the mascot; mine is clay-soft.
public struct Bubble: View {
    public enum From { case kaiku, me }
    let text: String
    let from: From
    var big = false
    var centered = false
    public init(_ text: String, from: From = .kaiku, big: Bool = false, centered: Bool = false) {
        self.text = text; self.from = from; self.big = big; self.centered = centered
    }
    @Environment(\.dynamicTypeSize) private var dts
    var shape: UnevenRoundedRectangle {
        from == .me
            ? UnevenRoundedRectangle(topLeadingRadius: 20, bottomLeadingRadius: 20, bottomTrailingRadius: 6, topTrailingRadius: 20, style: .continuous)
            : UnevenRoundedRectangle(topLeadingRadius: 20, bottomLeadingRadius: 6, bottomTrailingRadius: 20, topTrailingRadius: 20, style: .continuous)
    }
    public var body: some View {
        HStack {
            if from == .me && !centered { Spacer(minLength: dts.isAccessibilitySize ? 16 : 40) }
            Text(text)
                .kText(big ? .callout : .body, weight: big ? .medium : nil)
                .foregroundStyle(KaikuTokens.Colors.ink)
                .wraps()
                .padding(.horizontal, KaikuTokens.Space.s4)
                .padding(.vertical, KaikuTokens.Space.s3)
                .background(shape.fill(from == .me ? KaikuTokens.Colors.claySoft : KaikuTokens.Colors.surface)
                    .shadow(color: KaikuTokens.Colors.ink.opacity(from == .me ? 0 : 0.05), radius: 8, y: 3))
                .overlay(shape.strokeBorder(from == .me ? .clear : KaikuTokens.Colors.line, lineWidth: 1))
                .contentTransition(.opacity)
            if from == .kaiku && !centered { Spacer(minLength: dts.isAccessibilitySize ? 0 : 24) }
        }
    }
}

/// Mascot + bubble: side by side, stacked at large text (layout.md). `dial` makes the ear follow a 1..5 value.
public struct MascotWithBubble: View {
    let state: MascotState
    let text: String
    let size: CGFloat
    let dial: Double?
    var big = false
    @Environment(\.dynamicTypeSize) private var dts
    public init(state: MascotState, text: String, size: CGFloat = 132, dial: Double? = nil, big: Bool = false) {
        self.state = state; self.text = text; self.size = size; self.dial = dial; self.big = big
    }
    public var body: some View {
        if dts.stacksMascot {
            VStack(spacing: KaikuTokens.Space.s3) {
                GlowingMascot(state: state, size: size, dial: dial).frame(maxWidth: .infinity)
                Bubble(text, big: big)
            }
        } else {
            HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
                GlowingMascot(state: state, size: size, dial: dial)
                Bubble(text, big: big).layoutPriority(1)
            }
        }
    }
}
