import XCTest
@testable import KaikuKit

// The "Kaiku bot" tab: the MQTT wire (BotBus.swift), what it subscribes to and drops, the robot's address, the
// reducer that turns heard envelopes into the screen (BotState.swift), the words (BotWords.swift), and when the
// tab listens (BotModel.swift). `BotBrokerTests` below runs the real client against a throwaway mosquitto.

final class BotWireTests: XCTestCase {
    func testConnectIsMQTT311WithCleanSessionAndKeepAlive() {
        let d = [UInt8](MQTTOut.connect(clientID: "ab", keepAlive: 30))
        XCTAssertEqual(d, [0x10, 14, 0, 4, 0x4D, 0x51, 0x54, 0x54, 4, 0x02, 0, 30, 0, 2, 0x61, 0x62])
        let signed = [UInt8](MQTTOut.connect(clientID: "a", keepAlive: 30, user: "u", password: "p"))
        XCTAssertEqual(signed[9], 0xC2, "user + password + clean session")
        XCTAssertEqual(Array(signed.suffix(6)), [0, 1, 0x75, 0, 1, 0x70])
        XCTAssertEqual([UInt8](MQTTOut.connect(clientID: "a", keepAlive: 30, user: "", password: "p"))[9], 0x02,
                       "no name: no password either (MQTT 3.1.1 forbids a password without a user name)")
    }

    func testSubscribeAsksQoS0ForEachFilter() {
        let d = [UInt8](MQTTOut.subscribe(id: 1, filters: ["a/#", "b"]))
        XCTAssertEqual(d, [0x82, 12, 0, 1, 0, 3, 0x61, 0x2F, 0x23, 0, 0, 1, 0x62, 0])
    }

    func testTheOnlyThingTheClientCanPublishIsAMicrophoneFrame() throws {
        // Every other packet the client can make, by its type nibble: never 3 (PUBLISH).
        let all = [MQTTOut.connect(clientID: "x", keepAlive: 30, user: "u", password: "p"),
                   MQTTOut.subscribe(id: 1, filters: BotTopics.filters(home: "h")), MQTTOut.pingreq, MQTTOut.disconnect,
                   MQTTOut.puback(7), MQTTOut.pubrec(7), MQTTOut.pubcomp(7)]
        XCTAssertEqual(all.map { $0.first! >> 4 }, [1, 8, 12, 14, 4, 5, 7])
        // The one PUBLISH (D56): a whole 640-byte frame, QoS 0, not retained, on the phone's microphone topic only.
        let frame = Data((0..<640).map { UInt8($0 % 251) })
        let topic = try XCTUnwrap(BotMicWire.topic(home: "h"))
        XCTAssertEqual(topic, "kaiku/v1/h/audio/phone/mic")
        let p = try XCTUnwrap(MQTTOut.micFrame(topic: topic, frame: frame))
        XCTAssertEqual(p.first, 0x30)
        var dec = MQTTDecoder()
        XCTAssertEqual(try dec.feed(p), [.publish(topic: topic, payload: frame, qos: 0, id: nil)])
        XCTAssertNil(MQTTOut.micFrame(topic: topic, frame: Data(count: 100)), "never a piece of a frame")
        XCTAssertNil(MQTTOut.micFrame(topic: "kaiku/v1/h/cmd/head", frame: frame), "never a command, never an envelope topic")
        XCTAssertNil(MQTTOut.micFrame(topic: "kaiku/v1/h/audio/head/mic", frame: frame), "never as the head")
        XCTAssertNil(BotMicWire.topic(home: nil)); XCTAssertNil(BotMicWire.topic(home: "+"))
    }

    func testMicrophonePcmBecomesWholeFramesInOrder() {
        var f = BotMicFramer()
        let pcm = Data((0..<1500).map { UInt8($0 % 256) })
        XCTAssertTrue(f.feed(pcm.prefix(600)).isEmpty)
        let out = f.feed(pcm.dropFirst(600))
        XCTAssertEqual(out.count, 2)
        XCTAssertEqual(out[0] + out[1], pcm.prefix(1280))
    }

    func testThePhonesMicrophoneIsSentOnlyWhileTheHubHoldsTheRobotsOpen() {
        var s = BotState()
        let t0 = Date(timeIntervalSince1970: 1_800_000_000)
        XCTAssertFalse(s.micHeld(now: t0))
        s.take(BotEnvelope(type: "cmd.head", source: "hub", payload: .object(["mic": .string("open")])), now: t0)
        XCTAssertTrue(s.micHeld(now: t0.addingTimeInterval(3)))
        XCTAssertFalse(s.micHeld(now: t0.addingTimeInterval(6)), "the hub stopped saying so")
        s.take(BotEnvelope(type: "cmd.head", source: "hub", payload: .object(["mic": .string("close")])), now: t0.addingTimeInterval(1))
        XCTAssertFalse(s.micHeld(now: t0.addingTimeInterval(2)))
    }

    func testRemainingLengthAtEveryBoundary() throws {
        for n in [0, 1, 127, 128, 16_383, 16_384, 100_000] {
            let body = Data(repeating: 0x41, count: n)
            var p = Data([0x30]); p.append(MQTTOut.remainingLength(n + 3)); p.append(contentsOf: [0, 1, 0x74]); p.append(body)
            var dec = MQTTDecoder()
            XCTAssertEqual(try dec.feed(p), [.publish(topic: "t", payload: body, qos: 0, id: nil)], "\(n)")
            XCTAssertEqual(dec.pending, 0)
        }
        XCTAssertEqual([UInt8](MQTTOut.remainingLength(2_097_152)), [0x80, 0x80, 0x80, 0x01])
    }

