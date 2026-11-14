import SwiftUI

/// Dynamic Type for the token text styles (layout.md → Text scaling): each `KaikuTokens.TextStyle` size scales with
/// the matching system style via @ScaledMetric, with line spacing from the token line height.
public enum KText: Sendable {
    case caption, footnote, body, callout, title3, title2, title1, display

    var style: KaikuTextStyle {
        switch self {
        case .caption: return KaikuTokens.TextStyle.caption
        case .footnote: return KaikuTokens.TextStyle.footnote
        case .body: return KaikuTokens.TextStyle.body
        case .callout: return KaikuTokens.TextStyle.callout
        case .title3: return KaikuTokens.TextStyle.title3
        case .title2: return KaikuTokens.TextStyle.title2
        case .title1: return KaikuTokens.TextStyle.title1
        case .display: return KaikuTokens.TextStyle.display
        }
    }

    var relative: Font.TextStyle {
        switch self {
        case .caption: return .caption
        case .footnote: return .footnote
        case .body: return .body
        case .callout: return .callout
        case .title3: return .title3
        case .title2: return .title2
        case .title1: return .title
        case .display: return .largeTitle
        }
    }
}

struct KTextModifier: ViewModifier {
    let kind: KText
    let weight: Font.Weight?
    @ScaledMetric var size: CGFloat
    @ScaledMetric var lineHeight: CGFloat
    let monospaced: Bool

    init(_ kind: KText, weight: Font.Weight?, monospaced: Bool) {
        self.kind = kind
        self.weight = weight
        self.monospaced = monospaced
        _size = ScaledMetric(wrappedValue: kind.style.size, relativeTo: kind.relative)
        _lineHeight = ScaledMetric(wrappedValue: kind.style.lineHeight, relativeTo: kind.relative)
    }

    /// Headings stop growing earlier than body text, so long Finnish compounds ("Tulikärpänen") still fit a
    /// 320 pt column at the largest accessibility sizes. Body text scales all the way.
    var cap: CGFloat {
        switch kind {
        case .caption, .footnote, .body: return 3
        case .callout: return 1.7
        case .title3: return 1.6
        case .title2: return 1.5
        case .title1: return 1.4
        case .display: return 1.3
        }
    }

    func body(content: Content) -> some View {
        let s = min(size, kind.style.size * cap)
        content
            .font(.system(size: s, weight: weight ?? kind.style.fontWeight, design: monospaced ? .monospaced : .rounded))
            .lineSpacing(max(0, min(lineHeight, kind.style.lineHeight * cap) - s * 1.2))
    }
}

public extension View {
    /// Token type with Dynamic Type. Wraps by default (layout.md → Wrapping): never truncates.
    func kText(_ kind: KText, weight: Font.Weight? = nil, mono: Bool = false) -> some View {
        modifier(KTextModifier(kind, weight: weight, monospaced: mono))
    }

    /// Text that must wrap instead of pushing the layout wider (layout.md: `.fixedSize(horizontal: false, vertical: true)`).
    func wraps() -> some View { fixedSize(horizontal: false, vertical: true) }
}

public extension DynamicTypeSize {
    /// layout.md: at scale ≥ 1.2, side-by-side mascot + bubble layouts stack.
    var stacksMascot: Bool { self >= .xxLarge }
}
