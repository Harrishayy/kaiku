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
    var subtitle: String? = nil
    let back: (() -> Void)?
    let scrolls: Bool
    let maxWidth: CGFloat
    let spacing: CGFloat
    let content: Content
    @Environment(\.dynamicTypeSize) private var dts
    @Environment(\.kaikuStaticLayout) private var staticLayout
    @State private var width: CGFloat = 0
    @Environment(AppModel.self) private var app: AppModel?

    public init(_ title: String? = nil, subtitle: String? = nil, back: (() -> Void)? = nil, scrolls: Bool = true,
                maxWidth: CGFloat = KaikuTokens.Size.contentMax, spacing: CGFloat = KaikuTokens.Space.s5, @ViewBuilder content: () -> Content) {
        self.title = title
        self.subtitle = subtitle
        self.back = back
        self.scrolls = scrolls
        self.maxWidth = maxWidth
        self.spacing = spacing
        self.content = content()
    }

    public var body: some View {
        VStack(spacing: 0) {
            if staticLayout {
                inner.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            } else if !scrolls {
                inner.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top).fillsProposal()
            } else {
                ScrollView {
                    // Exactly the width offered, never what the content would like. A scroll view grows to its
                    // content's minimum width, and this screen's width is what `kaikuPaneWidth` (and so the two
                    // columns) is read from: content too wide for its column made the screen wider, the wider
                    // screen made the first column wider, and the Mac's Today never stopped laying out.
                    inner.frame(minWidth: 0, maxWidth: .infinity)
                }
                .scrollBounceBehavior(.basedOnSize)
                .scrollDismissesKeyboard(.interactively)
                .kTopEdgeBackdrop()
            }
        }
        .background(KBackdrop())
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
        .environment(\.kaikuPaneWidth, max(0, min(width - 2 * KaikuPlatform.sidePadding, maxWidth)))
        #if os(iOS)
        .toolbar(.hidden, for: .navigationBar)
        #else
        .navigationTitle(back != nil ? (title ?? "Kaiku") : "Kaiku")
        #endif
    }

    /// Mac pushed screens show their title in the window toolbar (next to the system back button), like any Mac app.
    private var headerTitle: String? {
        if !KaikuPlatform.isPhone && back != nil { return nil }
        return scrolls || !dts.isAccessibilitySize ? title : nil
    }

    private var inner: some View {
        // One section gap on every screen and both platforms (design/layout.md); room above the floating tab bar.
        VStack(alignment: .leading, spacing: spacing) {
            // Fixed (game) screens give the field the room at accessibility sizes: back + pill only.
            // Every tab root (scrolling or fixed, like Talk) starts with the same page header.
            if back == nil, let t = headerTitle {
                PageHeader(title: t, subtitle: subtitle)
            } else {
                ScreenHeader(title: headerTitle, back: back)
            }
            // Offline is said once, in the same place, on every scrolling screen (queued work is safe).
            if scrolls, app?.offline == true, app?.isPaired == true { OfflineBanner() }
            content
        }
        .padding(.horizontal, KaikuPlatform.sidePadding)
        .padding(.top, KaikuPlatform.isPhone ? KaikuTokens.Space.s3 : KaikuTokens.Space.s5)
        .padding(.bottom, KaikuPlatform.isPhone && scrolls ? KaikuTokens.Space.s8 + KaikuTokens.Space.s4 : KaikuTokens.Space.s5)
        .frame(maxWidth: maxWidth, alignment: .leading)
        .frame(maxWidth: .infinity, maxHeight: scrolls ? nil : .infinity, alignment: .top)
    }
}

/// A tab's page header: a small clay date line, the big title, one plain line on what the page is for, and the
/// "I'm not OK" pill top-right on iPhone. Gives every page the same calm, magazine-like start.
public struct PageHeader: View {
    let title: String
    let subtitle: String?
    public init(title: String, subtitle: String? = nil) { self.title = title; self.subtitle = subtitle }

    static var eyebrow: String {
        let f = DateFormatter()
        f.locale = Locale(identifier: L10n.shared.language.rawValue)
        f.setLocalizedDateFormatFromTemplate("EEEEdMMMM")
        return f.string(from: Date())
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s2) {
            HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
                Text(Self.eyebrow.uppercased(with: Locale(identifier: L10n.shared.language.rawValue)))
                    .kText(.caption, weight: .semibold).tracking(0.8)
                    .foregroundStyle(KaikuTokens.Colors.clay)
                    .wraps()
                    .frame(maxWidth: .infinity, alignment: .leading)
                Spacer(minLength: KaikuTokens.Space.s2)
                if KaikuPlatform.isPhone { NotOKPill() }
            }
            Text(title)
                .kText(.title1, weight: .bold)
                .foregroundStyle(KaikuTokens.Colors.ink)
                .wraps()
                .accessibilityAddTraits(.isHeader)
            if let subtitle {
                Text(subtitle).kText(.body).foregroundStyle(KaikuTokens.Colors.ink2).wraps()
                    .padding(.top, KaikuTokens.Space.s1 / 2)
            }
        }
        .padding(.bottom, KaikuTokens.Space.s1)
    }
}

