// Tiny mouse driver for apps/apple/scripts/record_app_demo.sh (hover/click the Mac notch island on camera).
//   demo_mouse move X Y     glide the pointer to (X, Y) in screen points (top-left origin)
//   demo_mouse click X Y    glide there and click
// Posting events needs Accessibility permission for the terminal (the same one AppleScript UI scripting uses).
import CoreGraphics
import Foundation

let args = CommandLine.arguments
guard args.count == 4, let x = Double(args[2]), let y = Double(args[3]) else {
    FileHandle.standardError.write("usage: demo_mouse move|click X Y\n".data(using: .utf8)!)
    exit(2)
}
let target = CGPoint(x: x, y: y)
let start = CGEvent(source: nil)?.location ?? target
let steps = 30
for i in 1...steps {   // ease-out glide so the pointer is easy to follow on video
    let t = Double(i) / Double(steps), e = 1 - pow(1 - t, 3)
    let p = CGPoint(x: start.x + (target.x - start.x) * e, y: start.y + (target.y - start.y) * e)
    CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: p, mouseButton: .left)?.post(tap: .cghidEventTap)
    usleep(16_000)
}
if args[1] == "click" {
    usleep(150_000)
    CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: target, mouseButton: .left)?.post(tap: .cghidEventTap)
    usleep(80_000)
    CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: target, mouseButton: .left)?.post(tap: .cghidEventTap)
}
