import SwiftUI

/// A square stage for a ring + Kaiku that takes whatever height the fixed game screen has left (up to `maxSide`),
/// so Breathe and Tell Kaiku never push their header off the top on a small phone or at large text.
struct RingStage<Content: View>: View {
    var maxSide: CGFloat = 250
    var minSide: CGFloat = 120
    @ViewBuilder let content: (_ side: CGFloat) -> Content

    var body: some View {
        GeometryReader { g in
            let side = max(minSide, min(maxSide, g.size.width, g.size.height))
            content(side)
                .frame(width: side, height: side)
                .position(x: g.size.width / 2, y: g.size.height / 2)
        }
        .frame(minHeight: minSide, maxHeight: maxSide)
    }
}
