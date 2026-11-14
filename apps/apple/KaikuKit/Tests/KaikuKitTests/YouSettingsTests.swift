import XCTest
@testable import KaikuKit

/// You → Sharing and permissions: every choice is a row that can be read at a glance (a symbol, a title, one
/// short line), and where the row shows a short form, the whole consent text is still there to be shown in full.
@MainActor
final class YouSettingsTests: XCTestCase {
    override func setUp() { L10n.shared.language = .en }

    func testEveryChoiceHasASymbolATitleAndOneShortLine() {
        for s in Signal.allCases {
            XCTAssertFalse(s.symbol.isEmpty, s.rawValue)
            for lang in [KaikuLanguage.en, .fi] {
                XCTAssertTrue(L10n.shared.has("sig.\(s.rawValue).t", lang), "title \(s.rawValue) \(lang)")
                XCTAssertTrue(L10n.shared.has(s.wholeKey, lang), "whole text \(s.rawValue) \(lang)")
                XCTAssertTrue(L10n.shared.has(s.lineKey, lang), "row line \(s.rawValue) \(lang)")
            }
            // One line in the Mac's sheet, two or three on a small phone: never a paragraph in a row.
            XCTAssertLessThanOrEqual(L10n.shared.string(s.lineKey, lang: .en).count, 70, s.rawValue)
        }
    }

    func testAShortFormNeverReplacesTheWholeText() {
        let short = Signal.allCases.filter(\.hasShortForm)
        XCTAssertEqual(Set(short), [.camera, .watch, .transcripts, .see])
        for s in Signal.allCases {
            if s.hasShortForm {
                XCTAssertEqual(s.lineKey, "sig.\(s.rawValue).s")
                // The paragraph is longer than its row line, and it is the one `SharingInFull` shows under the list.
                XCTAssertGreaterThan(L10n.shared.string(s.wholeKey, lang: .en).count,
                                     L10n.shared.string(s.lineKey, lang: .en).count, s.rawValue)
            } else {
                XCTAssertEqual(s.lineKey, "sig.\(s.rawValue).d", "a short text is the row line itself")
            }
        }
    }

    /// The list is the device's own signals, each once, and showing it never switches one on.
    func testTheListIsEverySignalOfTheDeviceAndNothingNewIsOnByDefault() {
        let list = Signal.forThisDevice
        XCTAssertEqual(Set(list).count, list.count)
        XCTAssertTrue(list.contains(.transcripts))
        XCTAssertEqual(Signal.allCases.filter(\.defaultOn), [.checkins, .walks])
        for s in [Signal.camera, .transcripts, .see, .voice, .mac, .watch] { XCTAssertFalse(s.defaultOn, s.rawValue) }
    }

    func testTheCopyOfTheRows() {
        for key in ["you.pauseall.s", "you.sec.devices", "you.service", "you.service.host", "share.count", "share.sub", "share.full",
                    "quick.state.on", "quick.state.off", "quick.set.on.s", "quick.set.bar.s", "quick.set.captions.s", "quick.set.double.s"] {
            XCTAssertTrue(L10n.shared.has(key, .en) && L10n.shared.has(key, .fi), key)
        }
        XCTAssertEqual(T("share.count", ["n": "2", "m": "5"]), "2 of 5 on")
        XCTAssertEqual(T("you.service.host", ["host": "kaiku.local"]), "Connected · kaiku.local")
    }
}
