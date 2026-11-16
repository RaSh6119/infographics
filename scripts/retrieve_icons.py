"""Setup 3: retrieve candidate Health Icons for every prompt in a set, once, and save them.

    python scripts/retrieve_icons.py --prompts data/prompts/dev_set.jsonl

Writes data/icons/retrieved_<set>.json (label positions, glossary terms and icon IDs, never label
text), which setup 3 reads, so every model gets the same icons. Also prints each label with its
candidates so they can be checked before any model runs. Needs data/icons/index.json
(scripts/build_icon_index.py) and the sentence-transformers package; the first run downloads the
embedding model (about 130 MB).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from infographics.harness.prompts import load_prompts  # noqa: E402
from infographics.rag.icons import load_icons  # noqa: E402
from infographics.rag.retrieve import (  # noqa: E402
    build_record,
    load_glossary,
    retrieve,
    retrieved_path,
    sentence_transformer_embedder,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--quiet", action="store_true", help="don't print the candidates")
    args = parser.parse_args()

    prompts = load_prompts(args.prompts)
    icons = load_icons()
    embed, info = sentence_transformer_embedder()
    results = retrieve(prompts, icons, embed, load_glossary())

    out = retrieved_path(args.prompts)
    out.write_text(json.dumps(build_record(args.prompts, results, info), indent=1) + "\n", encoding="utf-8")

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
