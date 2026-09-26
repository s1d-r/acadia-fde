"""Render docs/architecture.png.

    python scripts/render_architecture.py

Drawn with Pillow rather than rendered from the Mermaid source next to it,
because Mermaid needs Node and this machine has no Node on it. The Mermaid file
is still the readable source of truth and GitHub renders it inline in the design
document. This script exists so the PNG can be regenerated rather than being a
binary nobody can change.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "architecture.png"

SCALE = 2  # drawn at 2x and downsampled, so the text is not ragged
WIDTH, HEIGHT = 1500, 1080

INK = (26, 26, 26)
MUTED = (110, 118, 130)
LINE = (203, 210, 220)
ACCENT = (43, 92, 217)
WARM = (176, 98, 30)
PANEL = (247, 248, 250)
WHITE = (255, 255, 255)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
BOLD_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for path in BOLD_CANDIDATES if bold else FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size * SCALE)
    return ImageFont.load_default()


class Canvas:
    def __init__(self) -> None:
        self.image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), WHITE)
        self.draw = ImageDraw.Draw(self.image)

    def box(self, x, y, w, h, *, title, lines=(), fill=WHITE, border=LINE, accent=None):
        s = SCALE
        self.draw.rounded_rectangle(
            [x * s, y * s, (x + w) * s, (y + h) * s],
            radius=9 * s, fill=fill, outline=border, width=2,
        )
        if accent:
            self.draw.rounded_rectangle(
                [x * s, y * s, (x + 5) * s, (y + h) * s], radius=3 * s, fill=accent
            )
        self.draw.text(
            ((x + 16) * s, (y + 12) * s), title, font=_font(15, bold=True), fill=INK
        )
        for index, line in enumerate(lines):
            self.draw.text(
                ((x + 16) * s, (y + 36 + index * 19) * s),
                line, font=_font(12), fill=MUTED,
            )

    def label(self, x, y, text, *, size=13, colour=MUTED, bold=False, anchor="la"):
        self.draw.text(
            (x * SCALE, y * SCALE), text, font=_font(size, bold=bold),
            fill=colour, anchor=anchor,
        )

    def arrow(self, x1, y1, x2, y2, *, colour=ACCENT, text=None, dashed=False):
        s = SCALE
        if dashed:
            self._dashed(x1, y1, x2, y2, colour)
        else:
            self.draw.line([x1 * s, y1 * s, x2 * s, y2 * s], fill=colour, width=2 * s // 1)
        # arrow head
        if x1 == x2:
            direction = 1 if y2 > y1 else -1
            self.draw.polygon(
                [(x2 * s, y2 * s), ((x2 - 5) * s, (y2 - 9 * direction) * s),
                 ((x2 + 5) * s, (y2 - 9 * direction) * s)], fill=colour)
        else:
            direction = 1 if x2 > x1 else -1
            self.draw.polygon(
                [(x2 * s, y2 * s), ((x2 - 9 * direction) * s, (y2 - 5) * s),
                 ((x2 - 9 * direction) * s, (y2 + 5) * s)], fill=colour)
        if text:
            midx, midy = (x1 + x2) / 2, (y1 + y2) / 2
            offset = 10 if x1 == x2 else -12
            self.label(midx + offset, midy - 8, text, size=11, colour=colour,
                       anchor="la" if x1 == x2 else "ma")

    def _dashed(self, x1, y1, x2, y2, colour, dash=7, gap=5):
        s = SCALE
        total = max(abs(x2 - x1), abs(y2 - y1))
        steps = int(total / (dash + gap)) or 1
        for i in range(steps):
            t0 = i * (dash + gap) / total
            t1 = min((i * (dash + gap) + dash) / total, 1.0)
            self.draw.line(
                [(x1 + (x2 - x1) * t0) * s, (y1 + (y2 - y1) * t0) * s,
                 (x1 + (x2 - x1) * t1) * s, (y1 + (y2 - y1) * t1) * s],
                fill=colour, width=2 * s,
            )

    def group(self, x, y, w, h, caption):
        s = SCALE
        self.draw.rounded_rectangle(
            [x * s, y * s, (x + w) * s, (y + h) * s],
            radius=12 * s, fill=PANEL, outline=LINE, width=1,
        )
        self.label(x + 16, y + 11, caption.upper(), size=11, colour=MUTED, bold=True)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.resize((WIDTH, HEIGHT), Image.LANCZOS).save(path)


def render() -> Path:
    c = Canvas()

    c.label(60, 34, "Natural language insights engine", size=22, colour=INK, bold=True)
    c.label(60, 66, "One CSV in, one question in plain English, one answer with the SQL that produced it.",
            size=13, colour=MUTED)

    # --- callers ---------------------------------------------------------
    c.group(60, 104, 830, 96, "callers")
    c.box(80, 132, 250, 54, title="Browser UI", lines=["one static page, no build step"])
    c.box(348, 132, 250, 54, title="HTTP client", lines=["curl, or anything else"])
    c.box(616, 132, 254, 54, title="Command line", lines=["insights ingest / ask"])

    # --- api -------------------------------------------------------------
    c.box(60, 242, 830, 86, fill=WHITE, accent=ACCENT,
          title="HTTP API  (FastAPI)",
          lines=["Input validation, status codes, one error shape, no stack traces.",
                 "No business logic: the CLI and the API call the same functions."])
    c.arrow(475, 200, 475, 238)

    # --- jobs ------------------------------------------------------------
    c.box(60, 372, 400, 96, accent=WARM,
          title="Job runner",
          lines=["Bounded pool of worker threads,", "inside this process."])
    c.box(490, 372, 400, 96, accent=WARM,
          title="Job store  (meta.jobs)",
          lines=["Queued, running, succeeded, failed.", "Jobs left running by a dead", "process are closed out at startup."])
    c.arrow(475, 328, 475, 368, text="  submit, get an id back")
    c.arrow(460, 420, 486, 420, colour=WARM)
    c.label(60, 482, "The caller polls GET /api/jobs/{id} until the job finishes. Nothing slow is done while a request is held open.",
            size=12, colour=MUTED)

    # --- engine ----------------------------------------------------------
    c.group(60, 516, 830, 400, "engine")

    c.box(80, 552, 380, 80, title="1. Ingestion",
          lines=["Loader: file to table, knows no meaning.", "Profiler: measures every column, concludes nothing."])
    c.box(80, 648, 380, 80, title="2. Schema context builder",
          lines=["Roles inferred from statistics, never from names.", "Caveats: no date column, no numbers, mostly empty."])
    c.box(80, 744, 380, 80, title="3. Planner",
          lines=["Question plus context in. SQL out,", "or a refusal with a reason."])
    c.box(80, 840, 380, 60, title="4. Validator",
          lines=["One SELECT, our table only, columns must exist."])
    c.box(490, 840, 380, 60, title="5. Executor",
          lines=["Row limit and timeout. Cancellable."])

    c.box(490, 552, 380, 80, title="Registry  (meta.datasets)",
          lines=["The measured profile of every dataset,", "stored as JSON, read whole by id."])
    c.box(490, 648, 380, 80, accent=ACCENT, title="LLM client  (protocol)",
          lines=["One method. Nothing above it has heard", "of Ollama. Swapping provider is one file."])
    c.box(490, 744, 380, 80, title="Refusal",
          lines=["A first class outcome, not an error.", "Travels to the caller with its reason."])

    c.arrow(270, 632, 270, 644)
    c.arrow(270, 728, 270, 740)
    c.arrow(270, 824, 270, 836)
    c.arrow(464, 870, 486, 870)
    c.arrow(460, 592, 486, 592, colour=MUTED)
    c.arrow(460, 688, 486, 688, colour=ACCENT)
    c.arrow(460, 784, 486, 784, colour=WARM)

    # --- model -----------------------------------------------------------
    c.box(940, 648, 500, 80, accent=ACCENT,
          title="Ollama, qwen2.5-coder:7b",
          lines=["Runs on the machine doing the demo. No API key,", "no network, no per question cost."])
    c.arrow(874, 688, 936, 688, colour=ACCENT, dashed=True)

    # --- storage ---------------------------------------------------------
    c.box(940, 372, 500, 96, title="DuckDB, one file",
          lines=["ds_<id>  one table per ingested CSV", "meta.datasets  profiles", "meta.jobs  job records"])
    c.arrow(894, 420, 936, 420, colour=MUTED)
    c.arrow(1190, 468, 1190, 640, colour=MUTED, dashed=True)

    c.label(940, 800, "What the caller gets back", size=13, colour=INK, bold=True)
    c.box(940, 824, 500, 96, title="Answer",
          lines=["The rows, the SQL that produced them, the model", "that wrote it, and how long each stage took.",
                 "Or a refusal naming what is missing."])

    c.label(60, 950, "Read the arrows top to bottom. A question enters at the API, becomes a job, and travels 2 to 5 before an answer comes back.",
            size=12, colour=MUTED)
    c.label(60, 976, "The validator is the only way to reach the executor: it returns a type the executor requires, so unchecked SQL cannot reach the database.",
            size=12, colour=MUTED)
    c.label(60, 1002, "Nothing in the engine knows any column name. Everything it knows about a file was measured from that file at ingest time.",
            size=12, colour=MUTED)

    c.save(OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    print(f"wrote {render()}")
