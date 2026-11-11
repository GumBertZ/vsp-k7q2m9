# -*- coding: utf-8 -*-
"""Munta el zip del pack a partir de modpack.json.

Us: python scripts/build_pack.py [--out dist]

- Els jars NO viuen a git. Es busquen a cache/ pel seu SHA-1; si hi falten i la
  font es "modrinth", es baixen de Modrinth pel mateix SHA-1. Els de font "local"
  s'han de posar a cache/ a ma (el script diu quins falten).
- Tot jar es comprova pel SHA-1 abans d'entrar al zip.
- local/servers.dat (fora de git) entra al zip si existeix.
"""
import argparse, hashlib, json, pathlib, sys, urllib.request, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = {"User-Agent": "pack-build/1.0"}


def sha1(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fetch_modrinth(digest, dest):
    req = urllib.request.Request("https://api.modrinth.com/v2/version_file/%s?algorithm=sha1" % digest, headers=UA)
    meta = json.load(urllib.request.urlopen(req, timeout=60))
    url = [f["url"] for f in meta["files"] if f["hashes"]["sha1"] == digest][0]
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r, open(dest, "wb") as f:
        f.write(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    a = ap.parse_args()
    m = json.loads((ROOT / "modpack.json").read_text(encoding="utf-8"))
    cache = ROOT / "cache"
    cache.mkdir(exist_ok=True)
    falten = []
    entrades = []  # (ruta al zip, fitxer)
    items = [dict(x, dest="mods/" + x["file"]) for x in m["mods"] if x["side"] in ("client", "both")]
    items.append(dict(m["loader"], dest="bin/modpack.jar"))
    for x in items:
        p = cache / x["file"]
        if not p.exists() and x["source"] == "modrinth":
            print("baixant", x["file"])
            fetch_modrinth(x["sha1"], p)
        if not p.exists():
            falten.append(x["file"])
            continue
        if sha1(p) != x["sha1"]:
            sys.exit("SHA-1 diferent: %s" % x["file"])
        entrades.append((x["dest"], p))
    if falten:
        sys.exit("Falten a cache/ (font local): " + ", ".join(falten))
    excl = set(m.get("config_exclude", []))
    for p in sorted((ROOT / "config").rglob("*")):
        rel = p.relative_to(ROOT).as_posix()
        if p.is_file() and rel not in excl:
            entrades.append((rel, p))
    for extra in m.get("root_files", []):
        entrades.append((extra, ROOT / "root" / extra))
    sd = ROOT / "local" / "servers.dat"
    if sd.exists():
        entrades.append(("servers.dat", sd))
    out = ROOT / a.out
    out.mkdir(exist_ok=True)
    z = out / ("%s-%s.zip" % (m["name"], m["version"]))
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for arc, p in entrades:
            zf.write(p, arc)
    nm = len([e for e in entrades if e[0].startswith("mods/")])
    print("OK %s: %d fitxers, %d mods, %.1f MB, sha1 %s" % (z.name, len(entrades), nm, z.stat().st_size / 1e6, sha1(z)))


if __name__ == "__main__":
    main()
