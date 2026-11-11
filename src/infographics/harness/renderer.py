"""Render one self-contained HTML page to a full-page PNG, and report whether it failed.

A render failure scores 0 in every metric, so this module decides what counts as one:

    timeout       the page did not finish within the deadline (for example an infinite loop)
    render_error  the browser or page crashed
    js_error      a script threw an uncaught error
    broken_asset  an image failed to load, or the page requested anything outside itself
    blank         nothing visible was drawn
    too_tall      the page is taller than Chromium can capture reliably

The page runs with no network access. Generated code cannot reach the internet, so a page
that depends on a CDN or web font fails here on every machine, instead of passing or failing
according to the network it happened to run on.

Warnings (console errors, content wider than 1080 px) are recorded but do not fail the page.

Usage:
    with Renderer() as renderer:
        result = renderer.render(html, "runs/example/render.png")
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image, ImageChops
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

PAGE_WIDTH = 1080
VIEWPORT_HEIGHT = 800
MAX_PAGE_HEIGHT = 16384  # Chromium's texture limit; captures beyond it are unreliable
DEFAULT_TIMEOUT_S = 30.0
SETTLE_MS = 250  # lets short timers and script-drawn content finish before the capture

# A pixel counts as drawn if it differs from the background by more than the tolerance
# (0-255). A page needs a few drawn pixels, so that compression noise does not count.
BLANK_TOLERANCE = 8
BLANK_MIN_DRAWN_PIXELS = 50

CLOSE_TIMEOUT_S = 5.0
MAX_DETAIL_CHARS = 300

# The page is served from this address so relative links arrive as requests that can be
# caught and reported. The .invalid domain is reserved and never resolves.
PAGE_URL = "http://infographic.invalid/"

INSPECT_PAGE_JS = """
async (settleMs) => {
  const images = [...document.images];
  for (const image of images) image.loading = "eager";
  await Promise.all(images.map((image) => image.complete ? null : new Promise((done) => {
    image.addEventListener("load", done, { once: true });
    image.addEventListener("error", done, { once: true });
  })));
  await document.fonts.ready;
  await new Promise((done) => setTimeout(done, settleMs));
  await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));

  const root = document.documentElement;
  const body = document.body;
  return {
    brokenImages: images
      .filter((image) => !image.complete || image.naturalWidth === 0)
      .map((image) => image.currentSrc || image.getAttribute("src") || "(no src)"),
    hasContent: Boolean(
      body && (body.innerText.trim() || body.querySelector("svg, img, canvas, video"))
    ),
    width: root.scrollWidth,
    height: root.scrollHeight,
  };
}
"""


@dataclass
class Failure:
    kind: str
    detail: str = ""


@dataclass
class RenderResult:
    png_path: str | None = None  # also set for a failed page if it could be captured
    width: int | None = None
    height: int | None = None
    elapsed_s: float = 0.0
    failures: list[Failure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict:
        return {"ok": self.ok, **asdict(self)}


def _shorten(text: str) -> str:
    return text if len(text) <= MAX_DETAIL_CHARS else text[:MAX_DETAIL_CHARS] + "..."


def _is_blank_image(png_path: Path) -> bool:
    with Image.open(png_path) as image:
        rgb = image.convert("RGB")
    _, background = max(rgb.getcolors(maxcolors=rgb.width * rgb.height))
    difference = ImageChops.difference(rgb, Image.new("RGB", rgb.size, background))
    histogram = difference.convert("L").histogram()
    return sum(histogram[BLANK_TOLERANCE + 1 :]) < BLANK_MIN_DRAWN_PIXELS


class Renderer:
    """Keeps one browser open across renders. Each page gets its own isolated context."""

    def __init__(self, timeout_s: float = DEFAULT_TIMEOUT_S):
        self.timeout_s = timeout_s
        self._loop: asyncio.AbstractEventLoop | None = None
        self._playwright = None
        self._browser = None

    def __enter__(self) -> "Renderer":
        self._loop = asyncio.new_event_loop()
        self._playwright = self._loop.run_until_complete(async_playwright().start())
        self._browser = self._loop.run_until_complete(self._playwright.chromium.launch())
        return self

    def __exit__(self, *exc_info) -> None:
        self._loop.run_until_complete(self._close_browser())
        self._loop.run_until_complete(self._playwright.stop())
        self._loop.close()

    def render(self, html: str, out_png: str | Path) -> RenderResult:
        return self._loop.run_until_complete(self._render(html, Path(out_png)))

    async def _render(self, html: str, out_png: Path) -> RenderResult:
        start = time.perf_counter()
        result = RenderResult()
        out_png.parent.mkdir(parents=True, exist_ok=True)
        out_png.unlink(missing_ok=True)  # a failed rerun must not leave an old image behind

        if not self._browser.is_connected():
            await self._restart_browser()
        context = await self._browser.new_context(
            viewport={"width": PAGE_WIDTH, "height": VIEWPORT_HEIGHT},
            device_scale_factor=1,
            color_scheme="light",
            reduced_motion="reduce",
            locale="en-US",
            timezone_id="UTC",
            service_workers="block",
            offline=True,
        )
        try:
            await asyncio.wait_for(self._capture(context, html, out_png, result), self.timeout_s)
        except asyncio.TimeoutError:
            result.failures.append(Failure("timeout", f"exceeded {self.timeout_s:g} s"))
        except PlaywrightError as error:
            result.failures.append(Failure("render_error", _shorten(str(error))))

        try:
            await asyncio.wait_for(context.close(), CLOSE_TIMEOUT_S)
        except (asyncio.TimeoutError, PlaywrightError):
            await self._restart_browser()  # a hung page can block closing its context

        result.elapsed_s = round(time.perf_counter() - start, 3)
        return result

    async def _capture(self, context, html: str, out_png: Path, result: RenderResult) -> None:
        async def handle_request(route) -> None:
            url = route.request.url
            if url == PAGE_URL:
                await route.fulfill(body=html, content_type="text/html; charset=utf-8")
            elif url.startswith(("data:", "blob:")):
                await route.continue_()
            else:
                result.failures.append(Failure("broken_asset", _shorten(url)))
                await route.abort()

        def handle_console(message) -> None:
            # Failed loads are already reported as broken assets.
            if message.type == "error" and not message.text.startswith("Failed to load resource"):
                result.warnings.append(f"console error: {_shorten(message.text)}")

        def handle_page_error(error) -> None:
            result.failures.append(Failure("js_error", _shorten(str(error))))

        await context.route("**/*", handle_request)
        page = await context.new_page()
        page.on("console", handle_console)
        page.on("pageerror", handle_page_error)

        await page.goto(PAGE_URL, wait_until="load")
        info = await page.evaluate(INSPECT_PAGE_JS, SETTLE_MS)

        for src in info["brokenImages"]:
            # Requests the route handler aborted have already been reported.
            detail = _shorten(src)
            if not any(f.kind == "broken_asset" and f.detail == detail for f in result.failures):
                result.failures.append(Failure("broken_asset", detail))
        result.width, result.height = info["width"], info["height"]
        if result.width > PAGE_WIDTH:
            result.warnings.append(f"content is {result.width} px wide, expected {PAGE_WIDTH}")
        if result.height > MAX_PAGE_HEIGHT:
            result.failures.append(
                Failure("too_tall", f"{result.height} px, limit {MAX_PAGE_HEIGHT}")
            )
            return

        await page.screenshot(path=str(out_png), full_page=True, animations="disabled")
        result.png_path = str(out_png)
        if not info["hasContent"]:
            result.failures.append(Failure("blank", "page has no text or graphics"))
        elif _is_blank_image(out_png):
            result.failures.append(Failure("blank", "nothing visible was drawn"))

    async def _close_browser(self) -> None:
        try:
            await asyncio.wait_for(self._browser.close(), CLOSE_TIMEOUT_S)
        except (asyncio.TimeoutError, PlaywrightError):
            pass

    async def _restart_browser(self) -> None:
        await self._close_browser()
        self._browser = await self._playwright.chromium.launch()
