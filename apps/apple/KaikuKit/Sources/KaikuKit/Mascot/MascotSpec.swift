import Foundation
import SwiftUI

/// Decoded `design/mascot.spec.json` (bundled copy). Geometry, poses, tracks, blink modes and interactions all
/// come from the file; nothing about Kaiku's shape is written in Swift.
public struct MascotSpec: Sendable {
    public struct Shape: Sendable {
        public enum Kind: Sendable { case ellipse(CGRect), path(Path) }
        public let kind: Kind
        public let fill: String?        // token name, "glow", or nil for none
        public let stroke: String?
        public let strokeWidth: CGFloat
        public let lineCap: CGLineCap
        public let lineJoin: CGLineJoin
        public let opacity: Double
        public let radial: Bool
    }

    public final class Part: @unchecked Sendable {
        public let id: String
        public let pivot: CGPoint
        public let shapes: [Shape]
        public let children: [Part]
        public let defaultOpacity: Double
        public let clip: String?
        init(id: String, pivot: CGPoint, shapes: [Shape], children: [Part], defaultOpacity: Double, clip: String?) {
            self.id = id; self.pivot = pivot; self.shapes = shapes; self.children = children
            self.defaultOpacity = defaultOpacity; self.clip = clip
        }
    }

    public enum Prop: String, Sendable { case translate, rotate, scale, opacity }

    /// A value: a scalar (rotate, opacity) or a pair (translate, scale).
    public enum Value: Sendable, Equatable {
        case scalar(Double), pair(Double, Double)
        var a: Double { if case .scalar(let v) = self { return v }; if case .pair(let x, _) = self { return x }; return 0 }
        var b: Double { if case .pair(_, let y) = self { return y }; return a }
        static func lerp(_ x: Value, _ y: Value, _ t: Double) -> Value {
            switch (x, y) {
            case (.scalar(let p), .scalar(let q)): return .scalar(p + (q - p) * t)
            default: return .pair(x.a + (y.a - x.a) * t, x.b + (y.b - x.b) * t)
            }
        }
    }

    public struct Track: Sendable {
        public let part: String
        public let prop: Prop
        public let easing: String
        public let keys: [(Double, Value?)]   // nil value = "pose" (blink keys)
    }

    public struct Event: Sendable {
        public let interval: ClosedRange<Double>   // seconds
        public let duration: Double
        public let tracks: [Track]
    }

    public struct State: Sendable {
        public let name: String
        public let duration: Double   // seconds
        public let loop: Bool
        public let blink: String
        public let pose: [String: [Prop: Value]]
        public let tracks: [Track]
        public let events: [String: Event]
    }

    public struct BlinkMode: Sendable {
        public let duration: Double
        public let interval: ClosedRange<Double>
        public let doubleChance: Double
        public let doubleGap: Double
    }

    public let viewBox: CGRect
    public let root: Part
    public let clips: [String: CGRect]
    public let states: [String: State]
    public let blinkParts: [String]
    public let blinkClosed: Value
    public let blinkEasing: String
    public let blinkModes: [String: BlinkMode]
    public let tap: Track
    public let tapDuration: Double
    public let dialFrom: ClosedRange<Double>
    public let dialTo: ClosedRange<Double>
    public let lookMax: CGSize
    public let ambient: [String: String]

    public static let shared: MascotSpec = {
        let url = Bundle.module.url(forResource: "mascot.spec", withExtension: "json")!
        let data = try! Data(contentsOf: url)
        return try! MascotSpec(json: data)
    }()

    enum SpecError: Error { case bad(String) }

