import CoreGraphics
import SwiftUI
import XCTest
@testable import KaikuKit

/// Everything in the notch island's drop panel lives inside the island: Kaiku's frame (with its floating z's, drawn
/// light and 1.6× on black, at the far end of their drift and Kaiku's breath) sits inside the panel's content rect
/// (≥ 16 pt from every edge), in peek and expanded, at 1× and 2× after pixel snapping.
final class MacIslandLayoutTests: XCTestCase {
    func find(_ id: String, in p: MascotSpec.Part) -> MascotSpec.Part? {
        if p.id == id { return p }
        for c in p.children { if let f = find(id, in: c) { return f } }
        return nil
    }

    /// The z's extent in viewBox units: shape bounds (+ stroke), on-dark scale about the pivot, the sleepy drift,
    /// and the root's breath scale.
    func zBounds() throws -> CGRect {
        let spec = MascotSpec.shared
        let z = try XCTUnwrap(find("z", in: spec.root))
        var r = CGRect.null
        for s in z.shapes {
            guard case .path(let p) = s.kind else { continue }
            r = r.union(p.boundingRect.insetBy(dx: -s.strokeWidth, dy: -s.strokeWidth))
        }
        let k = MacIslandLayout.onDarkZScale
        r = CGRect(x: z.pivot.x + (r.minX - z.pivot.x) * k, y: z.pivot.y + (r.minY - z.pivot.y) * k,
                   width: r.width * k, height: r.height * k)
        let sleepy = try XCTUnwrap(spec.states["sleepy"])
        var drift = r
        for tr in sleepy.tracks where tr.part == "z" && tr.prop == .translate {
            for (_, v) in tr.keys { if let v { drift = drift.union(r.offsetBy(dx: v.a, dy: v.b)) } }
        }
        // Breath: the root scales up to 1.03 about its pivot.
        let p = spec.root.pivot, s = 1.03
        return CGRect(x: p.x + (drift.minX - p.x) * s, y: p.y + (drift.minY - p.y) * s,
                      width: drift.width * s, height: drift.height * s)
    }

    func testZsStayInsideKaikusCanvas() throws {
        let vb = MascotSpec.shared.viewBox
        let z = try zBounds()
        XCTAssertTrue(vb.contains(z), "z \(z) leaves the viewBox \(vb)")
    }

    func testMascotAndZsInsideThePanelAtEveryStateAndScale() throws {
        let vb = MascotSpec.shared.viewBox
        let z = try zBounds()
        for expanded in [false, true] {
            let panel = CGRect(origin: .zero, size: MacIslandLayout.size(expanded: expanded))
            let content = MacIslandLayout.contentRect(expanded: expanded)
            let m = MacIslandLayout.mascotRect(expanded: expanded)
            let k = m.width / vb.width
            let zr = CGRect(x: m.minX + (z.minX - vb.minX) * k, y: m.minY + (z.minY - vb.minY) * k,
                            width: z.width * k, height: z.height * k)
            for scale in [1.0, 2.0] {
                func snap(_ r: CGRect) -> CGRect {
                    CGRect(x: (r.minX * scale).rounded(.down) / scale, y: (r.minY * scale).rounded(.down) / scale,
                           width: (r.width * scale).rounded(.up) / scale, height: (r.height * scale).rounded(.up) / scale)
                }
                XCTAssertTrue(content.contains(snap(m)), "mascot \(m) outside \(content) expanded=\(expanded) @\(scale)x")
                XCTAssertTrue(content.contains(snap(zr)), "z's \(zr) outside \(content) expanded=\(expanded) @\(scale)x")
                XCTAssertTrue(panel.contains(snap(m)))
            }
            XCTAssertGreaterThanOrEqual(m.minY, 16)
            XCTAssertGreaterThanOrEqual(panel.maxY - m.maxY, 16)
            XCTAssertGreaterThanOrEqual(m.minX, 16)
            XCTAssertGreaterThanOrEqual(m.width, 120)
            XCTAssertLessThanOrEqual(m.width, 140)
        }
    }
}
