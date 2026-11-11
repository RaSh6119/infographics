# Infographic Generation Experiment

Compares six ways of generating infographics across local and frontier models, scored by the same
five automated metrics. The full design is in [docs/](docs/).

## Layout

```
configs/            Run configs. Pin model checkpoints and quantization here.
  models/ setups/ metrics/
data/
  prompts/          Dev prompts, plus previous students' prompts kept for the record
  ground_truth/     Reference infographics used as a style guide (not tracked)
  images_test/      Pilot images sent for clinician review (not tracked)
  few_shot/         The 3 fixed examples for setup 2
  checklists/       Yes/no questions per prompt, for metric 5
  icons/            Health Icons and the retrieval index (not tracked)
  training/         Synthetic prompts, SFT data and DPO pairs for setup 6 (not tracked)
  human_ratings/    Clinician ratings and comments (not tracked)
src/infographics/
  harness/          Prompt loader, Playwright renderer, run logging
  backends/         Local LLMs, local image models, frontier APIs
  rag/              Icon embedding, retrieval and SVG inlining
  metrics/          The 5 metrics
  setups/           s1_zero_shot, s2_few_shot, s3_rag_icons, s4_direct_image, s5_hybrid, s6_rl_finetune
scripts/            Entry points for running and scoring
models/             Downloaded weights (not tracked)
runs/               Output, render and logs for each run (not tracked)
results/            Aggregated tables and figures
notebooks/          Analysis
tests/              Harness and metric tests
third_party/        Design2Code evaluation code (not tracked)
```

## Setup

Python 3.11+. Run from the repo root.

**Laptop (Windows, RTX 4050, CUDA 12.4 driver)**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
playwright install chromium
```

**Server (Linux, 2×H100)**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt    # brings in vLLM and a matching CUDA build of torch
playwright install --with-deps chromium
```

**Both: Design2Code (metric 3)**

```bash
git clone https://github.com/NoviScl/Design2Code.git third_party/Design2Code
git -C third_party/Design2Code checkout 7a575e4c33f417c4be5c64072b8f5798de0d0f99
pip install --no-deps -e third_party/Design2Code
```

Use `--no-deps` because its own requirements pin old versions (torch 2.2, numpy 1.26) that conflict
with this stack.

**Secrets:** copy `.env.example` to `.env` and fill in the keys.

## Known issues

- `colormath` 3.0.0 calls `numpy.asscalar`, which numpy 2 removed, so `delta_e_cie2000` raises
  `AttributeError`. Design2Code's color score uses it. Fix this when building metric 3: either restore
  the function before importing, or swap in `skimage.color.deltaE_ciede2000`, which works here.
- `requirements-lock-windows.txt` records the laptop environment. Its `+cu124` torch builds need
  `--extra-index-url https://download.pytorch.org/whl/cu124`.

## Data rules

- Frontier APIs only ever see the de-identified test prompts.
- Patient data does not go on the server until the compliance controls in the plan are in place,
  and it never goes in this repo.