    public init(json data: Data) throws {
        let j = try JSONDecoder().decode(JSONValue.self, from: data)
        func pt(_ v: JSONValue?) -> CGPoint {
            if case .array(let a)? = v, a.count == 2 { return CGPoint(x: a[0].double ?? 0, y: a[1].double ?? 0) }
            return .zero
        }
        func val(_ v: JSONValue?) -> Value? {
            switch v {
            case .number(let n)?: return .scalar(n)
            case .array(let a)? where a.count == 2: return .pair(a[0].double ?? 0, a[1].double ?? 0)
            default: return nil
            }
        }
        func ellipse(_ o: JSONValue) -> CGRect {
            let cx = o["cx"]?.double ?? 0, cy = o["cy"]?.double ?? 0
            let rx = o["rx"]?.double ?? o["r"]?.double ?? 0, ry = o["ry"]?.double ?? o["r"]?.double ?? 0
            return CGRect(x: cx - rx, y: cy - ry, width: rx * 2, height: ry * 2)
        }
        func shape(_ o: JSONValue) -> Shape {
            let type = o["type"]?.string ?? "path"
            let kind: Shape.Kind = type == "path" ? .path(SVGPath.parse(o["d"]?.string ?? "")) : .ellipse(ellipse(o))
            let fill = o["fill"]?.string
            let cap: CGLineCap = o["stroke-linecap"]?.string == "round" ? .round : .butt
            let join: CGLineJoin = o["stroke-linejoin"]?.string == "round" ? .round : .miter
            return Shape(kind: kind, fill: fill == "none" ? nil : fill, stroke: o["stroke"]?.string,
                         strokeWidth: CGFloat(o["stroke-width"]?.double ?? 0), lineCap: cap, lineJoin: join,
                         opacity: o["opacity"]?.double ?? 1, radial: o["gradient"]?.string == "radial")
        }
        func part(_ o: JSONValue) -> Part {
            var shapes: [Shape] = []
            if case .array(let a)? = o["shapes"] { shapes = a.map(shape) }
            var kids: [Part] = []
            if case .array(let a)? = o["children"] { kids = a.map(part) }
            return Part(id: o["id"]?.string ?? "", pivot: pt(o["pivot"]), shapes: shapes, children: kids,
                        defaultOpacity: o["default"]?["opacity"]?.double ?? 1, clip: o["clip"]?.string)
        }
        func track(_ o: JSONValue) -> Track {
            var keys: [(Double, Value?)] = []
            if case .array(let a)? = o["keys"] {
                for k in a {
                    if case .array(let kv) = k, kv.count == 2 { keys.append((kv[0].double ?? 0, val(kv[1]))) }
                }
            }
            return Track(part: o["part"]?.string ?? "", prop: Prop(rawValue: o["prop"]?.string ?? "") ?? .opacity,
                         easing: o["easing"]?.string ?? "soft-in-out", keys: keys)
        }
        func tracks(_ v: JSONValue?) -> [Track] {
            if case .array(let a)? = v { return a.map(track) }
            return []
        }
        func range(_ v: JSONValue?) -> ClosedRange<Double> {
            if case .array(let a)? = v, a.count == 2 { return (a[0].double ?? 0) / 1000...(a[1].double ?? 0) / 1000 }
            return 0...0
        }

        if case .array(let vb)? = j["viewBox"], vb.count == 4 {
            viewBox = CGRect(x: vb[0].double ?? 0, y: vb[1].double ?? 0, width: vb[2].double ?? 200, height: vb[3].double ?? 200)
        } else { viewBox = CGRect(x: 0, y: 0, width: 200, height: 200) }

        guard case .array(let parts)? = j["parts"], let first = parts.first else { throw SpecError.bad("parts") }
        root = part(first)

        var clips: [String: CGRect] = [:]
        if case .object(let c)? = j["clips"] { for (k, v) in c { clips[k] = ellipse(v) } }
        self.clips = clips

        var states: [String: State] = [:]
        if case .object(let s)? = j["states"] {
            for (name, o) in s {
                var pose: [String: [Prop: Value]] = [:]
                if case .object(let p)? = o["pose"] {
                    for (partID, props) in p {
                        guard case .object(let pp) = props else { continue }
                        for (k, v) in pp { if let prop = Prop(rawValue: k), let vv = val(v) { pose[partID, default: [:]][prop] = vv } }
                    }
                }
                var events: [String: Event] = [:]
                if case .object(let ev)? = o["events"] {
                    for (en, e) in ev {
                        events[en] = Event(interval: range(e["interval"]), duration: (e["duration"]?.double ?? 0) / 1000,
                                           tracks: tracks(e["tracks"]))
                    }
                }
                states[name] = State(name: name, duration: (o["duration"]?.double ?? 1000) / 1000,
                                     loop: o["loop"]?.bool ?? true, blink: o["blink"]?.string ?? "normal",
                                     pose: pose, tracks: tracks(o["tracks"]), events: events)
            }
        }
        self.states = states

        let blink = j["blink"]
        if case .array(let bp)? = blink?["parts"] { blinkParts = bp.compactMap(\.string) } else { blinkParts = [] }
        blinkClosed = val(blink?["closed"]) ?? .pair(0, 28)
        blinkEasing = blink?["easing"]?.string ?? "soft-in-out"
        var modes: [String: BlinkMode] = [:]
        if case .object(let m)? = blink?["modes"] {
            for (k, v) in m where v != .null {
                modes[k] = BlinkMode(duration: (v["duration"]?.double ?? 240) / 1000, interval: range(v["interval"]),
                                     doubleChance: v["double_chance"]?.double ?? 0,
                                     doubleGap: (v["double_gap"]?.double ?? 0) / 1000)
            }
        }
        blinkModes = modes

        let inter = j["interactions"]
        tap = track(inter?["tap"] ?? .null)
        tapDuration = (inter?["tap"]?["duration"]?.double ?? 620) / 1000
        func r(_ v: JSONValue?) -> ClosedRange<Double> {
            if case .array(let a)? = v, a.count == 2 { return (a[0].double ?? 0)...(a[1].double ?? 0) }
            return 0...1
        }
        dialFrom = r(inter?["dial"]?["map"]?["from"])
        dialTo = r(inter?["dial"]?["map"]?["to"])
        let lm = pt(inter?["look"]?["max"])
        lookMax = CGSize(width: lm.x, height: lm.y)

        var amb: [String: String] = [:]
        if case .object(let a)? = j["ambient_mood"] { for (k, v) in a { if let s = v.string { amb[k] = s } } }
        ambient = amb
    }

