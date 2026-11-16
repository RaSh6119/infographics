"""Check that this machine can run the experiments, before starting a long run.

    python scripts/check_env.py                                    # harness only
    python scripts/check_env.py --server http://localhost:8000/v1  # also check a running vLLM server

Each check prints PASS, WARN or FAIL. The script exits with an error if anything failed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

results: list[str] = []


def report(status: str, name: str, detail: str = "") -> None:
    results.append(status)
    print(f"{status:4}  {name}" + (f": {detail}" if detail else ""))


def check(name: str, function) -> None:
    try:
        status, detail = function()
    except Exception as error:  # noqa: BLE001
        status, detail = "FAIL", f"{type(error).__name__}: {error}"
    report(status, name, detail)


def python_version():
    ok = sys.version_info >= (3, 11)
    return ("PASS" if ok else "FAIL"), sys.version.split()[0]


def gpu():
    import torch

    if not torch.cuda.is_available():
        return "WARN", "no CUDA GPU visible to torch (OCR will run on CPU, slowly)"
    names = [
        f"{torch.cuda.get_device_name(i)} "
        f"({torch.cuda.get_device_properties(i).total_memory / 2**30:.0f} GB)"
        for i in range(torch.cuda.device_count())
    ]
    return "PASS", f"torch {torch.__version__}, " + ", ".join(names)


TEST_PAGE = """<body style="margin:0;padding:40px;font-family:Poppins,Inter,Arial,sans-serif">
<h1 style="font-size:56px;color:#08344c">HIV Prevention Strategies</h1>
<p style="font-size:30px">Condom Use</p></body>"""


def render_and_ocr():
    from infographics.harness.renderer import Renderer
    from infographics.metrics.ocr_text import OcrReader, score_image

    with tempfile.TemporaryDirectory() as folder:
        png = Path(folder) / "check.png"
        with Renderer() as renderer:
            result = renderer.render(TEST_PAGE, png)
        if not result.ok:
            return "FAIL", f"render failed: {result.failures}"
        score, _ = score_image(png, ["HIV Prevention Strategies", "Condom Use"], OcrReader())
    if score.phrase_recall < 1:
        return "FAIL", f"OCR missed {score.missing}"
    return "PASS", "Chromium renders and EasyOCR reads the text back"


def fonts():
    wanted = ["Poppins", "Inter"]
    if shutil.which("fc-list"):
        installed = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True).stdout
    else:
        folders = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
                   Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts"]
        installed = " ".join(p.name for f in folders if f.exists() for p in f.iterdir())
    missing = [font for font in wanted if font.lower() not in installed.lower()]
    if missing:
        return "WARN", f"{missing} not installed; pages will fall back to Arial (see the runbook)"
    return "PASS", "Poppins and Inter installed"


def reference_images():
    from infographics.setups.builders import FEW_SHOT_DIR, FEW_SHOT_IMAGES

    missing = [name for name in FEW_SHOT_IMAGES if not (FEW_SHOT_DIR / name).exists()]
    if missing:
        return "WARN", f"missing {missing}; setup 1 still works, setup 2 needs them"
    return "PASS", "setup 2's three reference pages are present"


def prompts():
    from infographics.harness.prompts import load_prompts

    loaded = load_prompts(ROOT / "data" / "prompts" / "dev_set.jsonl")
    return "PASS", f"{len(loaded)} dev prompts"


def api_keys():
    from dotenv import dotenv_values

    values = dotenv_values(ROOT / ".env") if (ROOT / ".env").exists() else {}
    keys = ["GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HF_TOKEN"]
    present = [key for key in keys if values.get(key) or os.environ.get(key)]
    absent = [key for key in keys if key not in present]
    detail = f"set: {present or 'none'}; not set: {absent or 'none'}"
    return ("PASS" if not absent else "WARN"), detail + " (only needed for those models)"


def server(base_url: str):
    def check_server():
        with urllib.request.urlopen(base_url.rstrip("/") + "/models", timeout=10) as response:
            models = [m["id"] for m in json.load(response)["data"]]
        return "PASS", f"serving {models}"

    return check_server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--server", help="a vLLM base URL to test, e.g. http://localhost:8000/v1")
    args = parser.parse_args()

    check("Python 3.11+", python_version)
    check("GPU", gpu)
    check("Render and OCR", render_and_ocr)
    check("Fonts", fonts)
    check("Dev prompts", prompts)
    check("Setup 2 reference images", reference_images)
    check("API keys in .env", api_keys)
    if args.server:
        check(f"vLLM server at {args.server}", server(args.server))

    failed = results.count("FAIL")
    print(f"\n{failed} failed, {results.count('WARN')} warnings")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
