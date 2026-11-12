# -*- coding: utf-8 -*-
"""Regenera pw/ (el pack en format packwiz) a partir de modpack.json.

Us: python scripts/pw_refresh.py [--packwiz RUTA] [--offline] [--verify] [--repo PROPIETARI/REPO] [--jars-tag jars-1]

Que fa (un sol pas):
  1. pw/mods/<id>.pw.toml: un fitxer de metadades per mod de modpack.json.
       - Modrinth: es busca pel SHA-1 del jar (API de Modrinth); font i hash SHA-512.
       - CurseForge: amb `packwiz curseforge detect` (cal el binari de packwiz, --packwiz o al PATH);
         guarda projecte i fitxer. El hash es el SHA-1 que dona CurseForge.
       - Cap plataforma: URL directa a un asset del Release `--jars-tag` d'aquest repositori
         (el script llista quins jars s'han de pujar i amb quin nom).
     Si el fitxer ja existeix i coincideix amb el jar, es deixa tal com esta (no cal xarxa).
  2. pw/config/ i pw/options.txt: copia de config/ i root/ (config_exclude i root_files de modpack.json).
  3. pw/index.toml i pw/pack.toml: index amb SHA-256 de cada fitxer, `metafile = true` per als .pw.toml i
     `preserve = true` per als fitxers de PRESERVE (mes avall). Format segons packwiz.infra.link.
  4. pw/.packwizignore: deixa fora de l'index la carpeta pw/instancia/ (plantilla de la instancia de Prism).

Despres de refrescar, per publicar: commit + push de la branca `pw` (les URL del pack apunten a aquesta branca).
`--verify` executa `packwiz refresh` sobre una copia i comprova que el resultat es identic (cal packwiz).

Politica de configuracio (la decisio i el motiu estan a l'informe del pack):
  - PRESERVE: s'instal.la un cop i no es toca mai mes (gustos del jugador, ajustos de la seva maquina).
  - la resta (per defecte): "mana sempre": quan el fitxer canvia al pack, el jugador el rep i se li sobreescriu.
    Un fitxer nou que no surt a PRESERVE es tracta com a "mana sempre"; el script el mostra al resum.
"""
import argparse, fnmatch, hashlib, json, os, pathlib, re, shutil, subprocess, sys, tempfile, tomllib
import urllib.error, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
PW = ROOT / "pw"
UA = {"User-Agent": "pack-build/1.0"}
MODRINTH = "https://api.modrinth.com/v2"

# Fitxers que s'instal.len un cop i no es sobreescriuen (preserve = true). Camins relatius a pw/, patrons fnmatch.
PRESERVE = [
    "options.txt",                              # video, so, tecles: del jugador
    "config/embeddium-options.json",            # qualitat grafica
    "config/entityculling.json",                # culling d'entitats (client)
    "config/yacl.json5",                        # aspecte de la UI de configuracio
    "config/jei/*",                             # JEI: interficie, ordenacio, llista oculta
    "config/configured-client.properties",      # UI de configuracio (client)
    "config/gravestone-client.toml",            # aspecte de la tomba (client)
    "config/neoforge-client.toml",              # NeoForge: avisos i render (client)
    "config/fml.toml",                          # carregador: finestra primerenca, versions de GL; depen de la maquina
    "config/enchdesc.json",                     # descripcions d'encanteris: com es mostren
]

# Mods que SEMPRE van per URL a un Release d'aquest repositori, encara que siguin a una plataforma.
# Cas conegut: un mod que CurseForge exclou de l'API (l'autor no permet la baixada de tercers) fa fallar
# packwiz-installer 0.5.14 amb "This mod is excluded from the CurseForge API and must be downloaded manually".
# Avui no n'hi ha cap (torohealth es va substituir el 2026-11-12).
FORCE_URL = {}  # id -> nom a mostrar

# Fitxers de pw/ que no es cataloguen a l'index (a mes de pack.toml, index.toml i .packwizignore).
IGNORE_TOP = {"instancia", ".git", ".gitattributes", ".gitignore", ".DS_Store"}
PACKWIZIGNORE = "# Fora de l'index: la plantilla de la instancia de Prism no va a la carpeta del joc.\n/instancia/\n"


# ---------- utilitats ----------

