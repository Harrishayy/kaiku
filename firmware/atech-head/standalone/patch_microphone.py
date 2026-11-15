"""Add numeric raw-slot diagnostics to the fetched Atech microphone driver."""

from pathlib import Path


def patch(source: str) -> str:
    declaration = "// Static trampoline for FreeRTOS task"
    capture = "        int totalSamples = bytesRead / sizeof(int32_t);"
    if source.count(declaration) != 1 or source.count(capture) != 1:
        raise ValueError("Atech microphone driver changed; review raw-slot diagnostics")
    source = source.replace(declaration, """// Numeric diagnostics only: no audio samples are stored or printed.
static volatile uint32_t kaikuMicBlocks = 0;
static volatile uint32_t kaikuMicRawPeak[2] = {0, 0};
void kaiku_microphone_stats(uint32_t* blocks, uint32_t* even, uint32_t* odd) {
    *blocks = kaikuMicBlocks;
    *even = kaikuMicRawPeak[0];
    *odd = kaikuMicRawPeak[1];
}

""" + declaration)
    return source.replace(capture, """        for (size_t j = 0; j < bytesRead / sizeof(int32_t); ++j) {
            int64_t value = rawBuffer[j];
            uint32_t magnitude = (uint32_t)(value < 0 ? -value : value);
            if (magnitude > kaikuMicRawPeak[j & 1]) kaikuMicRawPeak[j & 1] = magnitude;
        }
        ++kaikuMicBlocks;
""" + capture)


if __name__ == "__main__":
    path = Path(__file__).parent / "build/lib/atech_microphone/microphone.cpp"
    path.write_text(patch(path.read_text()))
