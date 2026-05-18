"""Diagnóstico de cuotas Gemini disponibles en el free tier."""
import urllib.request, json, os, sys, re
sys.path.insert(0, 'tools/tl')
from _env import load_env
load_env()
k = os.environ['GEMINI_API_KEY']
for m in ['gemini-2.5-flash', 'gemini-2.5-pro']:
    print(f"\n=== {m} ===")
    for i in range(6):
        r = urllib.request.Request(
            f'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={k}',
            data=json.dumps({'contents': [{'role': 'user', 'parts': [{'text': 'hi'}]}]}).encode(),
            headers={'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(r, timeout=30):
                print(i, 'OK')
        except urllib.error.HTTPError as e:
            msg = e.read().decode()
            qv = re.search(r'"quotaValue":\s*"(\d+)"', msg)
            qi = re.search(r'"quotaId":\s*"([^"]+)"', msg)
            rd = re.search(r'"retryDelay":\s*"([^"]+)"', msg)
            print(i, 'HTTP', e.code,
                  'quotaValue=', qv.group(1) if qv else '?',
                  'quotaId=', qi.group(1) if qi else '?',
                  'retry=', rd.group(1) if rd else '?')
            break