/// A section's header: tone icon tile + title (+ one quiet line). Replaces bare grey captions.
public struct SectionHeader: View {
    let title: String
    var subtitle: String? = nil
    var icon: String? = nil
    var tone: KTone = .clay
    public init(_ title: String, subtitle: String? = nil, icon: String? = nil, tone: KTone = .clay) {
        self.title = title; self.subtitle = subtitle; self.icon = icon; self.tone = tone
    }
    public var body: some View {
        HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
            if let icon { RowIcon(symbol: icon, tint: tone.ink) }
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
                Text(title).kText(.callout, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                if let subtitle { Text(subtitle).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps() }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
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
        if let back {
            #if os(macOS)
            EscapeKey(action: back)   // Mac: the window toolbar's own back button; Esc still goes back
            #else
            BackButton(action: back)
            #endif
        }
    }
}

/// Mac: an invisible Esc shortcut (the visible back control is the system toolbar's).
public struct EscapeKey: View {
    let action: () -> Void
    public init(action: @escaping () -> Void) { self.action = action }
    public var body: some View {
        Button("", action: action).keyboardShortcut(.cancelAction).buttonStyle(.plain)
            .frame(width: 0, height: 0).opacity(0).accessibilityHidden(true)
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
                .kText(.footnote, weight: .bold)
                .foregroundStyle(onDark ? KaikuTokens.Colors.nightInk : KaikuTokens.Colors.ink)
                .frame(width: KaikuTokens.Size.control, height: KaikuTokens.Size.control)
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
                    .kaikuShadow(plain ? KaikuTokens.Elevation.card : KaikuShadow(radius: 0, y: 0, opacity: 0))
            )
            .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
                .strokeBorder(plain ? KaikuTokens.Colors.line : .clear, lineWidth: 1))
    }
}

/// Grouped list section: optional caption title, rows separated by hairlines.
public struct KSection<Content: View>: View {
    let title: String?
    var subtitle: String? = nil
    var icon: String? = nil
    var tone: KTone = .clay
    let content: Content
    public init(_ title: String? = nil, subtitle: String? = nil, icon: String? = nil, tone: KTone = .clay,
                @ViewBuilder content: () -> Content) {
        self.title = title; self.subtitle = subtitle; self.icon = icon; self.tone = tone; self.content = content()
    }
    public var body: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s3) {
            if let title {
                SectionHeader(title, subtitle: subtitle, icon: icon, tone: tone)
            }
            VStack(spacing: 0) { content }
                .clipShape(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous))
                .background(
                    RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous).fill(KaikuTokens.Colors.surface)
                        .kaikuShadow(KaikuTokens.Elevation.card)
                )
                .overlay(RoundedRectangle(cornerRadius: KaikuTokens.Radius.lg, style: .continuous)
                    .strokeBorder(KaikuTokens.Colors.line, lineWidth: 1))
        }
    }
}

/// The hairline between rows, inset to where the rows' text starts: past the icon tile, or (`plain`) at the row
/// padding for rows that have no icon.
public struct KDivider: View {
    var plain = false
    public init(plain: Bool = false) { self.plain = plain }
    public var body: some View { Rectangle().fill(KaikuTokens.Colors.line).frame(height: 1)
            .padding(.leading, plain ? KaikuTokens.Space.s4 : KaikuTokens.Space.s4 + KaikuTokens.Size.iconTile + KaikuTokens.Space.s3)
    }
}

/// What a row ends with. `link` is a short value and the chevron (a row that leads somewhere and says where
/// things stand: "On", "3 of 5 on").
public enum KRowAccessory { case chevron, check, none, value(String), link(String) }

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
            VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
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
                KChevron()
            case .check:
                Image(systemName: "checkmark.circle.fill").kText(.title3).foregroundStyle(KaikuTokens.Colors.sage)
            case .value(let v) where v.count <= 14:
                Text(v).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).lineLimit(1).fixedSize()
            case .link(let v):
                HStack(spacing: KaikuTokens.Space.s2) {
                    Text(v).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).lineLimit(1).fixedSize()
                    KChevron()
                }
            default: EmptyView()
            }
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .frame(minHeight: KaikuTokens.Size.rowMin)
        .contentShape(Rectangle())
    }
}

