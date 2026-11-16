# Findings: frontier models, setups 1 and 2, dev set (2026-11-16)

## What was run

| | |
|---|---|
| Models | GPT-5.5 (`gpt-5.5-2026-04-23`, reasoning effort medium, default temperature), Claude Opus 5.5 (`claude-opus-5-5`, effort medium, default temperature), Gemini 3.1 Pro (`gemini-3.1-pro-preview`, temperature 0.2) |
| Setups | 1 zero-shot (system prompt + prompt); 2 few-shot (adds reference pages 14E, 5E, 10E) |
| Prompts | `data/prompts/dev_set.jsonl`: 6 prompts, one per type plus the pilot list prompt |
| Samples | 1 per prompt (the plan's protocol is 3) |
| Total | 36 pages, all rendered without errors |
| Per-page scores | `results/ocr_runs.csv` (not in git), made by `scripts/score_runs.py` |

Temperature differs by model because Claude Opus 5.5 rejects the parameter and GPT-5.5 accepts only
its default while reasoning is on. Each run logs the temperature it actually used.

## Metric 4: OCR text fidelity

| Setup | Model | Text fidelity | Word recall | Phrase recall | Pages with all text |
|---|---|---|---|---|---|
| 1 zero-shot | Claude Opus 5.5 | 1.000 | 1.000 | 1.000 | 6/6 |
| 1 zero-shot | Gemini 3.1 Pro | 0.989 | 0.969 | 0.915 | 3/6 |
| 1 zero-shot | GPT-5.5 | 0.972 | 0.945 | 0.878 | 3/6 |
| 2 few-shot | Claude Opus 5.5 | 0.997 | 0.992 | 0.976 | 5/6 |
| 2 few-shot | Gemini 3.1 Pro | 1.000 | 1.000 | 1.000 | 6/6 |
| 2 few-shot | GPT-5.5 | 0.998 | 0.995 | 0.976 | 5/6 |

## Every flagged page, checked by eye

8 pages lost at least one phrase. 7 are real layout defects; 1 is an OCR error.

| Setup | Model | Prompt | Defect | Real? |
|---|---|---|---|---|
| 1 | Gemini 3.1 Pro | pilot_list_001 | Title runs off the right edge ("...prevention strateg") | Yes |
| 1 | GPT-5.5 | pilot_list_001 | Title runs off the right edge | Yes |
| 1 | GPT-5.5 | dev_process_001 | Title runs off the right edge ("Prevention V..."); step 3 label also clipped | Yes |
| 1 | Gemini 3.1 Pro | dev_timeline_001 | Adjacent labels collide ("...usually ease" runs into "Complete the full course") | Yes |
| 1 | Gemini 3.1 Pro | dev_process_001 | An arrow is drawn over "Review available PrEP methods" | Yes |
| 1 | GPT-5.5 | dev_comparison_001 | Icons drawn over four labels | Yes |
| 2 | GPT-5.5 | dev_process_001 | A checkmark drawn over "Choose the method" | Yes |
| 2 | Claude Opus 5.5 | dev_list_001 | Page shows "U=U" correctly; OCR read "=" as "-" | No (OCR error) |

## Observations

- Every real defect is a layout failure: text clipped at the page edge, or covered by icons and
  arrows. No model misspelled or changed a required phrase.
- Few-shot raised GPT-5.5 and Gemini from 3/6 pages with all text to 5/6 and 6/6. Claude was
  already at 6/6 zero-shot.
- The renderer's overflow check did not flag the three titles that run off the page: text clipped
  at the right edge is currently caught only by OCR.
- OCR can under-report: GPT-5.5's clipped "Review available PrEP methods" (setup 1, process) was
  still read and counted as present.
- OCR can over-report: "U=U" was misread. Metric 4 needs the human review alongside it.

## Decisions

- These failures are kept as findings. The system prompt and renderer were not changed to fix
  them, so later runs stay comparable with these.
- The system prompt asks for the exact phrases and also for a sentence-case title, which
  conflict; models resolved it differently. Metric 4 ignores case, so scores are unaffected. Kept
  as is for the same reason.

## Gemma 4 E4B (local, added the same day)

Gemma 4 E4B via Ollama on the laptop (Q4_K_M, digest dc35e8d9c606, thinking off, temperature 0.2,
seed sent), same setups and prompts. Scores: `results/ocr_gemma_dev_set.csv`.

| Setup | Rendered OK | Official text fidelity | As-rendered fidelity (diagnostic) | As-rendered pages with all text |
|---|---|---|---|---|
| 1 zero-shot | 0/6 | 0.000 | 0.997 | 5/6 |
| 2 few-shot | 0/6 | 0.000 | 1.000 | 6/6 |

- Every page loads Poppins and Inter from fonts.googleapis.com, which the output contract
  forbids, so every page fails (broken_asset) and officially scores 0. The frontier models did
  this on 0 of 36 pages.
- The as-rendered columns OCR the screenshot anyway, as a diagnostic only. The one as-rendered miss
  (setup 1, dev_list_001) is an OCR error: the page shows "U=U" correctly.
- High as-rendered text scores hide weak visuals: many of Gemma's icons are generic circles that
  depict nothing. Metric 4 does not measure that; the human review does.

## Qwen3.5-9B (local, workstation)

Qwen3.5-9B via vLLM 0.33.0 (revision c2022362, bf16, thinking off, temperature 0.2, seed sent) on a
workstation with one RTX PRO 6000 Blackwell 96 GB (not the H100 in the plan, so its latencies are
not H100 latencies). Rendered on the workstation, which has Poppins and Inter installed; the laptop
renders above used fallback fonts for Poppins. Scores: `results/ocr_qwen_dev_set.csv`.

| Setup | Rendered OK | Official text fidelity | Official phrase recall | As-rendered fidelity (diagnostic) | As-rendered phrase recall |
|---|---|---|---|---|---|
| 1 zero-shot | 0/6 | 0.000 | 0.000 | 0.900 | 0.746 |
| 2 few-shot | 6/6 | 0.717 | 0.603 | 0.717 | 0.603 |

- Every setup 1 page loads Google Fonts (broken_asset); no setup 2 page does. The reference pages
  appear to change this behaviour.
- In a test page (since deleted) and in one clinic page, Qwen looped, drawing the same SVG line
  segments until max_tokens (16,384). On the dev set no page looped.
- Low setup 2 scores are real omissions, checked by eye: the comparison page shows only the two
  column headings and drops all six labels; the timeline clips its labels inside boxes that are too
  small; the pilot list cuts off its title and four of its six cards at the page edge.

## Setup 3 retrieval: design, tuned on the dev set, frozen 2026-11-16

- Icon database: 776 Health Icons (CC0, commit 2080c1b) plus 10 generic supplementary icons from
  Material Symbols (Apache 2.0, commit 10ecc147): clock, hourglass, alarm clock, arrows down / up /
  right, percent, "no" sign, shield with checkmark, calendar with checkmark. Added because the dev
  retrieval showed Health Icons has no clocks, arrows or general "no" sign.
- Retrieval: BAAI/bge-small-en-v1.5 (revision 5c38ec7c) embeds each icon's title, tags and category.
  Each label (required phrase except the title) is a query, expanded by configs/icon_glossary.yaml.
  A negated label ("Don't share needles") is searched without the negation and gets the "no" sign as
  an extra candidate. At most 15 icons per prompt (3, 2 or 1 per label), grouped by label in the
  prompt; models may draw their own symbol when nothing fits (option A).
- Tuned over three rounds on the dev prompts only (glossary entries, the category text, the
  negation rule), then frozen before retrieving for any other set.
- Known weak dev retrievals left as they are rather than fitted to single phrases: "Choose the
  method that works best for you" gets Yoga and Exercise; "Sex" ranks a contraceptive voucher above
  the condoms.
- First test page (Claude Opus 5.5, dev_stat_001): 5 icons placed (4 distinct) of 13 offered, none
  invented; all required text present.

## Caveats

- 6 pages per model and setup, 1 sample each: early signals, not results.
- The dev prompts' medical figures were drafted for pipeline testing and were not checked by a
  clinician. They differ from the clinic content (e.g. PrEP efficacy 90-99%).
- Token counts are not comparable across providers yet: Gemini's OpenAI-compatible endpoint
  appears to exclude thinking tokens from its reported output tokens.