def digest(path, algo):
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def q(s):
    """Cadena TOML basica."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def http_json(url, data=None):
    body = json.dumps(data).encode() if data is not None else None
    headers = dict(UA)
    if body is not None:
        headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=60) as r:
        return json.load(r)


def repo_slug():
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    sys.exit("No puc deduir el repositori: passa --repo PROPIETARI/REPO")


def find_packwiz(arg):
    cand = [arg] if arg else []
    cand.append(shutil.which("packwiz"))
    for c in cand:
        if c and pathlib.Path(c).exists():
            return str(c)
    return None


# ---------- metadades (.pw.toml) ----------

def meta_modrinth(name, filename, side, url, sha512, project, version):
    return ("name = %s\nfilename = %s\nside = %s\n\n[download]\nurl = %s\nhash-format = \"sha512\"\nhash = %s\n\n"
            "[update]\n[update.modrinth]\nmod-id = %s\nversion = %s\n"
            % (q(name), q(filename), q(side), q(url), q(sha512), q(project), q(version)))


def meta_curseforge(name, filename, side, sha1, project_id, file_id):
    return ("name = %s\nfilename = %s\nside = %s\n\n[download]\nhash-format = \"sha1\"\nhash = %s\n"
            "mode = \"metadata:curseforge\"\n\n[update]\n[update.curseforge]\nfile-id = %d\nproject-id = %d\n"
            % (q(name), q(filename), q(side), q(sha1), int(file_id), int(project_id)))


def meta_url(name, filename, side, url, sha256):
    return ("name = %s\nfilename = %s\nside = %s\n\n[download]\nurl = %s\nhash-format = \"sha256\"\nhash = %s\n"
            % (q(name), q(filename), q(side), q(url), q(sha256)))


def kind_of(meta):
    if "modrinth" in meta.get("update", {}):
        return "modrinth"
    if "curseforge" in meta.get("update", {}):
        return "curseforge"
    return "url"


def check_meta(meta, mod, jar):
    """Torna (valid, verificat). valid: la metadada correspon a aquest mod; verificat: el hash s'ha comparat amb el jar."""
    if meta.get("filename") != mod["file"]:
        return False, False
    if (mod["id"] in FORCE_URL) != (kind_of(meta) == "url"):
        return False, False
    d = meta.get("download", {})
    fmt, h = d.get("hash-format"), d.get("hash", "")
    if fmt == "sha1" and d.get("mode") == "metadata:curseforge":
        return h == mod["sha1"], h == mod["sha1"]
    if jar.exists() and fmt in ("sha512", "sha256", "sha1"):
        ok = digest(jar, fmt) == h
        return ok, ok
    return True, False


# ---------- resolucio ----------

def resolve_modrinth(mods):
    """Torna {id: dict} per als mods trobats a Modrinth pel SHA-1."""
    if not mods:
        return {}
    res = http_json(MODRINTH + "/version_files", {"hashes": [m["sha1"] for m in mods], "algorithm": "sha1"})
    found = {}
    for m in mods:
        v = res.get(m["sha1"])
        if not v:
            continue
        files = [f for f in v["files"] if f["hashes"]["sha1"] == m["sha1"]]
        if not files:
            continue
        found[m["id"]] = {"project": v["project_id"], "version": v["id"], "file": files[0]}
    ids = sorted({x["project"] for x in found.values()})
    titles = {}
    if ids:
        for p in http_json(MODRINTH + "/projects?ids=" + urllib.parse.quote(json.dumps(ids))):
            titles[p["id"]] = p["title"]
    for x in found.values():
        x["title"] = titles.get(x["project"], x["file"]["filename"])
    return found