/// Icon tile: the tone's ink on its soft fill (artifact `.row-ic.ic-*`).
public struct RowIcon: View {
    let symbol: String
    let tint: Color
    var side: CGFloat = KaikuTokens.Size.iconTile
    public init(symbol: String, tint: Color, side: CGFloat = KaikuTokens.Size.iconTile) { self.symbol = symbol; self.tint = tint; self.side = side }
    public var body: some View {
        Image(systemName: symbol)
            .font(.system(size: side * 0.47, weight: .semibold))
            .foregroundStyle(tint)
            .frame(width: side, height: side)
            .background(RoundedRectangle(cornerRadius: KaikuTokens.Radius.sm, style: .continuous).fill(KTone.of(tint)?.soft ?? tint.opacity(0.14)))
            .accessibilityHidden(true)
    }
}

/// Switch row (consent, pauses): optional icon tile, title + one quiet line (the column wraps and takes the
/// rest), the switch. The row lays its parts out itself: as the label of the system switch the text was not
/// given its height on the Mac, so a second line ran over the row's padding into the rows around it.
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
                    toggle
                }
            } else {
                HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
                    if let icon { RowIcon(symbol: icon, tint: tint) }
                    labels
                    toggle
                }
            }
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .frame(minHeight: KaikuTokens.Size.rowMin)
    }

    /// The switch alone; VoiceOver hears the title and the quiet line on it, as when they were its label
    /// (a consent text must not depend on hints being switched on).
    private var toggle: some View {
        Toggle(isOn: $isOn) { Text(title) }
            .labelsHidden()
            .toggleStyle(.switch)
            .tint(KaikuTokens.Colors.sage)
            .fixedSize()
            .accessibilityLabel([title, detail].compactMap { $0 }.joined(separator: ", "))
    }

    private var labels: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
            Text(title).kText(.body, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
            if let detail { Text(detail).kText(.footnote).foregroundStyle(KaikuTokens.Colors.muted).wraps() }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .layoutPriority(1)
        .accessibilityHidden(true)
    }
}

/// Sheet scaffold (components.md → Sheet / modal): the title, Done top right (Esc closes too), and content that
/// scrolls inside. On the Mac a sheet is a small window of its own: `width` × `height` is how it opens.
public struct KSheet<Content: View>: View {
    let title: String
    var width: CGFloat
    var height: CGFloat
    let content: Content
    @Environment(\.dismiss) private var dismiss
    public init(_ title: String, width: CGFloat = 520, height: CGFloat = 520, @ViewBuilder content: () -> Content) {
        self.title = title; self.width = width; self.height = height; self.content = content()
    }
    public var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .center, spacing: KaikuTokens.Space.s3) {
                Text(title).kText(.title3, weight: .semibold).foregroundStyle(KaikuTokens.Colors.ink).wraps()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityAddTraits(.isHeader)
                Button(T("common.done")) { dismiss() }
                    .buttonStyle(KButtonStyle(.ghost, fullWidth: false))
                    .keyboardShortcut(.cancelAction)
            }
            .padding(.horizontal, KaikuPlatform.sidePadding)
            .padding(.top, KaikuTokens.Space.s4)
            .padding(.bottom, KaikuTokens.Space.s2)
            ScrollView {
                VStack(alignment: .leading, spacing: KaikuTokens.Space.s5) { content }
                    .padding(.horizontal, KaikuPlatform.sidePadding)
                    .padding(.top, KaikuTokens.Space.s2)
                    .padding(.bottom, KaikuTokens.Space.s5)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .scrollBounceBehavior(.basedOnSize)
        }
        .background(KaikuTokens.Colors.bg)
        #if os(macOS)
        .frame(width: width, height: height)
        #endif
    }
}