    func testPacketsArriveInAnyPieces() throws {
        var wire = Data()
        wire.append(contentsOf: [0x20, 0x02, 0x00, 0x00])                       // connack ok
        wire.append(contentsOf: [0x90, 0x06, 0x00, 0x01, 0, 0, 0, 0])           // suback: four filters granted 0
        let payload = Data(String(repeating: "{\"type\":\"raw.head.tap\"}", count: 400).utf8)   // ~9 kB
        var pub = Data([0x30]); let topic = Data("kaiku/v1/h/raw/head/tap".utf8)
        pub.append(MQTTOut.remainingLength(2 + topic.count + payload.count))
        pub.append(contentsOf: [0, UInt8(topic.count)]); pub.append(topic); pub.append(payload)
        wire.append(pub)
        wire.append(contentsOf: [0xD0, 0x00])                                   // pingresp
        let want: [MQTTIn] = [.connack(code: 0), .suback(id: 1, granted: [0, 0, 0, 0]),
                              .publish(topic: "kaiku/v1/h/raw/head/tap", payload: payload, qos: 0, id: nil), .pingresp]
        // one byte at a time
        var dec = MQTTDecoder(); var got: [MQTTIn] = []
        for b in wire { got += try dec.feed(Data([b])) }
        XCTAssertEqual(got, want)
        // all at once
        dec = MQTTDecoder()
        XCTAssertEqual(try dec.feed(wire), want)
        // in odd chunks
        dec = MQTTDecoder(); got = []
        var i = 0
        for size in [3, 1, 7, 900, 2, 5000, 1] + Array(repeating: 1500, count: 10) where i < wire.count {
            got += try dec.feed(wire.subdata(in: i..<min(wire.count, i + size))); i += size
        }
        XCTAssertEqual(got, want)
    }

    func testAQoS1DeliveryCarriesItsIdAndQoS2IsReadToo() throws {
        var dec = MQTTDecoder()
        let p1 = Data([0x32, 7, 0, 1, 0x74, 0x12, 0x34, 0x68, 0x69])
        XCTAssertEqual(try dec.feed(p1), [.publish(topic: "t", payload: Data("hi".utf8), qos: 1, id: 0x1234)])
        let p2 = Data([0x34, 5, 0, 1, 0x74, 0x00, 0x09])
        XCTAssertEqual(try dec.feed(p2), [.publish(topic: "t", payload: Data(), qos: 2, id: 9)])
        XCTAssertEqual(try dec.feed(Data([0x62, 2, 0, 9])), [.pubrel(id: 9)])
        XCTAssertEqual(try dec.feed(Data([0xB0, 2, 0, 3])), [.other(type: 11)], "an unsubscribe ack is read and let go")
    }

    func testMalformedInputThrowsAndNeverCrashes() {
        func throwsOn(_ bytes: [UInt8], _ why: String) {
            var dec = MQTTDecoder()
            XCTAssertThrowsError(try dec.feed(Data(bytes)), why)
        }
        throwsOn([0x30, 0xFF, 0xFF, 0xFF, 0xFF, 0x01], "a five-byte remaining length")
        throwsOn([0x36, 3, 0, 1, 0x74], "QoS 3")
        throwsOn([0x30, 3, 0, 9, 0x74], "a topic longer than its packet")
        throwsOn([0x32, 3, 0, 1, 0x74], "QoS 1 without a packet id")
        throwsOn([0x30, 4, 0, 2, 0xC3, 0x28], "a topic that is not UTF-8")
        throwsOn([0x20, 3, 0, 0, 0], "a CONNACK of the wrong length")
        throwsOn([0x00, 0], "the reserved packet type 0")
        throwsOn([0x30, 0xFF, 0xFF, 0xFF, 0x7F], "a packet larger than the client takes")
        // Random bytes: whatever comes, the decoder answers or throws; it does not trap.
        var rng = SystemRandomNumberGenerator()
        for _ in 0..<3000 {
            var dec = MQTTDecoder()
            let n = Int.random(in: 0...64, using: &rng)
            let junk = Data((0..<n).map { _ in UInt8.random(in: 0...255, using: &rng) })
            _ = try? dec.feed(junk)
            _ = try? dec.feed(junk)
        }
    }

    func testOnlyTheFourKindsAreAskedForNeverAudio() {
        XCTAssertEqual(BotTopics.filters(home: "demo-aino"),
                       ["kaiku/v1/demo-aino/raw/#", "kaiku/v1/demo-aino/cmd/#", "kaiku/v1/demo-aino/obs/#", "kaiku/v1/demo-aino/health/#"])
        XCTAssertEqual(BotTopics.filters(home: nil).first, "kaiku/v1/+/raw/#")
        XCTAssertEqual(BotTopics.filters(home: "a/#").first, "kaiku/v1/+/raw/#", "a home id is never a wildcard")
        for f in BotTopics.filters(home: nil) + BotTopics.filters(home: "h") {
            XCTAssertFalse(f.contains("audio")); XCTAssertNotEqual(f, "kaiku/v1/#"); XCTAssertFalse(f.hasPrefix("#"))
        }
        XCTAssertTrue(BotTopics.allowed("kaiku/v1/h/raw/head/tap", home: "h"))
        XCTAssertTrue(BotTopics.allowed("kaiku/v1/h/health/head", home: "h"))
        XCTAssertTrue(BotTopics.allowed("kaiku/v1/x/obs/ritual", home: nil))
        XCTAssertFalse(BotTopics.allowed("kaiku/v1/h/audio/head/mic", home: "h"))
        XCTAssertFalse(BotTopics.allowed("kaiku/v1/h/audio/head/speaker", home: nil))
        XCTAssertFalse(BotTopics.allowed("kaiku/v1/h/raw/audio/x", home: "h"), "nothing with an audio level")
        XCTAssertFalse(BotTopics.allowed("kaiku/v1/other/raw/head/tap", home: "h"))
        XCTAssertFalse(BotTopics.allowed("kaiku/v1/h/log/hub", home: "h"))
        XCTAssertFalse(BotTopics.allowed("something/else", home: nil))
    }

