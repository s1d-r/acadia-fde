"""Record the README GIFs, headless.

    python scripts/record_gifs.py

Drives the real UI in a headless Chromium with Playwright, takes a screenshot
several times a second, and assembles the frames into a GIF with Pillow.

Two decisions worth knowing about:

* **Every question is asked twice.** The first pass is thrown away. It warms the
  model, so the recorded pass does not spend ten seconds showing a spinner while
  weights load. This is what the brief means by recording after the answers have
  been produced.
* **Identical frames are collapsed.** A GIF of a page that is not changing is
  just a large file. Runs of identical frames are reduced to a couple, which
  keeps each GIF a few hundred kilobytes instead of several megabytes.

ffmpeg is not needed. Pillow writes the GIF directly.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "docs" / "gifs"

BASE_URL = "http://127.0.0.1:8000"

VIEWPORT = {"width": 1100, "height": 900}

#: Frames per second in the finished GIF. Low enough to keep the file small,
#: high enough that typing does not look like a slideshow.
FPS = 5
FRAME_MS = int(1000 / FPS)

#: How many identical frames to keep in a row. Two reads as a deliberate pause;
#: thirty reads as a stalled recording and costs thirty frames.
MAX_REPEATED_FRAMES = 2


class Recorder:
    """Collects screenshots and writes them out as a GIF."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.frames: list[Image.Image] = []

    def capture(self) -> None:
        raw = self.page.screenshot(type="png")
        self.frames.append(Image.open(io.BytesIO(raw)).convert("RGB"))

    def hold(self, seconds: float) -> None:
        """Keep recording while nothing is being driven."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.capture()
            time.sleep(1 / FPS)

    def save(self, path: Path) -> None:
        frames = _collapse_repeats(self.frames)
        if not frames:
            raise RuntimeError("nothing was recorded")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Palette conversion per frame, so colours stay stable across the GIF.
        converted = [frame.convert("P", palette=Image.ADAPTIVE, colors=128) for frame in frames]
        converted[0].save(
            path,
            save_all=True,
            append_images=converted[1:],
            duration=FRAME_MS,
            loop=0,
            optimize=True,
        )
        size_kb = path.stat().st_size / 1024
        print(f"  wrote {path.relative_to(REPOSITORY_ROOT)}  "
              f"{len(converted)} frames, {size_kb:.0f} KB")


def _collapse_repeats(frames: list[Image.Image]) -> list[Image.Image]:
    """Drop long runs of frames where nothing moved."""
    kept: list[Image.Image] = []
    repeats = 0
    for frame in frames:
        if kept and frame.tobytes() == kept[-1].tobytes():
            repeats += 1
            if repeats >= MAX_REPEATED_FRAMES:
                continue
        else:
            repeats = 0
        kept.append(frame)
    return kept


def wait_for_datasets(page: Page, timeout: int = 30_000) -> None:
    """Wait until the dataset list has been populated.

    Not wait_for_selector on an option: an option inside a closed select is not
    a visible element as far as the browser is concerned, so that call waits
    forever on a list that is perfectly well populated.
    """
    page.wait_for_function(
        "() => document.getElementById('dataset').options.length > 0",
        timeout=timeout,
    )


def type_question(recorder: Recorder, question: str) -> None:
    """Type into the box one character at a time, recording as it goes."""
    box = recorder.page.locator("#question")
    box.fill("")
    for index in range(1, len(question) + 1):
        box.fill(question[:index])
        if index % 3 == 0:
            recorder.capture()
    recorder.capture()


def wait_for_answer(recorder: Recorder, timeout: float = 120.0) -> None:
    """Record until the answer panel appears."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        recorder.capture()
        visible = recorder.page.locator("#answer").is_visible()
        failed = recorder.page.locator("#ask-status.bad").count() > 0
        if visible or failed:
            return
        time.sleep(1 / FPS)
    raise TimeoutError("no answer appeared")


def ask(recorder: Recorder, question: str) -> None:
    type_question(recorder, question)
    recorder.page.click("#ask")
    wait_for_answer(recorder)
    # The SQL sits below the fold on a 900 pixel viewport, and showing the SQL
    # beside the answer is the whole point of the demo. Scroll to it.
    recorder.hold(1.0)
    recorder.page.locator("#answer").scroll_into_view_if_needed()
    recorder.hold(0.4)
    recorder.page.mouse.wheel(0, 320)
    recorder.hold(0.4)


def warm_up(page: Page, question: str) -> None:
    """Ask once without recording, so the recorded pass is not a loading screen."""
    page.fill("#question", question)
    page.click("#ask")
    page.wait_for_selector("#answer:visible", timeout=180_000)
    page.reload()
    wait_for_datasets(page)


def record_ask(page: Page, question: str, output: Path) -> None:
    """GIF one: ask a question about a dataset that is already loaded."""
    print(f"Recording {output.name}")
    page.goto(BASE_URL)
    wait_for_datasets(page)

    warm_up(page, question)

    recorder = Recorder(page)
    recorder.hold(0.6)
    ask(recorder, question)
    recorder.hold(2.6)
    recorder.save(output)


def record_second_csv(page: Page, csv_path: Path, question: str, output: Path) -> None:
    """GIF two: a different CSV the app has never seen, uploaded and queried."""
    print(f"Recording {output.name}")
    page.goto(BASE_URL)
    page.wait_for_selector("#dataset", timeout=30_000)

    # Warm the model against this file first, then start again from a clean
    # page so the recording shows the upload from the beginning.
    page.set_input_files("#file", str(csv_path))
    page.click("#upload")
    page.wait_for_function(
        "() => document.getElementById('upload-status').textContent.startsWith('Loaded')",
        timeout=180_000,
    )
    warm_up(page, question)

    page.goto(BASE_URL)
    page.wait_for_selector("#dataset", timeout=30_000)

    recorder = Recorder(page)
    recorder.hold(0.6)
    recorder.page.set_input_files("#file", str(csv_path))
    recorder.hold(0.8)
    recorder.page.click("#upload")
    recorder.page.wait_for_function(
        "() => document.getElementById('upload-status').textContent.startsWith('Loaded')",
        timeout=180_000,
    )
    recorder.hold(1.2)
    ask(recorder, question)
    recorder.hold(2.6)
    recorder.save(output)


def record_refusal(page: Page, question: str, output: Path) -> None:
    """GIF three: the system refusing a question the data cannot answer."""
    print(f"Recording {output.name}")
    page.goto(BASE_URL)
    wait_for_datasets(page)

    warm_up(page, question)

    recorder = Recorder(page)
    recorder.hold(0.6)
    ask(recorder, question)
    recorder.hold(3.0)
    recorder.save(output)


DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--only", choices=["ask", "second-csv", "refusal"])
    args = parser.parse_args()

    global BASE_URL
    BASE_URL = args.base_url

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        try:
            if args.only in (None, "ask"):
                record_ask(
                    page,
                    "What are the top 10 products by revenue?",
                    OUTPUT_DIRECTORY / "ask-a-question.gif",
                )
            if args.only in (None, "refusal"):
                record_refusal(
                    page,
                    "Which supplier delivered the most late shipments?",
                    OUTPUT_DIRECTORY / "refusing-correctly.gif",
                )
            if args.only in (None, "second-csv"):
                record_second_csv(
                    page,
                    REPOSITORY_ROOT / "eval" / "data" / "bike_hire.csv",
                    "Which 3 stations brought in the most in fees?",
                    OUTPUT_DIRECTORY / "second-csv.gif",
                )
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
