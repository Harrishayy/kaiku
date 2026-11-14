import CoreGraphics
import Foundation

/// Plain geometry on face landmark points (Vision's, in picture pixels). Pure: points in, ratios out. Every
/// measure is taken against the face's own lines (an eye's corners, the line through the two eyes), so tilting
/// the head does not change it, and is a ratio of two distances in the same picture, so the face's size and
/// distance from the camera do not either.
enum FaceGeometry {
    struct Axis {
        var origin: CGPoint
        /// Unit vector along the feature (corner to corner).
        var ux: Double, uy: Double
        var length: Double
    }

    /// The line through the two points of a contour that are farthest apart: an eye's or a mouth's corners.
    static func axis(_ points: [CGPoint]) -> Axis? {
        guard points.count >= 3, points.allSatisfy({ $0.x.isFinite && $0.y.isFinite }) else { return nil }
        var best = 0.0, a = points[0], b = points[0]
        for i in points.indices {
            for j in points.indices where j > i {
                let d = hypot(Double(points[j].x - points[i].x), Double(points[j].y - points[i].y))
                if d > best { best = d; a = points[i]; b = points[j] }
            }
        }
        guard best > 0 else { return nil }
        return Axis(origin: a, ux: Double(b.x - a.x) / best, uy: Double(b.y - a.y) / best, length: best)
    }

    /// The line from one point to another (the line through the two eyes: the face's own "level").
    static func line(from a: CGPoint?, to b: CGPoint?) -> Axis? {
        guard let a, let b, let length = distance(a, b), length > 0 else { return nil }
        return Axis(origin: a, ux: Double(b.x - a.x) / length, uy: Double(b.y - a.y) / length, length: length)
    }

    /// How far a contour reaches across an axis (its height when the axis is its width).
    static func extent(of points: [CGPoint], across axis: Axis) -> Double {
        var low = Double.infinity, high = -Double.infinity
        for p in points {
            let side = Double(p.y - axis.origin.y) * axis.ux - Double(p.x - axis.origin.x) * axis.uy
            low = min(low, side); high = max(high, side)
        }
        return points.isEmpty ? 0 : high - low
    }

    /// How far a contour reaches along an axis (its width).
    static func extent(of points: [CGPoint], along axis: Axis) -> Double {
        var low = Double.infinity, high = -Double.infinity
        for p in points {
            let run = Double(p.x - axis.origin.x) * axis.ux + Double(p.y - axis.origin.y) * axis.uy
            low = min(low, run); high = max(high, run)
        }
        return points.isEmpty ? 0 : high - low
    }

    /// An eye's opening: its height over its width.
    static func eyeOpening(_ eye: [CGPoint]) -> Double? {
        guard let axis = axis(eye) else { return nil }
        return extent(of: eye, across: axis) / axis.length
    }

    /// The mouth's width: how far the outer lips reach along the line of the eyes.
    static func mouthWidth(outer: [CGPoint], eyeLine: Axis) -> Double? {
        guard outer.count >= 3, outer.allSatisfy({ $0.x.isFinite && $0.y.isFinite }) else { return nil }
        let width = extent(of: outer, along: eyeLine)
        return width > 0 ? width : nil
    }

    /// The gap between the lips: how tall the inner lip contour is, over the mouth's width. Both are measured
    /// against the line of the eyes, because a mouth has no dependable axis of its own: wide open it is taller
    /// than it is wide. Closed lips leave almost nothing, however thick the lips or wide the mouth.
    static func mouthOpening(inner: [CGPoint], outer: [CGPoint], eyeLine: Axis) -> Double? {
        guard let width = mouthWidth(outer: outer, eyeLine: eyeLine), inner.count >= 3,
              inner.allSatisfy({ $0.x.isFinite && $0.y.isFinite }) else { return nil }
        return extent(of: inner, across: eyeLine) / width
    }

    static func centre(_ points: [CGPoint]) -> CGPoint? {
        guard !points.isEmpty else { return nil }
        let x = points.map { Double($0.x) }.reduce(0, +) / Double(points.count), y = points.map { Double($0.y) }.reduce(0, +) / Double(points.count)
        return x.isFinite && y.isFinite ? CGPoint(x: x, y: y) : nil
    }

    static func distance(_ a: CGPoint?, _ b: CGPoint?) -> Double? {
        guard let a, let b else { return nil }
        let d = hypot(Double(b.x - a.x), Double(b.y - a.y))
        return d.isFinite ? d : nil
    }
}