    func testTheRobotsAddress() {
        XCTAssertEqual(BotAddress.parse("192.168.1.20"), BotAddress(host: "192.168.1.20", port: 1883))
        XCTAssertEqual(BotAddress.parse(" 192.168.1.20:1884 "), BotAddress(host: "192.168.1.20", port: 1884))
        XCTAssertEqual(BotAddress.parse("mqtt://Kaiku-Hub.local:1883/"), BotAddress(host: "kaiku-hub.local", port: 1883))
        XCTAssertEqual(BotAddress.parse("[fe80::1]:1999"), BotAddress(host: "fe80::1", port: 1999))
        for bad in ["", "a b", "host:0", "host:99999", "host:x", "user@host", "a/b", "[::1"] { XCTAssertNil(BotAddress.parse(bad), bad) }
        XCTAssertEqual(BotAddress(host: "10.0.0.2", port: 1883).text, "10.0.0.2")
        XCTAssertEqual(BotAddress(host: "10.0.0.2", port: 1884).text, "10.0.0.2:1884")
        XCTAssertEqual(BotAddress.guess(serviceURL: URL(string: "http://192.168.1.5:8000")), BotAddress(host: "192.168.1.5"))
        XCTAssertEqual(BotAddress.guess(serviceURL: URL(string: "http://127.0.0.1:8000")), BotAddress(host: "127.0.0.1"))
        XCTAssertNil(BotAddress.guess(serviceURL: URL(string: "https://kaiku.modal.run")), "a cloud host is never the robot")
        XCTAssertNil(BotAddress.guess(serviceURL: URL(string: "http://8.8.8.8")))
        XCTAssertNil(BotAddress.guess(serviceURL: nil))
        XCTAssertTrue(BotAddress.isLocal("172.20.1.1")); XCTAssertFalse(BotAddress.isLocal("172.32.1.1"))
        XCTAssertTrue(BotAddress.isLocal("10.1.2.3")); XCTAssertTrue(BotAddress.isLocal("169.254.3.4"))
        XCTAssertTrue(BotAddress.isLocal("fd12::1")); XCTAssertFalse(BotAddress.isLocal("fdexample.com"))
    }
}

// MARK: the reducer, on the contract's own examples

final class BotStateTests: XCTestCase {
    let t0 = Date(timeIntervalSince1970: 1_800_000_000)

    /// One envelope per type from contracts/schemas/examples.json, the generated examples of `registry.EXAMPLES`
    /// (so every field name here is the contract's).
    func examples() throws -> [String: Data] {
        let all = try XCTUnwrap(json("contracts/schemas/examples.json") as? [String: [String: Any]])
        // The file holds each type's example payload; the envelope around it is the one its sender would make.
        var out: [String: Data] = [:]
        for (type, payload) in all {
            let parts = type.split(separator: ".")
            let source = type == "health" ? "head" : type == "log" ? "hub" : type == "raw.hub.face" ? "sensors"
                : parts.first == "raw" ? String(parts[1]) : "hub"
            out[type] = try JSONSerialization.data(withJSONObject: ["v": 1, "id": "0199b2c4-7c1e-7a55-9a3e-2f1d6b7c8e90",
                "ts": "2026-11-14T10:00:00.000Z", "home_id": "demo-aino", "source": source, "type": type, "payload": payload, "sim": true])
        }
        return out
    }

    func env(_ type: String, _ source: String, _ payload: [String: Any], sim: Bool = true) -> BotEnvelope {
        let d = try! JSONSerialization.data(withJSONObject: ["v": 1, "id": "x", "ts": "2026-11-14T10:00:00.000Z", "home_id": "h",
                                                             "source": source, "type": type, "payload": payload, "sim": sim])
        return BotEnvelope.decode(d)!
    }

