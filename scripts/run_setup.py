"""Generate infographics for one setup and one model.

    python scripts/run_setup.py --setup s1_zero_shot --model configs/models/qwen3_5_9b.yaml

Outputs go to runs/<prompt set>/<setup>__<model>__<prompt set>/. Rerunning the same command continues an
interrupted run. Changing the settings needs a new --run-name, so results are never mixed.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from infographics.backends.factory import (  # noqa: E402
    load_model_config,
    make_backend,
    temperature_for,
)
from infographics.harness.prompts import load_prompts  # noqa: E402
from infographics.harness.renderer import Renderer  # noqa: E402
from infographics.harness.run_logger import RunLogger  # noqa: E402
from infographics.harness.runner import run_setup  # noqa: E402
from infographics.setups.builders import POSTPROCESSORS, SETUPS, SYSTEM_PROMPT_PATH  # noqa: E402

# The plan's decoding protocol. A model config can set `temperature: null` for models that only
# accept their default; the temperature actually used is what gets logged.
TEMPERATURE = 0.2
SAMPLES = 1  # the plan says 3; cut to 1 for the first round. Pass --samples 3 for the plan's protocol.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--setup", required=True, choices=sorted(SETUPS))
    parser.add_argument("--model", required=True, type=Path, help="a file in configs/models/")
    parser.add_argument("--prompts", type=Path, default=ROOT / "data" / "prompts" / "dev_set.jsonl")
    parser.add_argument("--samples", type=int, default=SAMPLES)
    parser.add_argument("--limit", type=int, help="only the first N prompts, for a quick test")
    parser.add_argument("--run-name", help="defaults to <setup>__<model>__<prompt set>")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    model_config = load_model_config(args.model)
    temperature = temperature_for(model_config, TEMPERATURE)
    prompts = load_prompts(args.prompts)[: args.limit]
    build_messages = SETUPS[args.setup]
    build_messages(prompts[0])  # fail now, not mid-run, if inputs such as reference images are missing

    run_name = args.run_name or f"{args.setup}__{model_config['name']}__{args.prompts.stem}"
    if args.limit:
        run_name += f"__first{args.limit}"
    system_prompt = SYSTEM_PROMPT_PATH.read_bytes()
    logger = RunLogger(
        ROOT / "runs" / args.prompts.stem / run_name,
        {
            "setup": args.setup,
            "model": model_config["name"],
            "checkpoint": model_config["checkpoint"],
            "quantization": model_config["quantization"],
            "temperature": temperature,  # None = the provider's default
            "samples": args.samples,
            "model_config": model_config,
            "system_prompt_sha256": hashlib.sha256(system_prompt).hexdigest(),
            "prompts_file": args.prompts.name,
        },
    )

    backend = make_backend(model_config)
    print(f"{run_name}: {len(prompts)} prompts x {args.samples} samples")
    with Renderer() as renderer:
        summary = run_setup(
            prompts, build_messages, backend, renderer, logger, args.samples, temperature,
            postprocess=POSTPROCESSORS.get(args.setup),
        )
    print(
        f"\nDone: {summary.logged} new, {summary.skipped} already done, "
        f"{summary.rendered_ok}/{summary.logged} new rendered OK, {summary.errors} failed calls."
    )
    print(f"Outputs: {logger.run_dir}")
    if summary.errors:
        print("Rerun the same command to retry the failed calls.")
        sys.exit(1)


if __name__ == "__main__":
    main()
