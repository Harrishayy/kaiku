import CoreGraphics

/// Where the Mac notch island goes (pure, tested). All rects are AppKit screen coordinates (origin bottom-left of
/// the main display). The island is a part of the menu bar, never on top of it:
/// - **collapsed** (notch screens only): a strip exactly the menu bar's height, the notch plus a wing of at most
///   `maxWing` pt each side, centred on the notch. Wings are clamped to the free space next to the notch.
/// - **drop**: peek/expanded content hangs *below* the menu bar, centred on the notch (or the screen on a Mac
///   without one), growing downward from `dropTop`. It never extends sideways over menu titles or status items.
public struct MacScreenInfo: Equatable, Sendable {
    public var frame: CGRect
    public var visibleFrame: CGRect
    /// `NSScreen.safeAreaInsets.top` (the notch height; 0 without a notch).
    public var safeTop: CGFloat
    /// `NSScreen.auxiliaryTopLeftArea` / `auxiliaryTopRightArea` (nil without a notch).
    public var auxLeft: CGRect?
    public var auxRight: CGRect?
    public var isMain: Bool
    public init(frame: CGRect, visibleFrame: CGRect, safeTop: CGFloat = 0, auxLeft: CGRect? = nil, auxRight: CGRect? = nil,
                isMain: Bool = false) {
        self.frame = frame; self.visibleFrame = visibleFrame; self.safeTop = safeTop
        self.auxLeft = auxLeft; self.auxRight = auxRight; self.isMain = isMain
    }
    public var hasNotch: Bool { safeTop > 0 && auxLeft != nil && auxRight != nil }
}

public struct MacIslandGeometry: Equatable, Sendable {
    public static let maxWing: CGFloat = 60

    /// The notch itself (nil on a screen without one).
    public var notch: CGRect?
    /// The collapsed strip (notch + wings, menu-bar height); nil on a screen without a notch.
    public var collapsed: CGRect?
    public var wing: CGFloat
    /// Menu bar height on this screen (the strip the island must not cover sideways).
    public var menuBar: CGFloat
    /// Drop content: horizontal centre and the top edge it hangs from (just below the menu bar).
    public var centerX: CGFloat
    public var dropTop: CGFloat
    public var screenTop: CGFloat

    /// The panel frame for drop content of `size` (plus `extraBelow` for the mascot hanging out of the edge).
    public func dropFrame(_ size: CGSize, extraBelow: CGFloat = 0) -> CGRect {
        CGRect(x: (centerX - size.width / 2).rounded(), y: dropTop - size.height - extraBelow,
               width: size.width, height: size.height + extraBelow)
    }

    public static func compute(_ s: MacScreenInfo, maxWing: CGFloat = maxWing) -> MacIslandGeometry {
        let top = s.frame.maxY
        if s.hasNotch, let l = s.auxLeft, let r = s.auxRight {
            let notch = CGRect(x: l.maxX, y: top - s.safeTop, width: r.minX - l.maxX, height: s.safeTop)
            // Wings stay inside the free gap next to the notch (never past the auxiliary areas' outer edges).
            let wing = max(0, min(maxWing, l.width, r.width))
            let collapsed = CGRect(x: notch.minX - wing, y: notch.minY, width: notch.width + 2 * wing, height: s.safeTop)
            return MacIslandGeometry(notch: notch, collapsed: collapsed, wing: wing, menuBar: s.safeTop,
                                     centerX: notch.midX, dropTop: notch.minY, screenTop: top)
        }
        let menuBar = max(0, top - s.visibleFrame.maxY)
        return MacIslandGeometry(notch: nil, collapsed: nil, wing: 0, menuBar: menuBar, centerX: s.frame.midX,
                                 dropTop: s.visibleFrame.maxY, screenTop: top)
    }

    /// The screen the island lives on: the one with a notch, else the main screen, else the first.
    public static func pick(_ screens: [MacScreenInfo]) -> MacScreenInfo? {
        screens.first(where: \.hasNotch) ?? screens.first(where: \.isMain) ?? screens.first
    }
}

/// The island's wide body below the menu bar and its shoulders (design/layout.md → Mac notch island): everything
/// lives inside it. `peek` / `expanded` are the content rects (the shape's body is `shoulder` taller). Two columns:
/// Kaiku on the left, vertically centred, `padding` from every edge; text + buttons on the right.
public enum MacIslandLayout {
    public static let padding: CGFloat = 18
    public static let gap: CGFloat = 16
    public static let peek = CGSize(width: 440, height: 172)
    public static let expanded = CGSize(width: 460, height: 188)
    public static let mascotPeek: CGFloat = 124
    public static let mascotExpanded: CGFloat = 128
    /// Shape body height for a content size (the concave shoulders sit above the content).
    public static func bodyHeight(expanded e: Bool) -> CGFloat { size(expanded: e).height + MacIslandShape.shoulder }
    /// The floating z's on black draw this much larger (about their pivot), see `MascotView`.
    public static let onDarkZScale: CGFloat = 1.6

    public static func size(expanded e: Bool) -> CGSize { e ? expanded : peek }
    public static func mascotSize(expanded e: Bool) -> CGFloat { e ? mascotExpanded : mascotPeek }

    /// Kaiku's frame in panel coordinates (origin top-left).
    public static func mascotRect(expanded e: Bool) -> CGRect {
        let s = size(expanded: e), m = mascotSize(expanded: e)
        return CGRect(x: padding, y: ((s.height - m) / 2).rounded(), width: m, height: m)
    }

    /// Where content may draw: the panel inset by the minimum 16 pt margin.
    public static func contentRect(expanded e: Bool) -> CGRect {
        CGRect(origin: .zero, size: size(expanded: e)).insetBy(dx: 16, dy: 16)
    }
}
