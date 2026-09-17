#!/bin/bash
# diagnose.sh — Reporte de diagnostico TL Games Pipeline.
# Uso:
#   ./diagnose.sh                       Reporte general (servicios, health, ultimos jobs)
#   ./diagnose.sh <job_id>              Reporte general + detalle del job
#   ./diagnose.sh <job_id> --log-lines 100   Mas lineas del log
#   ./diagnose.sh --no-color            Sin ANSI colors (para redirigir a archivo)
#
# Output diseñado para copy-paste a Claude cuando algo falle.

JOB_ID=""
LOG_LINES=30
USE_COLOR=1

while [ $# -gt 0 ]; do
  case "$1" in
    --log-lines) LOG_LINES="$2"; shift 2 ;;
    --no-color)  USE_COLOR=0; shift ;;
    -h|--help)
      sed -n '2,11p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) JOB_ID="$1"; shift ;;
  esac
done

if [ $USE_COLOR -eq 1 ] && [ -t 1 ]; then
  R=$'\e[31m'; G=$'\e[32m'; Y=$'\e[33m'; B=$'\e[34m'; C=$'\e[36m'; D=$'\e[2m'; N=$'\e[0m'; BOLD=$'\e[1m'
else
  R=''; G=''; Y=''; B=''; C=''; D=''; N=''; BOLD=''
fi

sep() { printf "${B}%s${N}\n" "────────────────────────────────────────────────────────────────"; }
hdr() { printf "\n${BOLD}${C}[%s] %s${N}\n" "$1" "$2"; }
ok()  { printf "  ${G}✓${N} %s\n" "$1"; }
bad() { printf "  ${R}✗${N} %s\n" "$1"; }
warn(){ printf "  ${Y}!${N} %s\n" "$1"; }

# ── Header ────────────────────────────────────────────────────────────────────
sep
printf "${BOLD}TL Games Pipeline — Diagnose${N}\n"
printf "${D}Fecha: %s${N}\n" "$(date '+%Y-%m-%d %H:%M:%S')"
printf "${D}Job ID: %s${N}\n" "${JOB_ID:-<ninguno>}"
sep

# ── 1. Servicios systemd ──────────────────────────────────────────────────────
hdr 1 "Servicios systemd"
for svc in tlgames-pipeline tlgames-qa tlgames-versions; do
  status=$(systemctl --user is-active $svc 2>/dev/null)
  uptime=$(systemctl --user show $svc --property=ActiveEnterTimestamp --value 2>/dev/null | sed 's/^.\{4\}//' | cut -d' ' -f1-2)
  if [ "$status" = "active" ]; then
    ok "$svc — active desde $uptime"
  else
    bad "$svc — $status"
  fi
done

# ── 2. Health endpoints ──────────────────────────────────────────────────────
hdr 2 "Health endpoints"

