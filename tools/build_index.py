"""Builds index.json, the list every copy of MSE Studio reads for its
add-on store.

For each folder in addons/ it checks addon.json, makes a release with the
zipped add-on when that version hasn't been released yet, and writes the
entry with its download link and how many times it was downloaded. Entries
in external.json (add-ons hosted somewhere else) are checked and added too.

    python tools/build_index.py           # what the GitHub Action runs
    python tools/build_index.py --check   # only check (pull requests)
    python tools/build_index.py --local   # zips into dist/, file links, no GitHub
    python tools/build_index.py --private # a private copy of this store: links MSE
                                          # Studio reads with its owner's GitHub token
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
KINDS = {"game-engine", "tool", "page", "cards", "models", "exporter", "art", "formats",
         "click-areas", "templates", "characters", "other"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SECTIONS = {"Create", "Produce", "Review", "Manage"}
FIELDS = ["id", "name", "version", "kind", "description", "author", "homepage", "license",
          "min_app_version", "tags", "screenshots", "run", "page", "cards", "formats",
          "click_areas", "templates", "characters"]
SKIP = {"__pycache__", ".DS_Store", "Thumbs.db"}


class Problem(Exception):
    pass


def check(addon: dict, folder: Path | None) -> list[str]:
    """What's wrong with an addon.json (empty = fine)."""
    out = []
    aid = str(addon.get("id", ""))
    if not ID_RE.match(aid):
        out.append(f"id {aid!r}: lowercase letters, digits, - _ . only")
    if folder is not None and aid != folder.name:
        out.append(f"id {aid!r} must be the folder's name ({folder.name})")
    if not str(addon.get("name", "")).strip():
        out.append("needs a name")
    if not VERSION_RE.match(str(addon.get("version", ""))):
        out.append(f"version {addon.get('version')!r} must look like 1.2.3")
    if addon.get("min_app_version") and not VERSION_RE.match(str(addon["min_app_version"])):
        out.append("min_app_version must look like 0.11.0")
    kind = addon.get("kind", "tool")
    if kind not in KINDS:
        out.append(f"kind {kind!r} must be one of {', '.join(sorted(KINDS))}")
    if not str(addon.get("description", "")).strip():
        out.append("needs a description")
    for key in ("tags", "screenshots", "cards", "formats", "click_areas", "templates",
                "characters"):
        if key in addon and not isinstance(addon[key], list):
            out.append(f"{key} must be a list")
    if kind == "page":
        page = addon.get("page") or {}
        if not page.get("module") or not page.get("class"):
            out.append("a page add-on needs page.module and page.class")
        elif str(page["module"]).startswith("mse_studio."):
            out.append("page.module must be a file of the add-on")
        elif folder is not None and not (folder / (page["module"].replace(".", "/") + ".py")).exists():
            out.append(f"{page['module']}.py is missing")
        if page.get("section", "Manage") not in SECTIONS:
            out.append(f"page.section must be one of {', '.join(sorted(SECTIONS))}")
        if "order" in page and (not isinstance(page["order"], int) or isinstance(page["order"], bool)):
            out.append("page.order must be a whole number (lower = higher up in its section)")
    if kind == "cards" and not addon.get("cards"):
        out.append("a card list add-on needs \"cards\": [\"lists/….json\"]")
    for rel in addon.get("cards") or []:
        if folder is None:
            continue
        f = folder / rel
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            cards = data.get("cards")
            if not isinstance(cards, list) or not cards:
                out.append(f"{rel}: needs a non-empty \"cards\" list")
            elif any(not isinstance(c, dict) or not str(c.get("name", "")).strip() for c in cards):
                out.append(f"{rel}: every card needs a name")
        except (OSError, ValueError) as e:
            out.append(f"{rel}: {e}")
    if kind == "formats" and not addon.get("formats"):
        out.append("a formats add-on needs \"formats\": [\"formats/….json\"]")
    if kind == "click-areas" and not addon.get("click_areas"):
        out.append("a click-areas add-on needs \"click_areas\": [\"click_areas.json\"]")
    if kind == "templates" and not addon.get("templates"):
        out.append("a templates add-on needs \"templates\": [\"templates.txt\"]")
    for rel in addon.get("templates") or []:
        if folder is None:
            continue
        try:
            lines = (folder / rel).read_text(encoding="utf-8").splitlines()
        except OSError as e:
            out.append(f"{rel}: {e}")
            continue
        rows = [ln for ln in lines if ln.strip() and not ln.strip().startswith(("#", "["))]
        bad = [ln for ln in rows if ln.count("|") < 2 or not ln.split("|", 2)[2].strip()]
        if not rows or bad:
            out.append(f"{rel}: every line needs colours | card types | text"
                       + (f" (not: {bad[0][:60]})" if bad else ""))
    if kind == "characters" and not addon.get("characters"):
        out.append("a characters add-on needs \"characters\": [\"characters.json\"]")
    for rel in addon.get("characters") or []:
        if folder is None:
            continue
        try:
            data = json.loads((folder / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append(f"{rel}: {e}")
            continue
        chars = data.get("characters", [data]) if isinstance(data, dict) else data
        if not isinstance(chars, list) or not chars or any(
                not isinstance(c, dict) or not str(c.get("name", "")).strip() for c in chars):
            out.append(f"{rel}: {{\"characters\": [{{\"name\", \"story\", …}}]}} expected")
    for rel in addon.get("click_areas") or []:
        if folder is None:
            continue
        try:
            data = json.loads((folder / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append(f"{rel}: {e}")
            continue
        bad = [k for k, v in (data.items() if isinstance(data, dict) else [("", None)])
               if not isinstance(v, dict) or any(
                   b is not None and not (isinstance(b, list) and len(b) == 4)
                   for b in v.values())]
        if bad:
            out.append(f"{rel}: {{frame: {{field: [x, y, w, h] or null}}}} expected")
    builtin = {"commander", "brawl", "standardbrawl", "oathbreaker", "paupercommander",
               "standard", "pioneer", "modern", "legacy", "vintage", "pauper", "casual",
               "limited"}
    for rel in addon.get("formats") or []:
        if folder is None:
            continue
        try:
            data = json.loads((folder / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append(f"{rel}: {e}")
            continue
        for fm in data if isinstance(data, list) else [data]:
            if not isinstance(fm, dict) or not str(fm.get("name", "")).strip():
                out.append(f"{rel}: every format needs a name")
            elif str(fm.get("key", "")).lower() in builtin:
                out.append(f"{rel}: {fm['key']} is one of MSE Studio's own formats")
            elif not isinstance(fm.get("size", 60), int) or not isinstance(fm.get("copies", 4), int):
                out.append(f"{rel}: size and copies must be whole numbers")
    run = addon.get("run") or {}
    if kind in ("game-engine", "tool", "exporter") and not run.get("windows") and folder is not None:
        out.append("a program add-on needs run.windows")
    fetch = addon.get("fetch") or []
    if not isinstance(fetch, list):
        out.append("fetch must be a list")
        fetch = []
    for f in fetch:
        path = str((f or {}).get("path", ""))
        if not str(f.get("url", "")).startswith("https://"):
            out.append(f"fetch {path or '?'}: needs a https:// url")
        if not SHA256_RE.match(str(f.get("sha256", ""))):
            out.append(f"fetch {path or '?'}: needs the file's sha256")
        if not path or path.startswith(("/", "\\")) or ".." in Path(path).parts:
            out.append(f"fetch {path or '?'}: path must be inside the add-on")
        if "extract" in f and not str(f.get("extract") or "").strip():
            out.append(f"fetch {path or '?'}: extract names the file to take out of the zip")
    if kind == "models":
        files = {str(f.get("path", "")) for f in fetch}
        if folder is not None:
            files |= {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
        params = {f[:-6] for f in files if f.endswith(".param")}
        if not params:
            out.append("a models add-on needs .param + .bin files (in the folder or in fetch)")
        for m in sorted(params):
            if f"{m}.bin" not in files:
                out.append(f"{m}.param has no {Path(m).name}.bin")
    return out


def fetched(f: dict) -> bytes:
    """A file named in "fetch": downloaded once (kept in dist/.fetch) and
    checked against its sha256, so a changed file is never published. With
    "extract", the download is a zip (its sha256 is checked) and the file of
    that name in it is what goes into the add-on (a program released only as
    a zip)."""
    cache = ROOT / "dist" / ".fetch" / f["sha256"]
    if cache.exists():
        data = cache.read_bytes()
    else:
        req = urllib.request.Request(f["url"], headers={"User-Agent": "MSE-Studio-Addons"})
        with urllib.request.urlopen(req, timeout=600) as r:
            data = r.read()
    got = hashlib.sha256(data).hexdigest()
    if got != f["sha256"]:
        raise Problem(f"{f['url']} isn't the file it should be (sha256 differs: it's {got})")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)
    member = str(f.get("extract") or "").strip()
    if not member:
        return data
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        found = [n for n in names if n == member] or \
            [n for n in names if n.rsplit("/", 1)[-1] == member.rsplit("/", 1)[-1]]
        if len(found) != 1:
            raise Problem(f"{f['url']}: {member} isn't in the zip (it has {', '.join(names[:10])})")
        return z.read(found[0])


def zip_addon(folder: Path, out: Path, addon: dict | None = None) -> Path:
    """The add-on's folder as a zip, plus the files its "fetch" list names
    (big files such as upscaling models aren't kept in this repository)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.rglob("*")):
            if f.is_file() and not (set(f.relative_to(folder).parts) & SKIP) and f.suffix != ".pyc":
                z.write(f, f"{folder.name}/{f.relative_to(folder).as_posix()}")
        for f in (addon or {}).get("fetch") or []:
            z.writestr(f"{folder.name}/{f['path']}", fetched(f), zipfile.ZIP_STORED
                       if f["path"].endswith(".bin") else zipfile.ZIP_DEFLATED)
    return out


def gh(*args: str, check_ok: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check_ok)


def release_assets(repo: str, private: bool = False) -> list[tuple[str, str, int, str, str]]:
    """Every release's zips: (tag, asset name, downloads, link, date). ``private``:
    the link is the file's API address – the one a token can read in a private
    repository."""
    link = ".url" if private else ".browser_download_url"
    r = gh("api", f"repos/{repo}/releases", "--paginate", "--jq",
           ".[] | .tag_name as $t | .published_at as $p | .assets[] | "
           f"[$t, .name, .download_count, {link}, ($p // \"\")] | @tsv")
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 4:
            tag, name, n, url = parts[:4]
            out.append((tag, name, int(n or 0), url, parts[4] if len(parts) > 4 else ""))
    return out


def download_counts(repo: str, assets: list | None = None) -> dict[str, int]:
    """Downloads per release asset name, over all releases."""
    counts: dict[str, int] = {}
    for _tag, name, n, _url, _date in (release_assets(repo) if assets is None else assets):
        counts[name] = counts.get(name, 0) + n
    return counts


def _vkey(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def versions_of(addon_id: str, assets: list) -> list[dict]:
    """Every released version of an add-on, newest first – MSE Studio's
    Add-ons page offers them (Other versions…)."""
    found = {}
    tag_re = re.compile(rf"^{re.escape(addon_id)}-v(\d+\.\d+\.\d+)$")
    for tag, name, _n, url, date in assets:
        m = tag_re.match(tag)
        if m and name.endswith(".zip") and m.group(1) not in found:
            found[m.group(1)] = {"version": m.group(1), "download": url, "date": date[:10]}
    return sorted(found.values(), key=lambda v: _vkey(v["version"]), reverse=True)


def entry(addon: dict, download: str, downloads: int = 0,
          versions: list | None = None) -> dict:
    e = {k: addon[k] for k in FIELDS if k in addon and addon[k] not in ("", [], {}, None)}
    e["download"] = download
    if downloads:
        e["downloads"] = downloads
    if versions:
        e["versions"] = versions
    return e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only check the add-ons")
    ap.add_argument("--local", action="store_true", help="zip into dist/ with file links")
    ap.add_argument("--private", action="store_true",
                    help="a private store: links read with the owner's GitHub token")
    args = ap.parse_args()
    repo = os.environ.get("REPO") or os.environ.get("GITHUB_REPOSITORY", "MEZTKING/MSE-Studio-Addons")
    problems: list[str] = []
    found: list[tuple[dict, Path]] = []
    for folder in sorted(p for p in (ROOT / "addons").iterdir() if p.is_dir()):
        try:
            addon = json.loads((folder / "addon.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            problems.append(f"addons/{folder.name}: addon.json: {e}")
            continue
        problems += [f"addons/{folder.name}: {p}" for p in check(addon, folder)]
        found.append((addon, folder))
    external = []
    ext_file = ROOT / "external.json"
    if ext_file.exists():
        for addon in json.loads(ext_file.read_text(encoding="utf-8")).get("addons", []):
            errs = check(addon, None)
            if not str(addon.get("download", "")).startswith("https://"):
                errs.append("needs a https:// download link")
            problems += [f"external.json {addon.get('id')}: {p}" for p in errs]
            external.append(addon)
    ids = [a["id"] for a, _f in found] + [a.get("id") for a in external]
    problems += [f"{i} is listed twice" for i in sorted({i for i in ids if ids.count(i) > 1})]
    if problems:
        print("Problems:\n  " + "\n  ".join(problems))
        return 1
    print(f"{len(found)} add-on(s) here and {len(external)} elsewhere look fine.")
    if args.check:
        return 0
    entries = []
    assets = [] if args.local else release_assets(repo, args.private)
    counts = download_counts(repo, assets)
    for addon, folder in found:
        name = f"{addon['id']}-{addon['version']}.zip"
        tag = f"{addon['id']}-v{addon['version']}"
        if args.local:
            z = zip_addon(folder, ROOT / "dist" / name, addon)
            entries.append(entry(addon, z.resolve().as_uri()))
            continue
        if gh("release", "view", tag, "--repo", repo, check_ok=False).returncode != 0:
            z = zip_addon(folder, ROOT / "dist" / name, addon)
            gh("release", "create", tag, str(z), "--repo", repo,
               "--title", f"{addon['name']} {addon['version']}",
               "--notes", addon.get("description", ""))
            print(f"released {tag}")
        link = f"https://github.com/{repo}/releases/download/{tag}/{name}"
        if args.private:            # the file's API address (a token can read it)
            link = next((u for t, n, _c, u, _d in release_assets(repo, True)
                         if t == tag and n == name), link)
        total = sum(n for asset, n in counts.items() if asset.startswith(f"{addon['id']}-")
                    and asset.endswith(".zip"))
        versions = versions_of(addon["id"], assets)
        if addon["version"] not in {v["version"] for v in versions}:     # released just now
            versions.insert(0, {"version": addon["version"], "download": link,
                                "date": __import__("datetime").date.today().isoformat()})
        entries.append(entry(addon, link, total, versions))
    entries += [entry(a, a["download"], int(a.get("downloads") or 0)) for a in external]
    entries.sort(key=lambda e: e["name"].lower())
    if args.private:
        for e in entries:
            e["private"] = True
    index = {"format": 1, "store": f"https://github.com/{repo}", "addons": entries}
    if args.private:
        index["private"] = True
    out = ROOT / ("dist/index.json" if args.local else "index.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} with {len(entries)} add-on(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
