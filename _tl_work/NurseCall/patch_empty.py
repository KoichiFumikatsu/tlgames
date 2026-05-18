"""Patch entries with empty 'target' in es_corpus.jsonl.
Processes in small batches (10), verifies non-empty, rewrites in-place.
"""
import io, sys, json, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(r"c:/xampp/htdocs/tl/.env")
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

CORPUS = r"c:/xampp/htdocs/tl/_tl_work/NurseCall/es_corpus.jsonl"
MODEL = "gpt-4.1-nano"
BATCH = 10
MAX_RETRIES = 3

SYSTEM_PROMPT = (
    "You are a professional localizer. The user sends a JSON array with 'id' and 'source' (English text). "
    "Translate each 'source' into natural Spanish (neutral). "
    "Keep '@' characters in exactly the same positions (they are line-break markers). "
    "Return ONLY a valid JSON array where each object has 'id' and 'target'. No markdown."
)

with open(CORPUS, encoding="utf-8") as f:
    entries = [json.loads(l) for l in f]

empty_idx = [i for i, e in enumerate(entries) if not e.get("target", "").strip()]
print(f"Empty entries to patch: {len(empty_idx)}")

for batch_start in range(0, len(empty_idx), BATCH):
    batch_indices = empty_idx[batch_start:batch_start + BATCH]
    batch = [{"id": entries[i]["id"], "source": entries[i]["source"]} for i in batch_indices]

    for attempt in range(MAX_RETRIES):
        try:
            payload = json.dumps(batch, ensure_ascii=False)
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": payload},
                ],
                temperature=0.3,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            results = json.loads(raw)

            id_to_target = {str(r["id"]): r.get("target", "") for r in results}
            all_ok = True
            for i, idx in enumerate(batch_indices):
                eid = entries[idx]["id"]
                tgt = id_to_target.get(str(eid), "").strip()
                if not tgt:
                    print(f"  WARN: empty target for ID {eid} on attempt {attempt+1}")
                    all_ok = False
                else:
                    entries[idx]["target"] = tgt

            if all_ok:
                break
            # retry if some empty
            time.sleep(1)
        except Exception as e:
            print(f"  ERROR attempt {attempt+1}: {e}")
            time.sleep(2)

    done = batch_start + len(batch_indices)
    print(f"  [{done}/{len(empty_idx)}] patched IDs {[e['id'] for e in batch]}")

# Write back
with open(CORPUS, "w", encoding="utf-8") as f:
    for e in entries:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")

# Final check
still_empty = [e for e in entries if not e.get("target", "").strip()]
print(f"\nDone. Still empty: {len(still_empty)}")
if still_empty:
    for e in still_empty[:5]:
        print(f"  [{e['id']}] {e['source'][:50]!r}")
