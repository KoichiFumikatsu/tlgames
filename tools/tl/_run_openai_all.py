"""Runner secuencial: traduce todos los .rpy de tl/spanish con OpenAI.

Ordena por tamaño (pequeños primero) para validar el flujo antes de los
archivos grandes. Tras cada archivo imprime el gasto acumulado.
"""
import sys, subprocess, json, pathlib, time

ROOT = pathlib.Path(sys.argv[1])
USAGE = pathlib.Path("tools/tl/.cache/openai_usage.json")

files = sorted(ROOT.rglob("*.rpy"), key=lambda p: p.stat().st_size)
print(f"[runner] {len(files)} archivos en {ROOT}", flush=True)

for i, f in enumerate(files, 1):
    print(f"\n[runner] === [{i}/{len(files)}] {f.name} ({f.stat().st_size//1024}KB) ===", flush=True)
    t0 = time.time()
    rc = subprocess.call([sys.executable, "-u", "tools/tl/translate.py", str(f), "--provider", "openai"])
    dt = time.time() - t0
    if USAGE.exists():
        u = json.loads(USAGE.read_text())
        print(f"[runner] file rc={rc} dt={dt:.1f}s | total acumulado: ${u['total_cost_usd']:.4f} ({u['requests']} reqs)", flush=True)
        if u['total_cost_usd'] >= 0.95:  # margen vs budget
            print("[runner] CERCA DEL BUDGET ($0.95). Deteniendo.", flush=True)
            break
    else:
        print(f"[runner] file rc={rc} dt={dt:.1f}s | sin usage tracker", flush=True)
print("\n[runner] DONE", flush=True)