/// Speech bubble (Kaiku or me). Kaiku's has the artifact's tucked corner toward the mascot; mine is clay-soft.
/// `maxWidth` caps the bubble inside a chat column; `footnote` is a quiet second line (e.g. "interrupted").
public struct Bubble: View {
    public enum From { case kaiku, me }
    let text: String
    let from: From
    var big = false
    var centered = false
    var maxWidth: CGFloat? = nil
    var footnote: String? = nil
    public init(_ text: String, from: From = .kaiku, big: Bool = false, centered: Bool = false,
                maxWidth: CGFloat? = nil, footnote: String? = nil) {
        self.text = text; self.from = from; self.big = big; self.centered = centered
        self.maxWidth = maxWidth; self.footnote = footnote
    }
    @Environment(\.dynamicTypeSize) private var dts
    var shape: UnevenRoundedRectangle {
        let r = KaikuTokens.Radius.md, tucked = KaikuTokens.Radius.xs
        return from == .me
            ? UnevenRoundedRectangle(topLeadingRadius: r, bottomLeadingRadius: r, bottomTrailingRadius: tucked, topTrailingRadius: r, style: .continuous)
            : UnevenRoundedRectangle(topLeadingRadius: r, bottomLeadingRadius: tucked, bottomTrailingRadius: r, topTrailingRadius: r, style: .continuous)
    }
    private var bubble: some View {
        VStack(alignment: .leading, spacing: KaikuTokens.Space.s1) {
            Text(text)
                .kText(big ? .callout : .body, weight: big ? .medium : nil)
                .foregroundStyle(KaikuTokens.Colors.ink)
                .wraps()
            if let footnote { Text(footnote).kText(.caption).foregroundStyle(KaikuTokens.Colors.ink2).wraps() }
        }
        .padding(.horizontal, KaikuTokens.Space.s4)
        .padding(.vertical, KaikuTokens.Space.s3)
        .background(shape.fill(from == .me ? KaikuTokens.Colors.claySoft : KaikuTokens.Colors.surface)
            .kaikuShadow(from == .me ? KaikuShadow(radius: 0, y: 0, opacity: 0) : KaikuTokens.Elevation.card))
        .overlay(shape.strokeBorder(from == .me ? .clear : KaikuTokens.Colors.line, lineWidth: 1))
        .contentTransition(.identity)   // a cross-fade of two lengths left ghost text
    }
    public var body: some View {
        if let maxWidth {
            bubble
                .frame(maxWidth: maxWidth, alignment: from == .me ? .trailing : .leading)
                .frame(maxWidth: .infinity, alignment: from == .me ? .trailing : .leading)
        } else {
            HStack {
                if from == .me && !centered { Spacer(minLength: dts.isAccessibilitySize ? KaikuTokens.Space.s4 : KaikuTokens.Space.s6) }
                bubble
                if from == .kaiku && !centered { Spacer(minLength: dts.isAccessibilitySize ? 0 : KaikuTokens.Space.s5) }
            }
        }
    }
}

/// The row chevron: follows Dynamic Type (one definition for every list row and card link).
public struct KChevron: View {
    var tint: Color = KaikuTokens.Colors.muted
    public init(tint: Color = KaikuTokens.Colors.muted) { self.tint = tint }
    public var body: some View {
        Image(systemName: "chevron.right").kText(.caption, weight: .bold).foregroundStyle(tint).accessibilityHidden(true)
    }
}

/// Small label chip: ink text on a tone's soft fill (AA at caption size), capsule. One chip for the whole app.
public struct KChip: View {
    let text: String
    var tone: KTone = .clay
    var icon: String? = nil
    public init(_ text: String, tone: KTone = .clay, icon: String? = nil) { self.text = text; self.tone = tone; self.icon = icon }
    public var body: some View {
        HStack(spacing: KaikuTokens.Space.s1) {
            if let icon { Image(systemName: icon).foregroundStyle(tone.ink).accessibilityHidden(true) }
            Text(text).foregroundStyle(KaikuTokens.Colors.ink).lineLimit(1)
        }
        .kText(.caption, weight: .semibold)
        .padding(.horizontal, KaikuTokens.Space.s2)
        .padding(.vertical, KaikuTokens.Space.s1)
        .background(Capsule().fill(tone.soft))
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
    public init(state: MascotState, text: String, size: CGFloat = KaikuTokens.Size.mascotM, dial: Double? = nil, big: Bool = false) {
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

public extension View {
    /// Scrolled content must not run under the clock and Dynamic Island: a strip of the page colour fills the top
    /// safe area above any scrolling screen (iPhone; the Mac window has its own toolbar).
    @ViewBuilder func kTopEdgeBackdrop() -> some View {
        #if os(iOS)
        modifier(TopEdgeBackdrop())
        #else
        self
        #endif
    }

    /// Takes exactly the size it is offered and reports no minimum of its own. Non-scrolling panes (games, Talk)
    /// need this on macOS: NavigationSplitView measures its detail at a tiny width, where vertically fixed wrapping
    /// text reports a huge minimum height — the split view then outgrew the window and clipped the sidebar list,
    /// the "I'm not OK" pill, the game title and the Start button.
    func fillsProposal() -> some View {
        GeometryReader { g in self.frame(width: g.size.width, height: g.size.height) }
    }
}

#if os(iOS)
/// An opaque strip of the page colour over the top safe area (status bar, Dynamic Island), with a soft fade
/// below it, so scrolled content never shows under the clock.
struct TopEdgeBackdrop: ViewModifier {
    func body(content: Content) -> some View {
        content.overlay(alignment: .top) {
            GeometryReader { g in
                let inset = g.safeAreaInsets.top
                VStack(spacing: 0) {
                    KaikuTokens.Colors.bg.frame(height: inset)
                    LinearGradient(colors: [KaikuTokens.Colors.bg, KaikuTokens.Colors.bg.opacity(0)], startPoint: .top, endPoint: .bottom)
                        .frame(height: KaikuTokens.Space.s2)
                }
                .offset(y: -inset)
            }
            .allowsHitTesting(false)
            .accessibilityHidden(true)
        }
    }
}
#endif