    func testEveryContractExampleIsReadAndShown() throws {
        var s = BotState()
        let ex = try examples()
        XCTAssertGreaterThan(ex.count, 30)
        for (type, data) in ex.sorted(by: { $0.key < $1.key }) {
            let e = try XCTUnwrap(BotEnvelope.decode(data), type)
            XCTAssertEqual(e.type, type)
            s.take(e, now: t0)
        }
        XCTAssertEqual(s.messages, ex.count)
        XCTAssertFalse(s.feed.isEmpty)
        XCTAssertTrue(s.feed.allSatisfy { !$0.line.isEmpty && !$0.line.contains("⟨") }, "every line has words, no missing key")
        XCTAssertEqual(s.ear, 4, "raw.head.ear value")
        XCTAssertEqual(s.eyes, "wide"); XCTAssertEqual(s.panMode, "track")
        XCTAssertEqual(s.face?.x, -0.2); XCTAssertEqual(s.face?.size, 0.3)
        XCTAssertEqual(s.distanceCm, 58); XCTAssertEqual(s.lux, 210)
        XCTAssertEqual(s.panDeg, -12.5)
        XCTAssertEqual(s.hr, 68); XCTAssertEqual(s.rmssd, 42); XCTAssertEqual(s.breath, 6)
        XCTAssertEqual(s.pulseAsked, true, "cmd.sensors ppg: start")
        XCTAssertEqual(s.pulseSamples, 5)
        XCTAssertEqual(s.tapCount, 1)
        XCTAssertEqual(s.buttonPressed, true)
        XCTAssertEqual(s.parts["head"]?.version, "0.1.0", "the health example")
        XCTAssertEqual(s.parts["head"]?.sim, true)
        XCTAssertNil(BotEnvelope.decode(Data(#"{"type":"raw.head.ear","source":"head","payload":{"value":1,"delta":0}}"#.utf8))?
            .payload["value"]?.bool, "a 1 is a number, not true")
        let obs = ex.keys.filter { $0.hasPrefix("obs.") }.count
        XCTAssertEqual(s.records.count, min(obs, BotState.recordsMax))
        // The safety flag is named, nothing more (no trigger, no severity).
        let flag = try XCTUnwrap(s.records.first { $0.line == T("bot.rec.safety") })
        XCTAssertFalse(flag.line.lowercased().contains("manual") || flag.line.lowercased().contains("high"))
    }

    /// The hub's trace (`raw.hub.trace`, payloads.HubTrace), as the hub sends it.
    func testWhatKaikuSaidHowAndWhatItUsed() {
        var s = BotState()
        s.take(env("raw.hub.trace", "hub", ["kind": "session", "detail": "open"]), now: t0)
        s.take(env("raw.hub.trace", "hub", ["kind": "said", "text": "How are you today?", "by": "live"]), now: t0)
        s.take(env("raw.hub.trace", "hub", ["kind": "heard"]), now: t0)
        s.take(env("raw.hub.trace", "hub", ["kind": "tool", "tool": "ask_mind", "by": "gemma", "ms": 2300, "ok": true]), now: t0)
        s.take(env("raw.hub.trace", "hub", ["kind": "tool", "tool": "feel", "ms": 40, "ok": true]), now: t0)
        s.take(env("raw.hub.trace", "hub", ["kind": "tool", "tool": "recall", "ms": 8100, "ok": false]), now: t0)
        XCTAssertEqual(s.conversationOpen, true)
        XCTAssertEqual(s.said.first?.text, "How are you today?"); XCTAssertEqual(s.said.first?.by, "live")
        XCTAssertEqual(s.heard, 1)
        XCTAssertEqual(BotWords.tool(s.tools[2]), "Asked its mind (ask_mind) · answered by Gemma in 2.3 s")
        XCTAssertEqual(BotWords.tool(s.tools[1]), "Chose how to answer (feel) · in 40 ms", "feel: the tool's name, never its manner cue")
        XCTAssertEqual(BotWords.tool(s.tools[0]), "Looked in its notebook (recall) · no answer after 8.1 s")
        XCTAssertTrue(s.feed.contains { $0.line == "Kaiku said: “How are you today?”" })
        // Tap it back, live.
        s.take(env("raw.hub.trace", "hub", ["kind": "music", "detail": "song", "bpm": 102]), now: t0)
        s.take(env("raw.hub.trace", "hub", ["kind": "game", "detail": "level:2", "bpm": 124]), now: t0)
        s.take(env("raw.hub.trace", "hub", ["kind": "game", "detail": "your_turn"]), now: t0.addingTimeInterval(8))
        XCTAssertEqual(s.level, 2); XCTAssertEqual(s.songBpm, 124); XCTAssertNotNil(s.yourTurnAt)
        s.take(env("raw.hub.trace", "hub", ["kind": "game", "detail": "band:great"]), now: t0.addingTimeInterval(14))
        XCTAssertEqual(s.band, "great")
        XCTAssertEqual(s.feed.first?.line, "Great")
        s.take(env("raw.hub.trace", "hub", ["kind": "session", "detail": "close"]), now: t0.addingTimeInterval(20))
        XCTAssertEqual(s.conversationOpen, false)
    }

    func testThePersonsWordsAreNeverShownEvenIfSent() {
        var s = BotState()
        // The contract refuses this; a misbehaving sender must still not put her words on the screen.
        s.take(env("raw.hub.trace", "hub", ["kind": "heard", "text": "I feel awful"]), now: t0)
        s.take(env("cmd.hub", "cloud", ["say": "I feel awful"]), now: t0)
        XCTAssertFalse(s.feed.contains { $0.line.contains("awful") })
        XCTAssertEqual(s.heard, 1)
    }

    func testTheMicrophoneIsOpenOnlyWhileItIsHeld() {
        var s = BotState()
        XCTAssertNil(s.micOpen(now: t0), "nothing heard: not known")
        s.take(env("health", "head", ["status": "ok", "version": "1", "uptime_s": 3, "details": ["audio": ["mic_open": false]]]), now: t0)
        XCTAssertEqual(s.micOpen(now: t0), false)
        s.take(env("cmd.head", "hub", ["mic": "open"]), now: t0)
        XCTAssertEqual(s.micOpen(now: t0.addingTimeInterval(1)), true)
        for i in 1...5 { s.take(env("cmd.head", "hub", ["mic": "open"]), now: t0.addingTimeInterval(Double(i) * 2)) }
        XCTAssertEqual(s.feed.filter { $0.line.hasPrefix("Microphone") }.count, 1, "held open is ONE line")
        XCTAssertEqual(s.feed.first?.count, 6)
        XCTAssertEqual(s.micOpen(now: t0.addingTimeInterval(19)), true, "the head's own limit is 10 s after the last open")
        XCTAssertEqual(s.micOpen(now: t0.addingTimeInterval(21)), false, "no open for 10 s: the head has closed it")
        s.take(env("cmd.head", "hub", ["mic": "open"]), now: t0.addingTimeInterval(30))
        s.take(env("cmd.head", "hub", ["mic": "close"]), now: t0.addingTimeInterval(31))
        XCTAssertEqual(s.micOpen(now: t0.addingTimeInterval(31.5)), false)
        // The head's own report counts too.
        s.take(env("health", "head", ["status": "ok", "version": "1", "uptime_s": 3, "details": ["audio": ["mic_open": true]]]), now: t0.addingTimeInterval(40))
        XCTAssertEqual(s.micOpen(now: t0.addingTimeInterval(41)), true)
    }

    func testFloodsAreOneLineUpdatedInPlace() {
        var s = BotState()
        for i in 0..<200 {
            s.take(env("raw.hub.face", "sensors", ["x_norm": 0.5, "y_norm": 0, "size": 0.25, "confidence": 0.9]), now: t0.addingTimeInterval(Double(i) * 0.1))
            s.take(env("raw.sensors.distance", "sensors", ["cm": 60]), now: t0.addingTimeInterval(Double(i) * 0.1))
        }
        XCTAssertEqual(s.feed.count, 2)
        XCTAssertEqual(s.feed.map(\.count).sorted(), [200, 200])
        XCTAssertEqual(s.someoneInView(now: t0.addingTimeInterval(20)), true)
        XCTAssertEqual(s.someoneInView(now: t0.addingTimeInterval(30)), false, "no face for two seconds: nobody in view")
        XCTAssertEqual(BotWords.face(s.face), "A face to the right, size 25 of 100")
        // A run of taps is one line with its tempo; the board's own clock gives it.
        for i in 0..<8 { s.take(env("raw.head.tap", "head", ["t_ms": 1000 + i * 600, "src": "imu"]), now: t0.addingTimeInterval(40 + Double(i) * 0.6)) }
        XCTAssertEqual(s.feed.first?.count, 8)
        XCTAssertEqual(s.tapTempo.map { Int($0.rounded()) }, 100)
        XCTAssertEqual(s.feed.first?.line, "Taps on the drum, about 100 a minute")
    }

    func testTheFeedKeepsAtMostThreeHundredLines() {
        var s = BotState()
        for i in 0..<500 { s.take(env("raw.head.button", "head", ["id": "head", "pressed": i % 2 == 0]), now: t0.addingTimeInterval(Double(i))) }
        XCTAssertEqual(s.feed.count, BotState.feedMax)
        XCTAssertEqual(s.messages, 500)
    }

    func testUnknownTypesAndFieldsAreAPlainLine() {
        var s = BotState()
        s.take(env("raw.hub.newthing", "hub", ["anything": [1, 2, 3]]), now: t0)
        s.take(env("cmd.head", "hub", ["blink": "twice"]), now: t0)
        s.take(env("raw.hub.trace", "hub", ["kind": "dance", "tool": 5]), now: t0)
        s.take(env("raw.head.ear", "head", ["value": "four"]), now: t0)
        s.take(env("obs.new_record", "hub", [:]), now: t0)
        s.take(env("health", "lamp", ["status": 3]), now: t0)
        XCTAssertEqual(s.messages, 6)
        XCTAssertEqual(s.feed.count, 6)
        XCTAssertEqual(s.records.first?.line, "Record: new record")
        XCTAssertNil(s.ear)
        XCTAssertNotNil(s.parts["lamp"])
        XCTAssertNil(BotEnvelope.decode(Data(repeating: 0, count: 640)), "an audio frame is not an envelope")
        XCTAssertNil(BotEnvelope.decode(Data("[1,2]".utf8)))
        XCTAssertNil(BotEnvelope.decode(Data("{\"payload\":{}}".utf8)), "no type: not an envelope")
    }

    func testTheRitualStepComesFromWhoeverSaidItLast() {
        var s = BotState()
        s.take(env("health", "hub", ["status": "ok", "version": "1", "uptime_s": 1, "details": ["ritual": "head:breathe", "head_mode": "follow"]]), now: t0)
        XCTAssertEqual(s.step, "breathe"); XCTAssertEqual(s.headMode, "follow")
        s.take(env("obs.ritual", "hub", ["step": "drum", "status": "started"]), now: t0.addingTimeInterval(1))
        XCTAssertEqual(s.step, "drum")
        s.take(env("cmd.head", "hub", ["show": "help"]), now: t0.addingTimeInterval(2))
        XCTAssertTrue(s.helpOn(now: t0.addingTimeInterval(3)))
        XCTAssertEqual(s.feed.first?.line, "Help numbers shown on the robot")
    }

    /// The tab's words are the person's: no state, verdict, score or clinical word, in English and under fi.
    func testNoStateOrVerdictWordInTheTabsCopy() throws {
        let o = try XCTUnwrap(json("apps/apple/KaikuKit/Sources/KaikuKit/Resources/copy.apple.json") as? [String: Any])
        let banned = try NSRegularExpression(pattern: #"(?i)\b(needs a call|change from (your )?usual|worse|better|low|decline|risk|diagnos\w*|relapse|symptom\w*|score|stable|alert)\b"#)
        var n = 0
        for lang in ["en", "fi"] {
            let table = try XCTUnwrap(o[lang] as? [String: String])
            for (k, v) in table where k.hasPrefix("bot.") || k.hasPrefix("tab.bot") {
                n += 1
                XCTAssertNil(banned.firstMatch(in: v, range: NSRange(v.startIndex..., in: v)), "\(lang) \(k): \(v)")
            }
        }
        XCTAssertGreaterThan(n, 400)
        // Every key a word family builds exists.
        for s in ["idle", "greet", "dial", "mood", "energy", "sleep", "breathe", "drum", "phq9", "nudge", "close", "done"] { XCTAssertTrue(L10n.shared.has("bot.step.\(s)", .fi), s) }
        for e in ["neutral", "happy", "sleepy", "wide", "listening", "thinking", "soft"] { XCTAssertTrue(L10n.shared.has("bot.eyes.\(e)", .fi), e) }
        for b in ["script", "live", "cached_voice", "notebook", "gemma", "flash", "argon", "rule"] { XCTAssertTrue(L10n.shared.has("bot.by.\(b)", .fi), b) }
        for p in ["head", "sensors", "hub", "friendlink", "glasses", "laptop", "phone", "cloud", "sim"] { XCTAssertTrue(L10n.shared.has("bot.part.\(p)", .fi), p) }
        for st in ["started", "completed", "skipped", "aborted"] { XCTAssertTrue(L10n.shared.has("bot.rec.ritual.\(st)", .fi), st) }
        for g in ["look_left", "look_right", "shake"] { XCTAssertTrue(L10n.shared.has("bot.gesture.\(g)", .fi)) }
        for c in ["off", "breathe", "glow", "pulse"] { XCTAssertTrue(L10n.shared.has("bot.chest.\(c)", .fi)) }
        for m in ["track", "still", "sway"] { XCTAssertTrue(L10n.shared.has("bot.pan.\(m)", .fi)) }
        for c in ["wake", "ok", "start_drum", "end_drum", "alert"] { XCTAssertTrue(L10n.shared.has("bot.chime.\(c)", .fi)) }
        for b in ["perfect", "great", "nice", "again"] { XCTAssertTrue(L10n.shared.has("bot.band.\(b)", .fi)) }
        for d in ["mood", "energy", "sleep"] { XCTAssertTrue(L10n.shared.has("bot.dial.\(d)", .fi)) }
        for t in ["feel", "recall", "remember", "forget", "ask_mind", "record_dial", "end_session", "suggest_nudge", "express",
                  "start_activity", "agree_activity", "start_phq9", "set_walk_goal", "log_walk_moment", "look_at_this",
                  "send_friend_ping", "suggest_activity", "other"] {
            XCTAssertTrue(L10n.shared.has("bot.tool.\(t)", .fi), t)
        }
    }

    /// The tool names the trace can carry are the registry's (contracts/schemas/companion_tools.json): each has words.
    func testEveryRegistryToolHasPlainWords() throws {
        let reg = try json("contracts/schemas/companion_tools.json")
        let names = Array(((reg as? [String: Any])?["tools"] as? [String: Any] ?? [:]).keys)
        XCTAssertGreaterThan(names.count, 5)
        for n in names { XCTAssertTrue(L10n.shared.has("bot.tool.\(n)", .en), "no words for the tool \(n)") }
    }
}

// MARK: when the tab listens

@MainActor
final class BotModelTests: XCTestCase {
    func defaults() -> UserDefaults {
        let d = UserDefaults(suiteName: "bot-tests-\(UUID().uuidString)")!
        return d
    }

    /// A model whose connections go to a free local port where nothing listens (never the real 1883).
    func model(_ d: UserDefaults) -> BotModel {
        let m = BotModel(defaults: d)
        let port = BotBrokerTests().freePort()
        m.makeClient = { _, home, user, password, state, message in
            BotBusClient(address: BotAddress(host: "127.0.0.1", port: port), home: home, user: user, password: password,
                         onState: state, onMessage: message)
        }
        return m
    }

    func testItListensOnlyWhileVisibleAndInFront() {
        let m = model(defaults())
        m.configure(serviceURL: URL(string: "https://kaiku.example.com"), home: "h")
        m.setVisible(true)
        XCTAssertNil(m.address, "a cloud host is not guessed as the robot")
        XCTAssertFalse(m.listening, "no address: nothing to listen to")
        m.configure(serviceURL: URL(string: "http://127.0.0.1:9"), home: "h")
        XCTAssertEqual(m.address, BotAddress(host: "127.0.0.1")); XCTAssertTrue(m.addressGuessed)
        m.setVisible(false); m.setVisible(true)
        XCTAssertTrue(m.listening)
        m.setInFront(false)
        XCTAssertFalse(m.listening, "background / another app in front / display asleep: closed at once")
        m.setInFront(true)
        XCTAssertTrue(m.listening)
        m.setVisible(false)
        XCTAssertFalse(m.listening, "leaving the tab closes it")
        XCTAssertEqual(m.link, .idle)
    }

    func testAProfileTheAppMadeForItselfListensToAnyHomeAndTheOverrideWins() {
        let d = defaults()
        let m = model(d)
        m.configure(serviceURL: nil, home: "device-0f3a")
        XCTAssertNil(m.home, "a device profile is not the robot's home: any home on the broker")
        m.configure(serviceURL: nil, home: "demo-aino")
        XCTAssertEqual(m.home, "demo-aino")
        d.set("aino-robot", forKey: BotModel.homeKey)
        m.configure(serviceURL: nil, home: "demo-aino")
        XCTAssertEqual(m.home, "aino-robot")
    }

    func testTheTypedAddressIsRememberedAndEmptyGoesBackToTheGuess() {
        let d = defaults()
        let m = model(d)
        m.configure(serviceURL: URL(string: "http://192.168.1.5:8000"), home: "h")
        XCTAssertFalse(m.setAddress("not an address!"))
        XCTAssertTrue(m.setAddress("192.168.1.30:1884"))
        XCTAssertEqual(m.address, BotAddress(host: "192.168.1.30", port: 1884)); XCTAssertFalse(m.addressGuessed)
        XCTAssertEqual(d.string(forKey: BotModel.addressKey), "192.168.1.30:1884")
        XCTAssertTrue(m.setAddress(""))
        XCTAssertEqual(m.address, BotAddress(host: "192.168.1.5"))
        m.setSignIn(user: "kaiku", password: "x")
        XCTAssertEqual(d.string(forKey: BotModel.userKey), "kaiku")
        XCTAssertNil(d.dictionaryRepresentation().values.first { ($0 as? String) == "x" }, "the password is never in UserDefaults")
    }

    func testHeardMessagesForAnotherHomeOrAudioAreDropped() {
        let m = model(defaults())
        m.configure(serviceURL: nil, home: "h")
        let tap = Data(#"{"type":"raw.head.tap","source":"head","payload":{"t_ms":1}}"#.utf8)
        m.heard("kaiku/v1/h/raw/head/tap", tap)
        m.heard("kaiku/v1/other/raw/head/tap", tap)
        m.heard("kaiku/v1/h/audio/head/mic", Data(repeating: 1, count: 640))
        XCTAssertEqual(m.state.messages, 1)
        XCTAssertEqual(m.home, "h")
        m.pause(true)
        m.heard("kaiku/v1/h/raw/head/tap", tap)
        XCTAssertEqual(m.newWhilePaused, 1); XCTAssertEqual(m.feed.first?.count, 1, "the paused list does not move")
        m.pause(false)
        XCTAssertEqual(m.feed.first?.count, 2)
    }
}

// MARK: the real client on a real broker

/// Runs the client against a throwaway mosquitto on a free port (skipped when mosquitto is not installed):
/// it subscribes, receives envelopes, never receives the audio topics or another home, acks QoS 1, comes back
/// after the broker restarts, and stops. Publishing is done with `mosquitto_pub`, never by the app's client.
@MainActor
final class BotBrokerTests: XCTestCase {
    static let bin = ["/opt/homebrew/sbin", "/usr/local/sbin", "/usr/sbin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
    func tool(_ name: String) -> String? { Self.bin.map { "\($0)/\(name)" }.first { FileManager.default.isExecutableFile(atPath: $0) } }

    func freePort() -> UInt16 {
        let fd = socket(AF_INET, SOCK_STREAM, 0); defer { close(fd) }
        var a = sockaddr_in(); a.sin_family = sa_family_t(AF_INET); a.sin_port = 0; a.sin_addr.s_addr = inet_addr("127.0.0.1")
        var len = socklen_t(MemoryLayout<sockaddr_in>.size)
        _ = withUnsafeMutablePointer(to: &a) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.bind(fd, $0, len) } }
        _ = withUnsafeMutablePointer(to: &a) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.getsockname(fd, $0, &len) } }
        return UInt16(bigEndian: a.sin_port)
    }

    func broker(_ exe: String, port: UInt16, dir: URL) throws -> Process {
        let conf = dir.appendingPathComponent("m.conf")
        try "listener \(port) 127.0.0.1\nallow_anonymous true\npersistence false\n".write(to: conf, atomically: true, encoding: .utf8)
        let p = Process(); p.executableURL = URL(fileURLWithPath: exe); p.arguments = ["-c", conf.path]
        p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
        try p.run()
        return p
    }

    func pub(_ exe: String, port: UInt16, _ topic: String, _ message: String? = nil, file: URL? = nil, qos: Int = 0, retain: Bool = false) throws {
        let p = Process(); p.executableURL = URL(fileURLWithPath: exe)
        var args = ["-h", "127.0.0.1", "-p", String(port), "-t", topic, "-q", String(qos)]
        if retain { args.append("-r") }
        if let file { args += ["-f", file.path] } else { args += ["-m", message ?? ""] }
        p.arguments = args
        try p.run(); p.waitUntilExit()
    }

    func wait(_ what: String, _ seconds: Double = 6, _ ok: @escaping () -> Bool) async {
        let end = Date().addingTimeInterval(seconds)
        while !ok(), Date() < end { try? await Task.sleep(nanoseconds: 50_000_000) }
        XCTAssertTrue(ok(), what)
    }

    func testTheClientListensReadOnlyAndNeverHearsTheAudioTopics() async throws {
        guard let mosq = tool("mosquitto"), let mpub = tool("mosquitto_pub") else { throw XCTSkip("mosquitto is not installed") }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("kaikubot-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let port = freePort()
        var b = try broker(mosq, port: port, dir: dir)
        defer { b.terminate(); b.waitUntilExit() }
        try await Task.sleep(nanoseconds: 400_000_000)

        // A retained heartbeat is there before the app connects (the robot's parts retain theirs).
        try pub(mpub, port: port, "kaiku/v1/h/health/head",
                #"{"v":1,"id":"a","ts":"2026-11-14T10:00:00.000Z","home_id":"h","source":"head","type":"health","payload":{"status":"ok","version":"0.3.0","uptime_s":4,"details":{"firmware":"standalone","audio":{"mic_open":false}}},"sim":true}"#, retain: true)
        var got: [String] = []
        var states: [BotLinkState] = []
        var timing = BotBusClient.Timing(); timing.backoff = [0.3]
        let c = BotBusClient(address: BotAddress(host: "127.0.0.1", port: port), home: "h", timing: timing,
                             onState: { states.append($0) }, onMessage: { t, _ in got.append(t) })
        c.start()
        await wait("subscribed") { c.state == .listening }
        await wait("the retained heartbeat") { got.contains("kaiku/v1/h/health/head") }

        let frame = dir.appendingPathComponent("frame.raw")
        try Data(repeating: 7, count: 640).write(to: frame)
        try pub(mpub, port: port, "kaiku/v1/h/audio/head/mic", file: frame)
        try pub(mpub, port: port, "kaiku/v1/h/audio/head/speaker", file: frame)
        try pub(mpub, port: port, "kaiku/v1/other/raw/head/tap", #"{"type":"raw.head.tap","source":"head","payload":{"t_ms":1}}"#)
        try pub(mpub, port: port, "kaiku/v1/h/log/hub", "x")
        try pub(mpub, port: port, "kaiku/v1/h/cmd/head", #"{"type":"cmd.head","source":"hub","payload":{"mic":"open"}}"#, qos: 1)
        try pub(mpub, port: port, "kaiku/v1/h/raw/head/ear", #"{"type":"raw.head.ear","source":"head","payload":{"value":3,"delta":1,"pressed":false}}"#)
        await wait("the envelopes") { got.contains("kaiku/v1/h/raw/head/ear") && got.contains("kaiku/v1/h/cmd/head") }
        try await Task.sleep(nanoseconds: 300_000_000)
        XCTAssertFalse(got.contains { $0.contains("/audio/") }, "an audio frame never reaches the app")
        XCTAssertFalse(got.contains { $0.contains("/other/") || $0.contains("/log/") })

        // The broker goes away and comes back: the client finds it again by itself.
        b.terminate(); b.waitUntilExit()
        await wait("noticed the broker went") { c.state == .unreachable }
        b = try broker(mosq, port: port, dir: dir)
        await wait("back", 10) { c.state == .listening }
        try pub(mpub, port: port, "kaiku/v1/h/obs/ritual", #"{"type":"obs.ritual","source":"hub","payload":{"step":"greet","status":"started"}}"#)
        await wait("after the restart") { got.contains("kaiku/v1/h/obs/ritual") }

        c.stop()
        XCTAssertEqual(c.state, .idle)
        let before = got.count
        try pub(mpub, port: port, "kaiku/v1/h/raw/head/ear", #"{"type":"raw.head.ear","source":"head","payload":{"value":4}}"#)
        try await Task.sleep(nanoseconds: 500_000_000)
        XCTAssertEqual(got.count, before, "stopped: nothing more")
        XCTAssertTrue(states.contains(.connecting) && states.contains(.listening))
    }

    func testNothingAtTheAddressIsUnreachableNotAnError() async throws {
        var states: [BotLinkState] = []
        var timing = BotBusClient.Timing(); timing.connectTimeout = 2; timing.backoff = [5]
        let c = BotBusClient(address: BotAddress(host: "127.0.0.1", port: freePort()), home: nil, timing: timing,
                             onState: { states.append($0) }, onMessage: { _, _ in })
        c.start()
        await wait("unreachable", 6) { c.state == .unreachable }
        c.stop()
        XCTAssertEqual(states.first, .connecting)
    }
}

// MARK: the real robot software (opt-in)

/// Listens to a broker the real hub and the software twins are running on, for a while, and prints what the
/// tab made of it: `KAIKU_BOT_TEST_BROKER=127.0.0.1:<port> [KAIKU_BOT_TEST_HOME=<home>] [KAIKU_BOT_TEST_SECONDS=60]
/// [KAIKU_BOT_TEST_RECORD=<file.jsonl>] swift test --filter BotRobotRunTests`. The recording (real envelopes as
/// heard) is what `-kaikuBotReplay` plays in for pictures.
@MainActor
final class BotRobotRunTests: XCTestCase {
    func testListenToTheRealRobotSoftware() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let raw = env["KAIKU_BOT_TEST_BROKER"], let address = BotAddress.parse(raw) else {
            throw XCTSkip("set KAIKU_BOT_TEST_BROKER to a broker the hub and the twins use")
        }
        let home = env["KAIKU_BOT_TEST_HOME"]
        let seconds = Double(env["KAIKU_BOT_TEST_SECONDS"] ?? "") ?? 60
        let record = env["KAIKU_BOT_TEST_RECORD"].map { URL(fileURLWithPath: $0) }
        var state = BotState()
        var byType: [String: Int] = [:]
        var lines: [String] = []
        var dropped = 0
        let start = Date()
        let c = BotBusClient(address: address, home: home, onState: { print("bot link: \($0)") }, onMessage: { topic, data in
            guard let e = BotEnvelope.decode(data) else { dropped += 1; return }
            byType[e.type, default: 0] += 1
            state.take(e, now: Date())
            if let l = BotRecording.line(t: Date().timeIntervalSince(start), topic: topic, payload: data) { lines.append(l) }
        })
        c.start()
        let end = Date().addingTimeInterval(seconds)
        while Date() < end { try await Task.sleep(nanoseconds: 200_000_000) }
        c.stop()
        if let record { try (lines.joined(separator: "\n") + "\n").write(to: record, atomically: true, encoding: .utf8) }
        let now = Date()
        print("bot run: \(state.messages) envelopes in \(Int(seconds)) s, \(dropped) not envelopes")
        for (t, n) in byType.sorted(by: { $0.key < $1.key }) { print("  \(t): \(n)") }
        print("parts: " + state.parts.map { "\($0.key)(\($0.value.version ?? "?")\($0.value.sim ? ", simulated" : ""))" }.sorted().joined(separator: ", "))
        print("now: step=\(state.step ?? "-") eyes=\(state.eyes ?? "-") chest=\(state.chest ?? "-") pan=\(state.panMode ?? "-") mic=\(String(describing: state.micOpen(now: now))) help=\(state.helpOn(now: now))")
        print("senses: ear=\(state.ear.map(String.init) ?? "-") taps=\(state.tapCount) tempo=\(state.tapTempo.map { String(Int($0)) } ?? "-") faceFrames=\(state.faceFrames) distance=\(state.distanceCm.map { String(Int($0)) } ?? "-") pulseSamples=\(state.pulseSamples) hr=\(state.hr.map { String(Int($0)) } ?? "-")")
        print("voice: said=\(state.said.count) heard=\(state.heard) tools=\(state.tools.map(\.name)) conversation=\(String(describing: state.conversationOpen)) level=\(state.level.map(String.init) ?? "-") song=\(state.songBpm.map { String(Int($0)) } ?? "-") band=\(state.band ?? "-")")
        print("records: \(state.records.count) · feed lines: \(state.feed.count) (from \(state.messages) messages)")
        for item in state.feed.prefix(25) { print("  \(BotTime.clock(item.at)) \(item.source) \(item.line)\(item.count > 1 ? " ×\(item.count)" : "")") }
        XCTAssertGreaterThan(state.messages, 0, "nothing came from the robot software")
        XCTAssertFalse(byType.keys.contains { $0.hasPrefix("audio") })
    }
}
