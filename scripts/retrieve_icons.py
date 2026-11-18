"""Setup 3: retrieve candidate Health Icons for every prompt in a set, once, and save them.

    python scripts/retrieve_icons.py --prompts data/prompts/dev_set.jsonl
    python scripts/retrieve_icons.py --prompts data/prompts/dev_set.jsonl --elements-first   # setup 3b

Writes data/icons/retrieved_<set>.json (label positions, glossary terms and icon IDs, never label
text), which setup 3 reads, so every model gets the same icons. Also prints each label with its
candidates so they can be checked before any model runs. Needs data/icons/index.json
(scripts/build_icon_index.py) and the sentence-transformers package; the first run downloads the
embedding model (about 130 MB).

With --elements-first (setup 3b), each label's icons come first from the project's elements
(data/icons/elements_index.json, scripts/build_elements_index.py) that match at least
ELEMENTS_MIN_SCORE, then from Health Icons; it writes data/icons/elements_retrieved_<set>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from infographics.harness.prompts import load_prompts  # noqa: E402
from infographics.rag.elements import NO_SIGN_ID as ELEMENTS_NO_SIGN_ID  # noqa: E402
from infographics.rag.elements import elements_hash, load_elements  # noqa: E402
from infographics.rag.icons import load_icons  # noqa: E402
from infographics.rag.retrieve import (  # noqa: E402
    ELEMENTS_MIN_SCORE,
    build_elements_record,
    build_record,
    elements_retrieved_path,
    load_glossary,
    retrieve,
    retrieve_elements_first,
    retrieved_path,
    sentence_transformer_embedder,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--quiet", action="store_true", help="don't print the candidates")
    parser.add_argument("--elements-first", action="store_true",
                        help="setup 3b: the project's elements first, Health Icons for the rest")
    args = parser.parse_args()

    prompts = load_prompts(args.prompts)
    icons = load_icons()
    embed, info = sentence_transformer_embedder()
    if args.elements_first:
        elements = load_elements()
        results = retrieve_elements_first(prompts, elements, icons, embed, load_glossary(), ELEMENTS_NO_SIGN_ID)
        record = build_elements_record(args.prompts, results, info, elements_hash())
        out = elements_retrieved_path(args.prompts)
        icons = {**icons, **elements}  # for printing titles
    else:
        results = retrieve(prompts, icons, embed, load_glossary())
        record = build_record(args.prompts, results, info)
        out = retrieved_path(args.prompts)
    out.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")

    if not args.quiet:
        for prompt in prompts:
            print(f"\n{prompt.id}")
            for entry in results[prompt.id]:
                label = prompt.required_text[entry["label_index"]]
                extra = f"  (+ {', '.join(entry['glossary_terms'])})" if entry["glossary_terms"] else ""
                print(f"  {label}{extra}")
                for c in entry["icons"]:
                    score = "  added" if c["score"] is None else f"{c['score']:.3f}"
                    print(f"      {score}  {c['id']}  ({icons[c['id']].title})")
    print(f"\nwrote {out.relative_to(ROOT)} using {info['model']} @ {info['revision'][:12]}")


if __name__ == "__main__":
    main()