def resolve_curseforge(mods, packwiz, cache):
    """Fa servir `packwiz curseforge detect` en una carpeta temporal. Torna {id: meta parsejada}."""
    out = {}
    if not mods or not packwiz:
        return out
    m = json.loads((ROOT / "modpack.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="pwcf_") as t:
        t = pathlib.Path(t)
        base = [packwiz, "--cache", str(t / "cache"), "--config", str(t / "cfg.toml")]
        (t / "pack" / "mods").mkdir(parents=True)
        subprocess.run(base + ["init", "--name", "pk", "--version", m["version"], "--mc-version", m["minecraft"],
                               "--modloader", "neoforge", "--neoforge-version", m["neoforge"], "--author", "pk"],
                       cwd=t / "pack", check=True, capture_output=True)
        for mod in mods:
            shutil.copyfile(cache / mod["file"], t / "pack" / "mods" / mod["file"])
        subprocess.run(base + ["curseforge", "detect"], cwd=t / "pack", check=True, capture_output=True)
        by_file = {mod["file"]: mod for mod in mods}
        for p in (t / "pack" / "mods").glob("*.pw.toml"):
            meta = tomllib.loads(p.read_text(encoding="utf-8"))
            if meta["filename"] in by_file and "curseforge" in meta.get("update", {}):
                out[by_file[meta["filename"]]["id"]] = meta
    return out


# ---------- passos ----------

def step_mods(m, args, packwiz):
    cache = ROOT / "cache"
    mods_dir = PW / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    wanted = {x["id"]: x for x in m["mods"]}
    for p in mods_dir.glob("*.pw.toml"):
        if p.name[:-len(".pw.toml")] not in wanted:
            p.unlink()
            print("eliminat (ja no es a modpack.json):", p.name)
    # el jar de cache/ ha de coincidir amb la llista mestra
    for x in m["mods"]:
        j = cache / x["file"]
        if j.exists() and digest(j, "sha1") != x["sha1"]:
            sys.exit("SHA-1 diferent a cache/: " + x["file"])
    status, pending = {}, []
    for x in m["mods"]:
        p = mods_dir / (x["id"] + ".pw.toml")
        if p.exists():
            meta = tomllib.loads(p.read_text(encoding="utf-8"))
            ok, ver = check_meta(meta, x, cache / x["file"])
            if ok:
                status[x["id"]] = (kind_of(meta), ver)
                continue
        pending.append(x)
    if pending and args.offline:
        sys.exit("Sense xarxa (--offline) i falten metadades: " + ", ".join(x["id"] for x in pending))
    forced = [x for x in pending if x["id"] in FORCE_URL]
    pending = [x for x in pending if x["id"] not in FORCE_URL]
    # 1) Modrinth
    mr = resolve_modrinth(pending)
    for x in pending:
        r = mr.get(x["id"])
        if not r:
            continue
        f = r["file"]
        jar = cache / x["file"]
        ver = False
        if jar.exists():
            if digest(jar, "sha512") != f["hashes"]["sha512"]:
                sys.exit("SHA-512 de Modrinth diferent del jar de cache/: " + x["file"])
            ver = True
        write_text(mods_dir / (x["id"] + ".pw.toml"),
                   meta_modrinth(r["title"], x["file"], x["side"], f["url"], f["hashes"]["sha512"], r["project"], r["version"]))
        status[x["id"]] = ("modrinth", ver)
    pending = [x for x in pending if x["id"] not in status]
    # 2) CurseForge
    missing_jars = [x for x in pending if not (cache / x["file"]).exists()]
    if pending and not packwiz:
        print("AVIS: no hi ha packwiz; no es consulta CurseForge per a: " + ", ".join(x["id"] for x in pending))
    cf = resolve_curseforge([x for x in pending if (cache / x["file"]).exists()], packwiz, cache)
    for x in pending:
        meta = cf.get(x["id"])
        if not meta:
            continue
        d = meta["download"]
        if d["hash"] != x["sha1"]:
            print("ATENCIO: el hash de CurseForge no coincideix amb el jar de cache/ per a", x["id"])
            continue
        u = meta["update"]["curseforge"]
        write_text(mods_dir / (x["id"] + ".pw.toml"),
                   meta_curseforge(meta["name"], x["file"], x["side"], d["hash"], u["project-id"], u["file-id"]))
        status[x["id"]] = ("curseforge", True)
    pending = [x for x in pending if x["id"] not in status] + forced
    # 3) URL directa a un Release d'aquest repositori
    uploads = []
    if pending:
        repo = args.repo or repo_slug()
        for x in pending:
            jar = cache / x["file"]
            if not jar.exists():
                sys.exit("Falta el jar a cache/ per fer l'entrada per URL: " + x["file"])
            url = "https://github.com/%s/releases/download/%s/%s" % (repo, args.jars_tag, urllib.parse.quote(x["file"]))
            write_text(mods_dir / (x["id"] + ".pw.toml"), meta_url(FORCE_URL.get(x["id"], x["id"]), x["file"], x["side"], url, digest(jar, "sha256")))
            status[x["id"]] = ("url", True)
            uploads.append(x["file"])
    return status, uploads


def step_files(m):
    """Copia config/ i root_files a pw/."""
    shutil.rmtree(PW / "config", ignore_errors=True)
    excl = set(m.get("config_exclude", []))
    for p in sorted((ROOT / "config").rglob("*")):
        rel = p.relative_to(ROOT).as_posix()
        if p.is_file() and rel not in excl:
            dest = PW / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
    for name in m.get("root_files", []):
        shutil.copyfile(ROOT / "root" / name, PW / name)


def is_preserved(rel):
    return any(fnmatch.fnmatch(rel, pat) for pat in PRESERVE)


def index_files():
    out = []
    for dp, dn, fn in os.walk(PW):
        dpp = pathlib.Path(dp)
        top = dpp.relative_to(PW).parts[:1]
        if top and top[0] in IGNORE_TOP:
            dn[:] = []
            continue
        for f in fn:
            rel = (dpp / f).relative_to(PW).as_posix()
            if rel in ("pack.toml", "index.toml", ".packwizignore") or rel.split("/")[0] in IGNORE_TOP:
                continue
            out.append(rel)
    return sorted(out)


def step_index(m):
    write_text(PW / ".packwizignore", PACKWIZIGNORE)
    rows = []
    for rel in index_files():
        e = ["[[files]]", "file = " + q(rel), "hash = " + q(digest(PW / rel, "sha256"))]
        if rel.endswith(".pw.toml"):
            e.append("metafile = true")
        if is_preserved(rel):
            e.append("preserve = true")
        rows.append("\n".join(e) + "\n")
    write_text(PW / "index.toml", 'hash-format = "sha256"\n' + "".join("\n" + r for r in rows))
    pack = ("name = %s\nversion = %s\npack-format = \"packwiz:1.1.0\"\n\n[index]\nfile = \"index.toml\"\n"
            "hash-format = \"sha256\"\nhash = %s\n\n[versions]\nminecraft = %s\nneoforge = %s\n"
            % (q(m["name"]), q(m["version"]), q(digest(PW / "index.toml", "sha256")), q(m["minecraft"]), q(m["neoforge"])))
    write_text(PW / "pack.toml", pack)


def verify_with_packwiz(packwiz):
    if not packwiz:
        sys.exit("--verify necessita packwiz (--packwiz RUTA o al PATH)")
    with tempfile.TemporaryDirectory(prefix="pwv_") as t:
        t = pathlib.Path(t)
        copy = t / "pw"
        shutil.copytree(PW, copy)
        subprocess.run([packwiz, "--cache", str(t / "cache"), "--config", str(t / "cfg.toml"), "refresh"],
                       cwd=copy, check=True, capture_output=True)
        bad = [n for n in ("pack.toml", "index.toml") if (copy / n).read_bytes() != (PW / n).read_bytes()]
        if bad:
            sys.exit("`packwiz refresh` canvia: " + ", ".join(bad))
    print("verificat: `packwiz refresh` no canvia res (pack.toml i index.toml identics)")


def main():
    ap = argparse.ArgumentParser(description="Regenera pw/ a partir de modpack.json")
    ap.add_argument("--packwiz", help="ruta al binari de packwiz (si no, el del PATH)")
    ap.add_argument("--offline", action="store_true", help="no consultis Modrinth ni CurseForge")
    ap.add_argument("--verify", action="store_true", help="comprova que `packwiz refresh` no canvia pack.toml ni index.toml")
    ap.add_argument("--repo", help="PROPIETARI/REPO per a les URL de Release (per defecte, el remot origin)")
    ap.add_argument("--jars-tag", default="jars-1", help="tag del Release amb els jars sense plataforma (per defecte jars-1)")
    args = ap.parse_args()
    m = json.loads((ROOT / "modpack.json").read_text(encoding="utf-8"))
    packwiz = find_packwiz(args.packwiz)
    status, uploads = step_mods(m, args, packwiz)
    step_files(m)
    step_index(m)
    n = {}
    for k, ver in status.values():
        n[k] = n.get(k, 0) + 1
    print("mods: %d (%s); hash comparat amb el jar: %d" % (len(status), ", ".join("%s %d" % kv for kv in sorted(n.items())), sum(1 for _, v in status.values() if v)))
    files = index_files()
    print("fitxers a l'index: %d (preserve: %d, metadades de mod: %d)" % (
        len(files), sum(1 for f in files if is_preserved(f)), sum(1 for f in files if f.endswith(".pw.toml"))))
    if uploads:
        print("PUJAR al Release %s (nom exacte):" % args.jars_tag)
        for u in uploads:
            print("  " + u)
    if args.verify:
        verify_with_packwiz(packwiz)


if __name__ == "__main__":
    main()