PIPELINE_HEALTH=$(curl -s --max-time 5 http://localhost:8766/health 2>/dev/null)
if [ -z "$PIPELINE_HEALTH" ]; then
  bad "pipeline_server (8766): SIN RESPUESTA"
else
  python3 <<PYEOF
import json
d = json.loads('''$PIPELINE_HEALTH''')
print(f"  pipeline_server: status={d.get('status')} jobs_en_memoria={d.get('jobs')}")
print(f"  ollama:  {d.get('ollama')}")
dl = d.get('deepl') or {}
if dl:
  print(f"  deepl:   {dl.get('total_used',0):,} / {dl.get('total_limit',0):,} chars  | available={dl.get('available',0):,}  | keys={dl.get('key_count')} | source={dl.get('source')}")
  print(f"  deepl_exhausted_today: {d.get('deepl_exhausted_today')}")
oa = d.get('openai') or {}
if oa:
  pct = (oa.get('spent_usd',0) / oa.get('budget_usd',1)) * 100 if oa.get('budget_usd') else 0
  print(f"  openai:  \${oa.get('spent_usd',0):.4f} / \${oa.get('budget_usd',0):.2f} ({pct:.1f}%) | available=\${oa.get('available_usd',0):.4f} | requests={oa.get('requests')}")
PYEOF
fi

QA_HEALTH=$(curl -s --max-time 5 http://localhost:8765/health 2>/dev/null)
if [ -z "$QA_HEALTH" ]; then
  bad "qa_server (8765): SIN RESPUESTA"
else
  python3 <<PYEOF
import json
d = json.loads('''$QA_HEALTH''')
print(f"  qa_server: backend={d.get('backend')} model={d.get('model')}")
PYEOF
fi

VER_HEALTH=$(curl -s --max-time 3 http://localhost:8767/health 2>/dev/null)
if [ -z "$VER_HEALTH" ]; then
  warn "version_tracker (8767): sin respuesta (opcional, no critico)"
else
  ok "version_tracker (8767): OK"
fi

# ── 3. Ultimos 5 jobs ────────────────────────────────────────────────────────
hdr 3 "Ultimos 5 jobs"
JOBS_FILE=$(mktemp)
curl -s --max-time 5 http://localhost:8766/jobs -o "$JOBS_FILE" 2>/dev/null
if [ ! -s "$JOBS_FILE" ]; then
  bad "No se pudo obtener /jobs"
else
  G_ESC="$G" R_ESC="$R" Y_ESC="$Y" N_ESC="$N" python3 -W ignore - "$JOBS_FILE" <<'PYEOF'
import json, sys, os
G=os.environ.get('G_ESC',''); R=os.environ.get('R_ESC',''); Y=os.environ.get('Y_ESC',''); N=os.environ.get('N_ESC','')
with open(sys.argv[1], 'r', encoding='utf-8') as f:
  data = json.load(f)
jobs = (data.get('jobs') or [])[-5:]
if not jobs:
  print("  (sin jobs)")
for j in jobs:
  status = j.get('status','?')
  tag = f"{G}OK {N}" if status=='done' else f"{R}ERR{N}" if status in ('error','unsupported') else f"{Y}RUN{N}"
  pct = j.get('overall_pct') if 'overall_pct' in j else (j.get('stats',{}) or {}).get('pct',0)
  print(f"  {j.get('job_id','?'):>8s}  {tag}  pct={(pct or 0):3d}%  {(j.get('game_name','?') or '')[:50]}")
PYEOF
fi

# ── 4. Detalle del job (si dieron ID) ────────────────────────────────────────
if [ -n "$JOB_ID" ]; then
  hdr 4 "Detalle del job $JOB_ID"
  JOB_FILE=$(mktemp)
  curl -s --max-time 5 "http://localhost:8766/pipeline/$JOB_ID" -o "$JOB_FILE" 2>/dev/null
  # Si el job no esta en memoria, intentar history
  if [ ! -s "$JOB_FILE" ] || grep -q '"error".*"job no encontrado"' "$JOB_FILE"; then
    warn "Job no encontrado en memoria — buscando en history jsonl"
    HIST="/home/kelsie/projects/tlgames/logs/pipeline_jobs_history.jsonl"
    if [ -f "$HIST" ]; then
      grep -F "\"$JOB_ID\"" "$HIST" | tail -1 > "$JOB_FILE"
    fi
  fi
  if [ ! -s "$JOB_FILE" ]; then
    bad "Job $JOB_ID no existe en memoria ni en history"
  else
    R_ESC="$R" Y_ESC="$Y" N_ESC="$N" LOG_LINES="$LOG_LINES" python3 -W ignore - "$JOB_FILE" <<'PYEOF'
import json, sys, os, datetime
R=os.environ.get('R_ESC',''); Y=os.environ.get('Y_ESC',''); N=os.environ.get('N_ESC','')
LOG_LINES=int(os.environ.get('LOG_LINES','30'))
with open(sys.argv[1], 'r', encoding='utf-8') as f:
  j = json.load(f)
print(f"  game: {j.get('game_name','?')}")
print(f"  path: {j.get('game_path','?')}")
print(f"  status: {j.get('status')} | current_stage: {j.get('current_stage')} | overall: {j.get('overall_pct',0)}%")
if j.get('error'):   print(f"  ${R}ERROR:${N} {j['error']}")
if j.get('warning'): print(f"  ${Y}WARNING:${N} {j['warning']}")

a = j.get('analysis') or {}
if a:
  print(f"\n  Analysis: {a.get('engine')} v{a.get('version')} {'/'.join(a.get('os') or [])} {a.get('runtime') or ''}")
  print(f"    chars={a.get('chars_count',0):,} files={a.get('files_count',0)} size={a.get('size_gb',0)}GB")
  print(f"    provider chosen: {a.get('chosen_provider')} ({a.get('provider_reason')})")
  print(f"    deepl_avail: {a.get('deepl_quota_avail',0):,} chars | openai_budget_avail: \${a.get('openai_budget_avail',0):.4f}")

st = j.get('stages') or {}
if st:
  print("\n  Stages:")
  for name in ['analyze','setup','translate','lint_qa','package']:
    s = st.get(name,{})
    d = s.get('details') or {}
    extra = ''
    for k in ('skipped_reason','reason','zip_path','size_mb','qa_issues','files_done','strings_done','provider_final','copy_path'):
      v = d.get(k)
      if v not in (None, ''):
        extra += f" {k}={v}"
    print(f"    {name:10s}: status={s.get('status'):8s} pct={s.get('pct',0):3d}{extra}")

stats = j.get('stats') or {}
if stats:
  print(f"\n  Stats: provider={stats.get('provider')} files={stats.get('files_done')}/{stats.get('total_files')} strings={stats.get('strings_done')}/{stats.get('total_strings')} openai_spent=\${stats.get('openai_spent',0):.4f}")
  if stats.get('current_file'):
    print(f"         current_file: {stats['current_file']}")

events = j.get('events') or []
critical = [e for e in events if e.get('event') in ('error','warn','provider_switch')]
if critical:
  print(f"\n  Eventos criticos (errors/warns/switches) — ultimos 10:")
  for e in critical[-10:]:
    ts = datetime.datetime.fromtimestamp(e['ts']).strftime('%H:%M:%S')
    if e['event'] == 'provider_switch':
      print(f"    {ts} [{e.get('stage')}] PROVIDER {e.get('from')} -> {e.get('to')} ({e.get('reason','')})")
    else:
      color = R if e['event']=='error' else Y
      print(f"    {ts} [{e.get('stage')}] {color}{e['event'].upper()}{N}: {(e.get('message') or '')[:120]}")

prog = j.get('progress') or []
if prog:
  print(f"\n  Ultimas {LOG_LINES} lineas del log:")
  for p in prog[-LOG_LINES:]:
    print(f"    {(p or '')[:200]}")
PYEOF
  fi
  rm -f "$JOB_FILE"
fi
rm -f "$JOBS_FILE" 2>/dev/null

# ── 5. Disco ──────────────────────────────────────────────────────────────────
hdr 5 "Disco"
df -h "/home/kelsie/Documents/games tl/" 2>/dev/null | tail -1 | awk '{printf "  partition: used=%s avail=%s use=%s mount=%s\n",$3,$4,$5,$6}'
if [ -d "/home/kelsie/Documents/games tl/" ]; then
  count=$(ls "/home/kelsie/Documents/games tl/" 2>/dev/null | wc -l)
  zips=$(ls "/home/kelsie/Documents/games tl/"*.zip 2>/dev/null | wc -l)
  printf "  games tl/: %d entradas (%d zips)\n" "$count" "$zips"
fi

# ── 6. Errores recientes en systemd ──────────────────────────────────────────
hdr 6 "Errores systemd ultimas 2h (pipeline + qa)"
errs=$(sudo -n journalctl -u tlgames-pipeline -u tlgames-qa --since "2 hours ago" 2>/dev/null | grep -iE "error|traceback|exception|failed" | tail -10)
if [ -z "$errs" ]; then
  ok "Sin errores en journalctl"
else
  echo "$errs" | sed 's/^/  /'
fi

# ── 7. Snapshot env relevante ────────────────────────────────────────────────
hdr 7 "Variables .env relevantes (oculta keys)"
if [ -f /home/kelsie/projects/tlgames/.env ]; then
  python3 <<'PYEOF'
import re
for line in open('/home/kelsie/projects/tlgames/.env'):
  line = line.strip()
  if not line or line.startswith('#') or '=' not in line: continue
  k, _, v = line.partition('=')
  if any(s in k.upper() for s in ('KEY','SECRET','TOKEN','PASSWORD')):
    v = (v[:8] + '...' + v[-4:]) if len(v) > 14 else '<set>'
  print(f"  {k}={v}")
PYEOF
fi

sep
printf "${D}Diagnostico completo. Para mas log: ./diagnose.sh <job_id> --log-lines 100${N}\n"
sep
