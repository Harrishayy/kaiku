import Foundation

/// The plain words for what the robot's parts said on the bus. Every visible string is a copy key
/// (copy.apple.json → `bot.*`). Machine words from the bus (an eye name, a tool name) are turned into words here;
/// one this build does not know is shown as it came, never dropped. Nothing here says how the person is.
enum BotWords {
    static func whole(_ v: Double) -> String { String(Int(v.rounded())) }
    static func one(_ v: Double) -> String {
        let f = NumberFormatter()
        f.locale = Locale(identifier: L10n.shared.language.rawValue)
        f.minimumFractionDigits = 1; f.maximumFractionDigits = 1
        return f.string(from: NSNumber(value: v)) ?? String(format: "%.1f", v)
    }

    /// head / sensors / hub / friendlink as the person calls them.
    static func part(_ source: String) -> String {
        switch source {
        case "head", "sensors", "hub", "friendlink", "glasses", "laptop", "phone", "cloud", "sim":
            return T("bot.part.\(source)")
        default: return source
        }
    }

    static func health(_ source: String, status: String?, version: String?) -> String {
        let name = part(source)
        switch status {
        case "down": return T("bot.feed.health.down", ["part": name])
        case "degraded": return T("bot.feed.health.degraded", ["part": name])
        default: return T("bot.feed.health.ok", ["part": name])
        }
    }

    static func step(_ s: String?) -> String {
        guard let s, !s.isEmpty else { return T("bot.step.unknown") }
        let known = ["idle", "greet", "dial", "mood", "energy", "sleep", "breathe", "drum", "phq9", "nudge", "close", "done"]
        return known.contains(s) ? T("bot.step.\(s)") : s
    }

    static func eyes(_ e: String) -> String {
        ["neutral", "happy", "sleepy", "wide", "listening", "thinking", "soft"].contains(e) ? T("bot.eyes.\(e)") : e
    }

    static func chest(_ c: String) -> String { ["off", "breathe", "glow", "pulse"].contains(c) ? T("bot.chest.\(c)") : c }

    static func panMode(_ m: String) -> String { ["track", "still", "sway"].contains(m) ? T("bot.pan.\(m)") : m }

    static func gesture(_ g: String) -> String {
        ["look_left", "look_right", "shake"].contains(g) ? T("bot.gesture.\(g)") : g
    }

    static func chime(_ c: String) -> String {
        ["wake", "ok", "start_drum", "end_drum", "alert"].contains(c) ? T("bot.chime.\(c)") : c
    }

    static func band(_ b: String?) -> String {
        guard let b else { return "" }
        return ["perfect", "great", "nice", "again"].contains(b) ? T("bot.band.\(b)") : b
    }

    static func ear(_ value: Int?, pressed: Bool) -> String {
        let n = value.map(String.init) ?? "–"
        return T(pressed ? "bot.feed.ear.press" : "bot.feed.ear", ["n": n])
    }

    static func taps(tempo: Double?) -> String {
        tempo.map { T("bot.feed.taps.tempo", ["n": whole($0)]) } ?? T("bot.feed.taps")
    }

    static func button(id: String?, pressed: Bool) -> String {
        let which = id == "head" ? T("bot.button.head") : T("bot.button.top")
        return T(pressed ? "bot.feed.button.down" : "bot.feed.button.up", ["button": which])
    }

    static func pan(_ deg: Double?, moving: Bool) -> String {
        T(moving ? "bot.feed.pan.moving" : "bot.feed.pan", ["n": deg.map(whole) ?? "–"])
    }

    static func distance(_ cm: Double?) -> String { T("bot.feed.distance", ["n": cm.map(whole) ?? "–"]) }
    static func light(_ lux: Double?) -> String { T("bot.feed.light", ["n": lux.map(whole) ?? "–"]) }

    /// Where the face is in the camera's picture, in words: left / centre / right, near / farther.
    static func face(_ f: BotState.Face?) -> String {
        guard let f else { return T("bot.feed.face.none") }
        let side = f.x < -0.25 ? T("bot.face.left") : f.x > 0.25 ? T("bot.face.right") : T("bot.face.centre")
        return T("bot.feed.face", ["side": side, "n": whole(f.size * 100)])
    }

    static func level(_ n: Int?, bpm: Double?) -> String {
        let l = n.map(String.init) ?? "–"
        return bpm.map { T("bot.feed.level.bpm", ["n": l, "bpm": whole($0)]) } ?? T("bot.feed.level", ["n": l])
    }

