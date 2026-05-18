"""Translate en_corpus.jsonl EN→ES using OpenAI gpt-4.1-nano.

Strategy:
- Batch 25 strings per request to minimize API calls
- @ is a line-break marker — preserve exactly
- Output: es_corpus.jsonl  {"id": "...", "source": "...", "target": "..."}
- Resume: skip IDs already present in es_corpus.jsonl
"""
import io, sys, json, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(r"c:/xampp/htdocs/tl/.env")

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

IN_FILE  = Path(r"c:/xampp/htdocs/tl/_tl_work/NurseCall/en_corpus.jsonl")
OUT_FILE = Path(r"c:/xampp/htdocs/tl/_tl_work/NurseCall/es_corpus.jsonl")

BATCH = 25
MODEL = "gpt-4.1-nano"

SYSTEM_PROMPT = """\
You are a professional Japanese-to-Spanish localizer. The user will send you a JSON array of objects with "id" and "source" (English text from a Japanese adult visual novel game about a hospital security guard). Translate each "source" into natural Spanish (Spain/neutral). Rules:
- The character "@" is a line-break marker — preserve it in exactly the same positions.
- Preserve square-bracket placeholders like [NAME] unchanged.
- Translate button labels, menu items, and UI strings concisely.
- Use "tú" (informal) for dialogue.
- Return ONLY a JSON array with the same objects adding a "target" field. No markdown, no commentary.
"""

def translate_batch(batch: list[dict]) -> list[dict]:
    payload = json.dumps([{"id": e["id"], "source": e["source"]} for e in batch], ensure_ascii=False)
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": payload},
        ],
        temperature=0.2,
    )
    raw = resp.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    result = json.loads(raw)
    return result

# Load already-translated IDs for resume
done_ids: set[str] = set()
if OUT_FILE.exists():
    with open(OUT_FILE, encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            done_ids.add(str(obj["id"]))

# Load corpus
corpus = []
with open(IN_FILE, encoding="utf-8") as f:
    for line in f:
        corpus.append(json.loads(line))

todo = [e for e in corpus if str(e["id"]) not in done_ids]
print(f"Total: {len(corpus)}  Already done: {len(done_ids)}  Remaining: {len(todo)}")

total_cost_est = 0.0
translated = 0

with open(OUT_FILE, "a", encoding="utf-8") as out_f:
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i+BATCH]
        try:
            results = translate_batch(batch)
        except Exception as e:
            print(f"ERROR batch {i//BATCH}: {e}", file=sys.stderr)
            time.sleep(5)
            continue

        # Merge source back and write
        id_to_source = {str(e["id"]): e["source"] for e in batch}
        for item in results:
            item_id = str(item.get("id", ""))
            entry = {
                "id": item_id,
                "source": id_to_source.get(item_id, ""),
                "target": item.get("target", ""),
            }
            out_f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        out_f.flush()

        translated += len(results)
        chars_batch = sum(len(e["source"]) for e in batch)
        total_cost_est += chars_batch * 4 / 1_000_000 * 0.10  # rough: 4 tokens/char at $0.10/1M input
        print(f"  [{translated}/{len(todo)}] batch {i//BATCH+1} done — est. cost so far: ${total_cost_est:.4f}")

print(f"\nDone. {translated} strings translated. Est. total cost: ${total_cost_est:.4f}")
