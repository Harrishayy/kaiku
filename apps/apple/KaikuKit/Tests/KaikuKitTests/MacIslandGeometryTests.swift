import CoreGraphics
import XCTest
@testable import KaikuKit

/// Notch island geometry: part of the menu bar on a notch screen, a drop below the menu bar elsewhere.
final class MacIslandGeometryTests: XCTestCase {
    /// The lead's MacBook: 1512 × 982 pt, menu bar 32, notch x 665…850.
    let notchScreen = MacScreenInfo(frame: CGRect(x: 0, y: 0, width: 1512, height: 982),
                                    visibleFrame: CGRect(x: 0, y: 0, width: 1512, height: 950), safeTop: 32,
                                    auxLeft: CGRect(x: 0, y: 950, width: 665, height: 32),
                                    auxRight: CGRect(x: 850, y: 950, width: 662, height: 32), isMain: true)

    func testNotchScreen() {
        let g = MacIslandGeometry.compute(notchScreen)
        XCTAssertEqual(g.notch, CGRect(x: 665, y: 950, width: 185, height: 32))
        XCTAssertEqual(g.collapsed, CGRect(x: 605, y: 950, width: 305, height: 32))   // notch + 60 pt wings, menu-bar tall
        XCTAssertEqual(g.centerX, 757.5)
        XCTAssertEqual(g.dropTop, 950)                                                 // content hangs below the menu bar
        let f = g.dropFrame(CGSize(width: 460, height: 170), extraBelow: 30)
        XCTAssertEqual(f.maxY, 950)
        XCTAssertEqual(f.midX, 757.5, accuracy: 0.5)
    }

    func testWingsStayInTheFreeGap() {
        var s = notchScreen
        s.auxRight = CGRect(x: 850, y: 950, width: 40, height: 32)
        XCTAssertEqual(MacIslandGeometry.compute(s).wing, 40)
    }

    func testNonNotchScreenDropsBelowTheMenuBar() {
        let s = MacScreenInfo(frame: CGRect(x: 0, y: 0, width: 1440, height: 900),
                              visibleFrame: CGRect(x: 0, y: 0, width: 1440, height: 875), isMain: true)
        let g = MacIslandGeometry.compute(s)
        XCTAssertNil(g.collapsed)
        XCTAssertNil(g.notch)
        XCTAssertEqual(g.dropTop, 875)
        XCTAssertEqual(g.menuBar, 25)
        XCTAssertEqual(g.centerX, 720)
    }

    func testExternalDisplayAndPicking() {
        let external = MacScreenInfo(frame: CGRect(x: 1512, y: -200, width: 2560, height: 1440),
                                     visibleFrame: CGRect(x: 1512, y: -200, width: 2560, height: 1415))
        let g = MacIslandGeometry.compute(external)
        XCTAssertNil(g.collapsed)
        XCTAssertEqual(g.centerX, 1512 + 1280)
        XCTAssertEqual(g.dropTop, 1215)
        // The notch screen wins even when listed second; no notch → main; else the first.
        XCTAssertEqual(MacIslandGeometry.pick([external, notchScreen]), notchScreen)
        var main = external
        main.isMain = true
        let plain = MacScreenInfo(frame: CGRect(x: 0, y: 0, width: 1440, height: 900),
                                  visibleFrame: CGRect(x: 0, y: 0, width: 1440, height: 875))
        XCTAssertEqual(MacIslandGeometry.pick([plain, main]), main)
        XCTAssertEqual(MacIslandGeometry.pick([plain]), plain)
    }
}