    static func music(_ detail: String?, bpm: Double?) -> String {
        switch detail {
        case "start": return T("bot.feed.music.start")
        case "song": return bpm.map { T("bot.feed.music.song.bpm", ["bpm": whole($0)]) } ?? T("bot.feed.music.song")
        case "hush": return T("bot.feed.music.hush")
        case "stop": return T("bot.feed.music.stop")
        default: return T("bot.feed.music.other")
        }
    }

    /// How a line was spoken, or who answered a tool call (`raw.hub.trace.by`).
    static func by(_ b: String?) -> String? {
        guard let b else { return nil }
        let known = ["script", "live", "cached_voice", "notebook", "gemma", "flash", "argon", "rule"]
        return known.contains(b) ? T("bot.by.\(b)") : b
    }

    /// "Asked its mind (ask_mind)". The tool's name is shown, never what it was asked or what came back.
    static func toolName(_ name: String) -> String {
        let known = ["feel", "recall", "remember", "forget", "ask_mind", "record_dial", "end_session", "suggest_nudge",
                     "express", "start_activity", "agree_activity", "start_phq9", "set_walk_goal", "log_walk_moment",
                     "look_at_this", "send_friend_ping", "suggest_activity"]
        let plain = known.contains(name) ? T("bot.tool.\(name)") : T("bot.tool.other")
        return name.isEmpty ? plain : T("bot.tool.named", ["what": plain, "tool": name])
    }

    static func seconds(_ ms: Int) -> String { ms < 1000 ? T("bot.ms", ["n": String(ms)]) : T("bot.s", ["n": one(Double(ms) / 1000)]) }

    static func tool(_ t: BotState.Tool) -> String {
        var out = toolName(t.name)
        if t.ok == false {
            out += " · " + (t.ms.map { T("bot.tool.failed.in", ["time": seconds($0)]) } ?? T("bot.tool.failed"))
        } else if let who = by(t.by) {
            out += " · " + (t.ms.map { T("bot.tool.by.in", ["who": who, "time": seconds($0)]) } ?? T("bot.tool.by", ["who": who]))
        } else if let ms = t.ms {
            out += " · " + T("bot.tool.in", ["time": seconds(ms)])
        }
        return out
    }

    /// One line for an observation the hub sends on to the person's record. Numbers she made (a dial, a tempo,
    /// taps) are fine; a word about how she is never. A safety flag is named and nothing more.
    static func record(_ e: BotEnvelope) -> String {
        let p = e.payload
        switch e.type {
        case "obs.ritual":
            let status = p["status"]?.string ?? ""
            let s = step(p["step"]?.string)
            return ["started", "completed", "skipped", "aborted"].contains(status)
                ? T("bot.rec.ritual.\(status)", ["step": s]) : T("bot.rec.ritual", ["step": s])
        case "obs.self_report":
            let item = p["item"]?.string ?? ""
            let name = ["mood", "energy", "sleep"].contains(item) ? T("bot.dial.\(item)") : item
            return T("bot.rec.dial", ["item": name, "n": p["value"]?.int.map(String.init) ?? "–"])
        case "obs.drum_session":
            return T("bot.rec.drum", ["n": p["taps"]?.int.map(String.init) ?? "–", "bpm": p["tempo_bpm"]?.double.map(whole) ?? "–"])
        case "obs.tap_back":
            return T("bot.rec.tapback", ["n": p["levels_played"]?.int.map(String.init) ?? "–", "taps": p["taps"]?.int.map(String.init) ?? "–"])
        case "obs.hrv_session":
            return T("bot.rec.hrv", ["bpm": p["hr_bpm"]?.double.map(whole) ?? "–"])
        case "obs.presence":
            return T(p["first_of_day"]?.bool == true ? "bot.rec.presence.first" : "bot.rec.presence")
        case "obs.engagement": return T("bot.rec.engagement")
        case "obs.intervention_response": return T("bot.rec.intervention")
        case "obs.speech_features": return T("bot.rec.speech")
        case "obs.light_level": return T("bot.rec.light")
        case "obs.nudge_offered": return T("bot.rec.nudge")
        case "obs.nudge_outcome": return T("bot.rec.nudge.answer")
        case "obs.friend_link": return T("bot.rec.friend")
        case "obs.phq9": return T("bot.rec.phq9")
        case "obs.safety_flag": return T("bot.rec.safety")
        default:
            let name = e.type.hasPrefix("obs.") ? String(e.type.dropFirst(4)).replacingOccurrences(of: "_", with: " ") : e.type
            return T("bot.rec.other", ["name": name])
        }
    }

    /// A message this build does not know: who sent it, and that it came.
    static func unknown(_ type: String, _ source: String) -> String { T("bot.feed.other", ["part": part(source)]) }
}
