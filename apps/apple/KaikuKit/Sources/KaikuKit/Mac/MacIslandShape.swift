import SwiftUI

/// The notch island silhouette (design/layout.md → Mac notch island): ONE black shape that grows out of the
/// notch. From the top of the screen down to `menuBar` it is only `topWidth` wide (the notch + wings, so it never
/// covers menu titles or status items); just below the menu bar it flares out to `bodyWidth` through concave "shoulder"
/// curves and ends in large rounded bottom corners. Collapsed = `bodyHeight` 0 (just the strip in the menu bar).
/// `pill` (a Mac without a notch): no strip, a rounded body `pillGap` below the menu bar. Centred horizontally in
/// the rect it is drawn in; animatable, so collapsed → expanded is one spring on the same shape.
public struct MacIslandShape: Shape {
    public var topWidth: CGFloat
    public var bodyWidth: CGFloat
    public var bodyHeight: CGFloat
    public var menuBar: CGFloat
    public var pill: Bool

    public static let shoulder: CGFloat = 12
    public static let bodyCorner: CGFloat = 10
    public static let bottomCorner: CGFloat = 30
    public static let stripCorner: CGFloat = 8
    public static let pillGap: CGFloat = 6

    public init(topWidth: CGFloat, bodyWidth: CGFloat, bodyHeight: CGFloat, menuBar: CGFloat, pill: Bool = false) {
        self.topWidth = topWidth; self.bodyWidth = bodyWidth; self.bodyHeight = bodyHeight
        self.menuBar = menuBar; self.pill = pill
    }

    public var animatableData: AnimatablePair<AnimatablePair<CGFloat, CGFloat>, CGFloat> {
        get { AnimatablePair(AnimatablePair(topWidth, bodyWidth), bodyHeight) }
        set { topWidth = newValue.first.first; bodyWidth = newValue.first.second; bodyHeight = newValue.second }
    }

    /// The concave shoulder radius actually drawn (0 when there is no flare yet).
    public var shoulderRadius: CGFloat {
        let flare = max(0, (bodyWidth - topWidth) / 2)
        return max(0, min(Self.shoulder, flare / 2, bodyHeight / 2))
    }

    public func path(in rect: CGRect) -> Path {
        let cx = rect.midX, y0 = rect.minY
        var p = Path()
        if pill {
            guard bodyHeight > 0.5, bodyWidth > 0.5 else { return p }
            let r = CGRect(x: cx - bodyWidth / 2, y: y0 + menuBar + Self.pillGap, width: bodyWidth, height: bodyHeight)
            p.addRoundedRect(in: r, cornerSize: CGSize(width: min(Self.bottomCorner, bodyHeight / 2), height: min(Self.bottomCorner, bodyHeight / 2)),
                             style: .continuous)
            return p
        }
        let tl = cx - topWidth / 2, tr = cx + topWidth / 2
        let bar = y0 + menuBar
        guard bodyHeight > 0.5 else {
            // Collapsed: just the strip in the menu bar, its bottom corners rounded like the hardware notch.
            let r = min(Self.stripCorner, menuBar / 2, topWidth / 2)
            p.move(to: CGPoint(x: tl, y: y0))
            p.addLine(to: CGPoint(x: tr, y: y0))
            p.addLine(to: CGPoint(x: tr, y: bar - r))
            p.addQuadCurve(to: CGPoint(x: tr - r, y: bar), control: CGPoint(x: tr, y: bar))
            p.addLine(to: CGPoint(x: tl + r, y: bar))
            p.addQuadCurve(to: CGPoint(x: tl, y: bar - r), control: CGPoint(x: tl, y: bar))
            p.closeSubpath()
            return p
        }
        let body = max(bodyWidth, topWidth)
        let bl = cx - body / 2, br = cx + body / 2
        let bottom = bar + bodyHeight
        let flare = (body - topWidth) / 2
        let s = shoulderRadius
        // The neck keeps the strip's width down to `bar` (so the menu bar band never widens); the concave
        // shoulders and the wide body start below it.
        let top = bar + s
        let c = max(0, min(Self.bodyCorner, flare - s, (bottom - top) / 3))
        let r = max(0, min(Self.bottomCorner, (bottom - top) / 2, body / 2))
        p.move(to: CGPoint(x: tl, y: y0))
        p.addLine(to: CGPoint(x: tr, y: y0))
        // right: neck down, concave shoulder out, body top edge, convex corner, side, big bottom corner
        p.addLine(to: CGPoint(x: tr, y: bar))
        p.addQuadCurve(to: CGPoint(x: tr + s, y: top), control: CGPoint(x: tr, y: top))
        p.addLine(to: CGPoint(x: br - c, y: top))
        p.addQuadCurve(to: CGPoint(x: br, y: top + c), control: CGPoint(x: br, y: top))
        p.addLine(to: CGPoint(x: br, y: bottom - r))
        p.addQuadCurve(to: CGPoint(x: br - r, y: bottom), control: CGPoint(x: br, y: bottom))
        p.addLine(to: CGPoint(x: bl + r, y: bottom))
        p.addQuadCurve(to: CGPoint(x: bl, y: bottom - r), control: CGPoint(x: bl, y: bottom))
        p.addLine(to: CGPoint(x: bl, y: top + c))
        p.addQuadCurve(to: CGPoint(x: bl + c, y: top), control: CGPoint(x: bl, y: top))
        p.addLine(to: CGPoint(x: tl - s, y: top))
        p.addQuadCurve(to: CGPoint(x: tl, y: bar), control: CGPoint(x: tl, y: top))
        p.addLine(to: CGPoint(x: tl, y: y0))
        p.closeSubpath()
        return p
    }
}
