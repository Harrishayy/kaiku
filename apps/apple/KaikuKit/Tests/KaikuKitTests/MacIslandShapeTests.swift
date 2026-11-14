import SwiftUI
import XCTest
@testable import KaikuKit

/// The island silhouette: the menu-bar band is exactly the collapsed width; the body below is the expanded width;
/// concave shoulders join them; collapsed is only the strip.
final class MacIslandShapeTests: XCTestCase {
    let rect = CGRect(x: 0, y: 0, width: 520, height: 260)   // the window, origin top-left
    let top: CGFloat = 305, menuBar: CGFloat = 32
    var cx: CGFloat { rect.midX }

    func testExpandedSilhouette() {
        let body = MacIslandLayout.expanded.width
        let shape = MacIslandShape(topWidth: top, bodyWidth: body, bodyHeight: MacIslandLayout.bodyHeight(expanded: true), menuBar: menuBar)
        let p = shape.path(in: rect)
        XCTAssertGreaterThan(shape.shoulderRadius, 0)
        // Menu bar band (every row from the top of the screen down to the menu bar): exactly the collapsed width.
        for y in stride(from: 0.5, to: menuBar, by: 1) {
            XCTAssertTrue(p.contains(CGPoint(x: cx - top / 2 + 0.5, y: y)), "y \(y)")
            XCTAssertTrue(p.contains(CGPoint(x: cx + top / 2 - 0.5, y: y)), "y \(y)")
            XCTAssertFalse(p.contains(CGPoint(x: cx - top / 2 - 0.5, y: y)), "band wider than the strip at y \(y)")
            XCTAssertFalse(p.contains(CGPoint(x: cx + top / 2 + 0.5, y: y)), "band wider than the strip at y \(y)")
        }
        // Body: the expanded width (mid-height, away from the corners).
        let mid = menuBar + MacIslandShape.shoulder + 80
        XCTAssertTrue(p.contains(CGPoint(x: cx - body / 2 + 0.5, y: mid)))
        XCTAssertTrue(p.contains(CGPoint(x: cx + body / 2 - 0.5, y: mid)))
        XCTAssertFalse(p.contains(CGPoint(x: cx - body / 2 - 0.5, y: mid)))
        XCTAssertEqual(p.boundingRect.width, body, accuracy: 0.5)
        XCTAssertEqual(p.boundingRect.minY, 0, accuracy: 0.01)                    // starts at the very top
        // Concave shoulder: the corner just outside the neck below the menu bar is filled, the band above isn't.
        let s = shape.shoulderRadius
        XCTAssertTrue(p.contains(CGPoint(x: cx + top / 2 + 1, y: menuBar + s - 0.5)))
        XCTAssertFalse(p.contains(CGPoint(x: cx + top / 2 + s - 1, y: menuBar + 1)))
    }

    func testCollapsedIsOnlyTheStrip() {
        let shape = MacIslandShape(topWidth: 185, bodyWidth: 185, bodyHeight: 0, menuBar: menuBar)
        let b = shape.path(in: rect).boundingRect
        XCTAssertEqual(b.width, 185, accuracy: 0.5)
        XCTAssertEqual(b.height, menuBar, accuracy: 0.5)
        XCTAssertEqual(shape.shoulderRadius, 0)
    }

    func testPillSitsBelowTheMenuBar() {
        let shape = MacIslandShape(topWidth: 0, bodyWidth: 440, bodyHeight: 180, menuBar: 25, pill: true)
        let b = shape.path(in: rect).boundingRect
        XCTAssertEqual(b.minY, 25 + MacIslandShape.pillGap, accuracy: 0.5)
        XCTAssertEqual(b.width, 440, accuracy: 0.5)
    }
}
