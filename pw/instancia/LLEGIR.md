# Plantilla d'instancia de Prism

Aquesta carpeta NO va a l'index de packwiz (`pw/.packwizignore`). Conte la part de la instancia que el pack no pot
portar: la configuracio de Prism. El zip final no es fa aqui.

## Que hi ha

- `instance.cfg`: configuracio de la instancia. `PreLaunchCommand` llança el bootstrap de packwiz abans de cada arrencada.
  `__PACK_URL__` s'ha de substituir per l'URL de `pack.toml` (vegeu mes avall).
- `mmc-pack.json`: components de la instancia: Minecraft 1.21.1 i NeoForge 21.1.206 (el que diu `modpack.json`).

## Que hi falta (no va a git)

Tots tres van dins una carpeta `minecraft/` del zip, al costat de `instance.cfg` i `mmc-pack.json`:

| Fitxer | D'on surt | Nota |
|---|---|---|
| `minecraft/packwiz-installer-bootstrap.jar` | [packwiz-installer-bootstrap v0.0.3](https://github.com/packwiz/packwiz-installer-bootstrap/releases/tag/v0.0.3) | 98989 bytes, SHA-256 `a8fbb24dc604278e97f4688e82d3d91a318b98efc08d5dbfcbcbcab6443d116c` |
| `minecraft/packwiz-installer.jar` | [packwiz-installer v0.5.14](https://github.com/packwiz/packwiz-installer/releases/tag/v0.5.14) | 4378828 bytes, SHA-256 `c9f646908d340d84773948a9a7d98bc1dae250d35e1016dc6e2b8459760b5598`. Es la versio fixada: amb `--bootstrap-no-update` el bootstrap no la canvia mai |
| `minecraft/servers.dat` | `local/servers.dat` (fora de git) | Llista de servidors inicial. Nomes va al zip d'instancia; packwiz no la toca, de manera que despres es del jugador |

## Com es fa el zip (a ma, un cop)

1. Copia `instance.cfg` i `mmc-pack.json` a una carpeta de treball i substitueix `__PACK_URL__` a `instance.cfg` per l'URL
   de `pack.toml`, per exemple `https://raw.githubusercontent.com/PROPIETARI/REPO/pw/pw/pack.toml` (branca `pw`, carpeta `pw`).
2. Crea `minecraft/` al costat i hi posa els tres fitxers de la taula.
3. Comprimeix el contingut (no la carpeta que el conte): a l'arrel del zip han de quedar `instance.cfg`, `mmc-pack.json` i `minecraft/`.
4. El jugador, a Prism: Add instance > Import from zip (o un enllaç `prismlauncher://import?url=...`).

A la primera arrencada el bootstrap descarrega tots els mods i configuracions; a les seguents nomes el que hagi canviat.

## Verificat i no verificat

El format de `instance.cfg` i `mmc-pack.json` esta contrastat amb el codi de Prism 11.1.1; el detall, i el que no s'ha pogut
provar sense Prism, es a l'informe de la tasca.