    /// Ear angle for a dial value (1..5 → −32..+32°).
    public func earAngle(forDial value: Double) -> Double {
        let t = (value - dialFrom.lowerBound) / (dialFrom.upperBound - dialFrom.lowerBound)
        return dialTo.lowerBound + (dialTo.upperBound - dialTo.lowerBound) * min(1, max(0, t))
    }
}

/// Cubic-bezier easings from tokens.json (`motion.easing`), evaluated on the CPU for Canvas tracks.
enum KaikuCurve {
    static let table: [String: (Double, Double, Double, Double)] = [
        "gentle-out": (0.32, 0.72, 0, 1), "soft-in-out": (0.45, 0, 0.25, 1),
        "overshoot": (0.34, 1.36, 0.64, 1), "settle": (0.22, 1, 0.36, 1), "linear": (0, 0, 1, 1),
    ]

    static func ease(_ name: String, _ x: Double) -> Double {
        guard let (x1, y1, x2, y2) = table[name] else { return x }
        if x <= 0 { return 0 }
        if x >= 1 { return 1 }
        // Solve bx(t) = x with Newton, fall back to bisection.
        func bx(_ t: Double) -> Double { 3 * (1 - t) * (1 - t) * t * x1 + 3 * (1 - t) * t * t * x2 + t * t * t }
        func by(_ t: Double) -> Double { 3 * (1 - t) * (1 - t) * t * y1 + 3 * (1 - t) * t * t * y2 + t * t * t }
        func dx(_ t: Double) -> Double { 3 * (1 - t) * (1 - t) * x1 + 6 * (1 - t) * t * (x2 - x1) + 3 * t * t * (1 - x2) }
        var t = x
        for _ in 0..<6 {
            let d = dx(t)
            if abs(d) < 1e-6 { break }
            t -= (bx(t) - x) / d
        }
        if t < 0 || t > 1 || abs(bx(t) - x) > 1e-4 {
            var lo = 0.0, hi = 1.0
            t = x
            for _ in 0..<30 { if bx(t) < x { lo = t } else { hi = t }; t = (lo + hi) / 2 }
        }
        return by(t)
    }
}

/// Absolute + relative M/L/H/V/C/Q/Z — everything mascot.spec.json uses.
enum SVGPath {
    static func parse(_ d: String) -> Path {
        var path = Path()
        var tokens: [String] = []
        var cur = ""
        for ch in d {
            if ch.isLetter {
                if !cur.isEmpty { tokens.append(cur); cur = "" }
                tokens.append(String(ch))
            } else if ch == " " || ch == "," || ch == "\n" {
                if !cur.isEmpty { tokens.append(cur); cur = "" }
            } else if ch == "-" && !cur.isEmpty && cur.last != "e" {
                tokens.append(cur); cur = "-"
            } else { cur.append(ch) }
        }
        if !cur.isEmpty { tokens.append(cur) }

        var i = 0
        var cmd: Character = "M"
        var p = CGPoint.zero
        var start = CGPoint.zero
        func num() -> CGFloat { defer { i += 1 }; return i < tokens.count ? CGFloat(Double(tokens[i]) ?? 0) : 0 }
        while i < tokens.count {
            if let c = tokens[i].first, c.isLetter { cmd = c; i += 1; if c == "Z" || c == "z" { path.closeSubpath(); p = start; continue } }
            let rel = cmd.isLowercase
            func abs(_ x: CGFloat, _ y: CGFloat) -> CGPoint { rel ? CGPoint(x: p.x + x, y: p.y + y) : CGPoint(x: x, y: y) }
            switch cmd {
            case "M", "m":
                p = abs(num(), num()); start = p; path.move(to: p)
                cmd = rel ? "l" : "L"
            case "L", "l": p = abs(num(), num()); path.addLine(to: p)
            case "H", "h": let x = num(); p = CGPoint(x: rel ? p.x + x : x, y: p.y); path.addLine(to: p)
            case "V", "v": let y = num(); p = CGPoint(x: p.x, y: rel ? p.y + y : y); path.addLine(to: p)
            case "C", "c":
                let c1 = abs(num(), num()), c2 = abs(num(), num()), e = abs(num(), num())
                path.addCurve(to: e, control1: c1, control2: c2); p = e
            case "Q", "q":
                let c1 = abs(num(), num()), e = abs(num(), num())
                path.addQuadCurve(to: e, control: c1); p = e
            default: i += 1
            }
        }
        return path
    }
}
