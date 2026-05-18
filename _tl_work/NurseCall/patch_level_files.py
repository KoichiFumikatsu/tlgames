"""Binary-patch Unity level files to replace language dropdown label.

'Fellow localize /English' (24 bytes) → 'Español' + spaces (24 bytes)
Length prefix kept at 0x18=24 so Unity parser reads the same field size.
"""
import io, sys, os, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

GAME_BASE = r"c:/xampp/htdocs/tl/proyects Game TL/Unity/ナースコール警備員/NurseCall_Data"
BACKUP_BASE = r"c:/xampp/htdocs/tl/backups/Unity/NurseCall-LevelFiles-20260429"

FILES = ["level0","level1","level2","level5","level6","level7","level8","level9","level10","resources.assets"]

OLD_STR = "Fellow localize /English"
NEW_STR = "Español" + " " * (len(OLD_STR.encode("utf-8")) - len("Español".encode("utf-8")))

old_b = OLD_STR.encode("utf-8")
new_b = NEW_STR.encode("utf-8")
assert len(old_b) == len(new_b), f"Length mismatch: {len(old_b)} vs {len(new_b)}"

prefix = len(old_b).to_bytes(4, "little")
old_pattern = prefix + old_b
new_pattern = prefix + new_b

print(f"OLD ({len(old_b)}B): {OLD_STR!r}")
print(f"NEW ({len(new_b)}B): {NEW_STR!r}")
print(f"Pattern: {old_pattern.hex()} → {new_pattern.hex()}")
print()

os.makedirs(BACKUP_BASE, exist_ok=True)

for fname in FILES:
    src = os.path.join(GAME_BASE, fname)
    bak = os.path.join(BACKUP_BASE, fname)

    with open(src, "rb") as f:
        data = f.read()

    count = data.count(old_pattern)
    if count == 0:
        print(f"  {fname}: pattern not found — skip")
        continue

    # Backup
    if not os.path.exists(bak):
        shutil.copy2(src, bak)

    new_data = data.replace(old_pattern, new_pattern)
    assert new_data.count(new_pattern) == count

    with open(src, "wb") as f:
        f.write(new_data)

    print(f"  {fname}: {count} replacement(s) ✓  (backup → {bak})")

print("\nDone.")
