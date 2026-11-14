import CoreGraphics

/// What the quick-talk surface is right now. It is ONE object at the left edge of the screen that grows: a thin
/// coloured bar at rest, a small pill with two buttons under the pointer, and the popup with Kaiku and the words.
public enum QuickTalkStage: String, Equatable, Sendable, CaseIterable {
    /// Nothing is drawn (the bar is turned off): the popup grows from the screen edge itself.
    case hidden
    case bar, pill, popup
}

/// Sizes of the quick-talk surface (pure, tested): a few points of bar, a small pill, and a card that is smaller
/// than the notch island on purpose: it sits beside whatever the person is doing.
public enum QuickTalkLayout {
    /// The bar at rest: a few points wide, so it sits over nothing anyone needs.
    public static let bar = CGSize(width: 6, height: 52)
    /// The bar while a conversation is on and the popup is put away: a little wider, with the voice meter in it.
    public static let barLive = CGSize(width: 12, height: 64)
    /// Under the pointer: exactly two round buttons, one above the other.
    public static let pill = CGSize(width: 50, height: 92)
    public static let pillButton: CGFloat = 34
    /// Gap between the screen edge and the bar / the pill (the popup uses `margin`).
    public static let barInset: CGFloat = 4
    public static let pillInset: CGFloat = 6
    /// How close to the bar the pointer has to come, and how far from the pill it may stray before it shrinks back.
    public static let hoverReach: CGFloat = 8
    public static let hoverSlack: CGFloat = 14

    /// The size of the one shape at a stage.
    public static func size(_ stage: QuickTalkStage, live: Bool = false, card: CGSize = wide) -> CGSize {
        switch stage {
        case .hidden: return CGSize(width: 0, height: bar.height)
        case .bar: return live ? barLive : bar
        case .pill: return pill
        case .popup: return card
        }
    }

    /// Its gap from the left edge of the usable screen.
    public static func inset(_ stage: QuickTalkStage) -> CGFloat {
        switch stage {
        case .hidden: return 0
        case .bar: return barInset
        case .pill: return pillInset
        case .popup: return margin
        }
    }

    /// Corner radius: the bar and the pill are capsules, the popup a card.
    public static func radius(_ stage: QuickTalkStage, size: CGSize) -> CGFloat {
        stage == .popup ? 24 : min(size.width, size.height) / 2
    }

    /// Whether the pointer keeps (or starts) the pill, given where the bar and the pill are on screen. Starting
    /// takes coming right up to the bar (from the screen edge to a little past it); once the pill is out, the
    /// pointer may wander a little around it before it shrinks back.
    public static func hovering(was: Bool, pointer: CGPoint, bar: CGRect, pill: CGRect, edge: CGFloat) -> Bool {
        let around = was ? pill : bar, reach = was ? hoverSlack : hoverReach
        // from the screen edge itself to a little past the shape, and a little above and below it
        return CGRect(x: edge - 1, y: around.minY - reach, width: around.maxX - edge + 1 + reach, height: around.height + 2 * reach)
            .contains(pointer)
    }

    /// The microphone's level (dB, about −90 quiet … 0 loud) as 0…1 for the bar's meter.
    public static func level(db: Float) -> Double { min(1, max(0, (Double(db) + 55) / 40)) }

    /// Kaiku with captions (or with the one line that says why it cannot listen).
    public static let wide = CGSize(width: 360, height: 184)
    /// Captions off: Kaiku alone with its controls.
    public static let compact = CGSize(width: 176, height: 198)
    /// Extra height for the one activity card Kaiku may suggest (under the captions).
    public static let activityRow: CGFloat = 48
    /// Gap between the left edge of the usable screen (or the Dock) and the card.
    public static let margin: CGFloat = 12
    /// Room around the card inside its window for the soft shadow.
    public static let shadowPad: CGFloat = 28
    public static let padding: CGFloat = 14
    public static let mascot: CGFloat = 72
    /// The small round controls (a pointer target, like the island's pills).
    public static let control: CGFloat = 30

    /// The card for what is showing. A reason Kaiku cannot listen is always spelled out, captions or not.
    /// An activity card needs the wide card too.
    public static func card(captions: Bool, conversational: Bool, activity: Bool = false) -> CGSize {
        if activity && conversational { return CGSize(width: wide.width, height: wide.height + activityRow) }
        return captions || !conversational ? wide : compact
    }

    /// The call in the notch island while the popup is put away: one row (state word, elapsed time, mute me, end).
    public static let islandCall = CGSize(width: 320, height: 46)

    /// The largest card: the window is made for it once, the card changes size inside.
    public static var largest: CGSize {
        CGSize(width: max(wide.width, compact.width), height: max(wide.height + activityRow, compact.height))
    }
}

/// Where the quick-talk panel goes (pure, tested). All rects are AppKit screen coordinates (origin bottom-left of
/// the main display). The card sits at the left edge of the screen's visible frame, vertically centred, so it is
/// clear of the menu bar and of the Dock wherever the Dock is (a Dock on the left moves the visible frame's left
/// edge). The window starts exactly at that edge: the card slides in from it and never shows on a neighbouring
/// display or under the Dock.
public struct QuickTalkGeometry: Equatable, Sendable {
    /// The transparent window that holds the card and its shadow.
    public var window: CGRect
    /// The visible frame the window was fitted into.
    public var visible: CGRect

    /// The frame of a card of `size` on screen: `margin` from the window's left edge, vertically centred.
    public func cardFrame(_ size: CGSize) -> CGRect { frame(size, inset: QuickTalkLayout.margin) }

    /// The frame of the one shape at a stage (the bar, the pill, or the popup card of `card` size).
    public func frame(_ stage: QuickTalkStage, live: Bool = false, card: CGSize = QuickTalkLayout.wide) -> CGRect {
        frame(QuickTalkLayout.size(stage, live: live, card: card), inset: QuickTalkLayout.inset(stage))
    }

    private func frame(_ size: CGSize, inset: CGFloat) -> CGRect {
        let w = min(size.width, max(0, window.width - inset))
        let h = min(size.height, window.height)
        return CGRect(x: window.minX + inset, y: (window.midY - h / 2).rounded(), width: w, height: h)
    }

    public static func compute(_ s: MacScreenInfo, largest: CGSize = QuickTalkLayout.largest) -> QuickTalkGeometry {
        let v = s.visibleFrame
        let width = min(v.width, QuickTalkLayout.margin + largest.width + QuickTalkLayout.shadowPad)
        let height = min(v.height, largest.height + 2 * QuickTalkLayout.shadowPad)
        let y = (v.midY - height / 2).rounded()
        return QuickTalkGeometry(window: CGRect(x: v.minX, y: min(max(y, v.minY), v.maxY - height), width: width, height: height),
                                 visible: v)
    }

    /// The screen the pointer is on (the person is looking there), else the main screen, else the first.
    public static func pick(_ screens: [MacScreenInfo], pointer: CGPoint) -> MacScreenInfo? {
        screens.first(where: { $0.frame.contains(pointer) }) ?? screens.first(where: \.isMain) ?? screens.first
    }
}
