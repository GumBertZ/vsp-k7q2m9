# -*- coding: utf-8 -*-
"""Publica dist/<nom>-<versio>.zip com a Release v<versio> amb el CLI `gh` i imprimeix
l'enllaç directe de baixada (el que va al camp "Modpack Location" de Technic).

Us: python scripts/release_pack.py
Requisits: `gh` autenticat, el commit de la versio ja pujat, i el zip fet amb build_pack.py.
"""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
m = json.loads((ROOT / "modpack.json").read_text(encoding="utf-8"))
tag = "v" + m["version"]
z = ROOT / "dist" / ("%s-%s.zip" % (m["name"], m["version"]))
if not z.exists():
    sys.exit("Falta %s: executa abans build_pack.py" % z)
notes = []
on = False
for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
    if line.startswith("## "):
        on = line.startswith("## " + m["version"])
        continue
    if on and line.strip():
        notes.append(line)
import shutil
fix = ROOT / "dist" / ("%s.zip" % m["name"])  # copia amb nom fix: fa que l'enllaç "latest" valgui per a totes les versions
shutil.copy2(z, fix)
r = subprocess.run(["gh", "release", "create", tag, str(z), str(fix), "--title", tag, "--notes", "\n".join(notes) or tag], cwd=ROOT)
if r.returncode != 0:
    sys.exit(r.returncode)
repo = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
print("Enllac d'aquesta versio: https://github.com/%s/releases/download/%s/%s" % (repo, tag, z.name))
print("Enllac fix (sempre l'ultima): https://github.com/%s/releases/latest/download/%s" % (repo, fix.name))
