# Workstation runbook: Qwen3.5-9B on setups 1 and 2

Runs Qwen3.5-9B with vLLM on one H100, and the harness next to it on the same machine. Expect about
an hour to set up the first time, most of it downloading the model (about 20 GB).

## Bring on a USB stick

From the laptop, neither of which is in git:

- `data/few_shot/`: `statistical_14E.png`, `process_5E.png` and `comparison_10E.png`. Setup 1 works
  without them; setup 2 needs them.
- `data/prompts/clinic_set.jsonl`: the 5 prompts condensed from the clinic content. Copy it into
  `data/prompts/` and add `--prompts data/prompts/clinic_set.jsonl` to the run commands to use it.

Qwen needs no API key.

## 1. Check the machine

```bash
nvidia-smi           # H100s listed, and whether anyone else is using them
python3 --version    # 3.11 to 3.14
df -h ~              # about 40 GB free for the model and environments
```

Use `tmux` (or `screen`) for the steps below, so a run survives a dropped connection:
`tmux new -s qwen`, and later `tmux attach -t qwen`.

## 2. Get the code

```bash
git clone https://github.com/RaSh6119/infographics.git
cd infographics
mkdir -p data/few_shot   # then copy the three PNGs from the USB stick into it
```

## 3. Start the model server (terminal 1)

vLLM gets its own environment, so its library versions can't clash with the harness.

```bash
python3 -m venv ~/vllm-env
source ~/vllm-env/bin/activate
pip install vllm==0.33.0

CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen3.5-9B \
    --revision c202236235762e1c871ad0ccb60c8ee5ba337b9a \
    --port 8000 --max-model-len 32768
```

`CUDA_VISIBLE_DEVICES=0` uses the first H100 only, which leaves the second free. The `--revision`
must match `checkpoint` in `configs/models/qwen3_5_9b.yaml`. Leave this running and wait for
`Application startup complete`.

## 4. Set up the harness (terminal 2)

```bash
cd infographics
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-harness.txt
playwright install --with-deps chromium   # without sudo: playwright install chromium
```

Fonts, so pages render in the reference style instead of falling back to Arial (no sudo needed):

```bash
mkdir -p ~/.local/share/fonts && cd ~/.local/share/fonts
for w in Regular SemiBold Bold; do
  curl -sLO "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-$w.ttf"
done
curl -sL -o Inter.ttf "https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf"
fc-cache -f && cd -
```

## 5. Check everything

```bash
python scripts/check_env.py --server http://localhost:8000/v1
```

Every line should say PASS. WARN on API keys is fine for Qwen. Fix any FAIL before going on.

## 6. One quick test, then look at it

```bash
python scripts/run_setup.py --setup s1_zero_shot --model configs/models/qwen3_5_9b.yaml --limit 1 --samples 1
```

Open the `render.png` it reports under `runs/<prompt set>/`. If it looks reasonable, note how long it took: the
full runs below are 6 times that, per setup.

## 7. The real runs

6 dev prompts x 1 sample = 6 outputs per setup. (The plan asks for 3 samples per prompt; add
`--samples 3 --run-name <new name>` for that; the run log won't mix the two settings in one folder.)

```bash
python scripts/run_setup.py --setup s1_zero_shot --model configs/models/qwen3_5_9b.yaml
python scripts/run_setup.py --setup s2_few_shot  --model configs/models/qwen3_5_9b.yaml
```

If a run stops, run the same command again: finished samples are skipped. The summary at the end
says how many rendered successfully.

## 8. Bring the results home

`runs/` is not in git. Copy it back to the laptop:

```bash
tar czf qwen_runs.tgz runs/
```

Fonts differ between Linux and Windows, so for scoring we'll re-render every page's saved HTML on
one machine. Nothing needs doing about that here.

## If something goes wrong

| Problem | Fix |
|---|---|
| vLLM out of memory | Someone else is on that GPU (check `nvidia-smi`); try `CUDA_VISIBLE_DEVICES=1`, or add `--gpu-memory-utilization 0.8` |
| vLLM says the model type is unsupported | `pip install -U vllm` in `~/vllm-env` |
| vLLM fails with a CUDA or driver error | The driver may be too old for vLLM 0.33; send the error and the `nvidia-smi` output |
| `playwright install --with-deps` asks for sudo | Run `playwright install chromium` instead; if `check_env.py` then fails on rendering, the system libraries need an admin |
| Can't download from Hugging Face | The network may block it; download on another machine and copy the model folder over |
| Runs log `cut off at max_tokens` | Note how often; we can raise `max_tokens` in the model config |
| `model call failed` three times in a row, then stops | The vLLM server stopped; check terminal 1 |
