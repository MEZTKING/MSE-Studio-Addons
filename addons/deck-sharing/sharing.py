"""Decks shared between friends: a deck packed in one file (.msedeck – a zip
with the deck folder, a little note about it and a preview picture), kept in a
folder you all can see (a shared OneDrive, Google Drive or Dropbox folder) or
sent any way you like. Opening one unpacks it into your decks folder."""
from __future__ import annotations

import datetime as _dt
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from mse_studio.core import addons

ADDON_ID = "deck-sharing"
SUFFIX = ".msedeck"
FORMAT = "mse-studio-shared-deck"
SKIP_DIRS = {".cache", "__pycache__"}
SKIP_FILES = {"history.zip"}      # your undo steps stay with you
ART_DIR = "Shared art"                # art kept outside the sender's deck
PICTURES = (".png", ".jpg", ".jpeg", ".webp")


class ShareError(RuntimeError):
    pass


@dataclass
class Shared:
    path: Path
    deck: str
    by: str
    when: str                      # ISO date and time
    cards: int = 0
    note: str = ""
    renders: bool = False
    art: bool = False
    size: int = 0

    @property
    def day(self) -> str:
        return self.when[:10]


# ------------------------------------------------------------------ your settings
def _prefs_file() -> Path:
    return addons.data_dir(ADDON_ID) / "prefs.json"


def prefs() -> dict:
    try:
        return json.loads(_prefs_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_pref(key: str, value) -> None:
    p = prefs()
    p[key] = value
    _prefs_file().write_text(json.dumps(p, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ packing a deck
def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", name).strip(" .") or "deck"


def file_name(deck: str, by: str) -> str:
    return f"{_safe(deck)} – shared by {_safe(by or 'me')}{SUFFIX}"


def _art(project) -> tuple[Optional[Path], str]:
    """The deck's art folder, and where it is in the deck folder ("" when it's
    somewhere else)."""
    folder = Path(project.folder).resolve()
    root = project.config.get("art_root") or str(Path(project.folder) / "Art")
    root = Path(root)
    if not root.is_dir():
        return None, ""
    root = root.resolve()
    try:
        return root, root.relative_to(folder).as_posix()
    except ValueError:
        return root, ""


def _files(project, renders: bool, art: bool):
    """(file on disk, name in the pack) for everything that goes in."""
    folder = Path(project.folder)
    stages = {Path(project.stage_dir(k)).resolve() for k in ("exported", "upscaled", "print")}
    root, inside = _art(project)
    for dirpath, dirs, files in os.walk(folder):
        d = Path(dirpath)
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS
                   and (renders or (d / x).resolve() not in stages)
                   and (art or root is None or (d / x).resolve() != root)
                   and not (x == "drawn" and d.name == ".mse-studio")]
        for n in files:
            if n.endswith((".tmp", ".partial")) or (n in SKIP_FILES and d.name == ".mse-studio"):
                continue
            p = d / n
            yield p, "deck/" + p.relative_to(folder).as_posix()
    if art and root is not None and not inside:
        for dirpath, _dirs, files in os.walk(root):
            for n in files:
                p = Path(dirpath) / n
                yield p, "art/" + p.relative_to(root).as_posix()


def estimate(project, renders: bool, art: bool) -> int:
    total = 0
    for p, _ in _files(project, renders, art):
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def _preview(project) -> Optional[bytes]:
    """A small picture of the deck: its commander's (or first card's) export."""
    from PIL import Image
    folder = Path(project.stage_dir("exported"))
    try:
        from mse_studio.core import commander
        rows = commander.rows(project)
    except Exception:  # noqa: BLE001
        rows = []
    names = project.card_filenames()
    order = [names[r] for r in rows if r < len(names)] + list(names)
    for n in order:
        for ext in PICTURES:
            f = folder / f"{n}{ext}"
            if f.is_file():
                try:
                    with Image.open(f) as im:
                        im = im.convert("RGB")
                        im.thumbnail((360, 500))
                        buf = io.BytesIO()
                        im.save(buf, "JPEG", quality=85)
                        return buf.getvalue()
                except OSError:
                    continue
    return None


def pack(project, out: Path, by: str, note: str = "", renders: bool = False,
         art: bool = False, version: str = "",
         progress: Optional[Callable[[int, int, str], None]] = None, cancel=None) -> Path:
    """The deck in one file at ``out``."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    files = list(_files(project, renders, art))
    _root, inside = _art(project)
    tmp = out.with_name(out.name + ".partial")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.writestr("share.json", json.dumps({
                "format": FORMAT, "format_version": 1, "deck": project.name, "by": by,
                "when": _dt.datetime.now().isoformat(timespec="seconds"),
                "cards": len(project.set.cards), "note": note, "renders": renders,
                "art": art, "art_in_deck": inside if art else "",
                "made_with": version}, indent=2))
            pic = _preview(project)
            if pic:
                z.writestr("preview.jpg", pic)
            for n, (p, arc) in enumerate(files):
                if cancel is not None and getattr(cancel, "cancelled", False):
                    raise ShareError("Stopped.")
                if progress and n % 10 == 0:
                    progress(n, len(files), f"Packing {p.name}")
                kind = zipfile.ZIP_STORED if p.suffix.lower() in PICTURES + (".mse-set",) \
                    else zipfile.ZIP_DEFLATED
                try:
                    z.write(p, arc, compress_type=kind)
                except OSError:
                    pass
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()
    return out


# ------------------------------------------------------------------ reading shared decks
def read(path: Path) -> Shared:
    """What a shared deck file says about itself."""
    try:
        with zipfile.ZipFile(path) as z:
            info = json.loads(z.read("share.json").decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        raise ShareError(f"{Path(path).name} isn't a shared deck ({e}).") from None
    if info.get("format") != FORMAT:
        raise ShareError(f"{Path(path).name} isn't a shared deck.")
    return Shared(Path(path), str(info.get("deck") or Path(path).stem), str(info.get("by") or ""),
                  str(info.get("when") or ""), int(info.get("cards") or 0),
                  str(info.get("note") or ""), bool(info.get("renders")), bool(info.get("art")),
                  Path(path).stat().st_size)


def preview(path: Path) -> Optional[bytes]:
    try:
        with zipfile.ZipFile(path) as z:
            return z.read("preview.jpg")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None


def shared_in(folder: Path) -> list[Shared]:
    """The shared decks in a folder, newest first."""
    out = []
    try:
        files = [f for f in Path(folder).iterdir() if f.suffix.lower() == SUFFIX]
    except OSError:
        return []
    for f in files:
        try:
            out.append(read(f))
        except ShareError:
            continue
    return sorted(out, key=lambda s: s.when, reverse=True)


def target_for(decks_dir: Path, shared: Shared) -> Path:
    """Where a shared deck goes – a folder that isn't there yet, so nothing of
    yours is ever replaced: its name, else "<name> (from <who>)", "… 2"…"""
    base = Path(decks_dir) / _safe(shared.deck)
    if not base.exists():
        return base
    who = shared.by or "a friend"
    for n in range(1, 100):
        cand = Path(decks_dir) / _safe(f"{shared.deck} (from {who}{'' if n == 1 else f' {n}'})")
        if not cand.exists():
            return cand
    raise ShareError("Too many copies of that deck in your decks folder.")


def unpack(path: Path, target: Path) -> Path:
    """Unpack a shared deck into ``target`` – a new folder – (art that was
    kept outside the deck goes in ``target/Shared art``); returns the deck
    folder."""
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        raise ShareError(f"{target} isn't empty.")
    target.mkdir(parents=True, exist_ok=True)
    has_art = False
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = info.filename
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts or not parts or info.is_dir():
                continue                      # never outside the target
            if parts[0] == "deck":
                dst = target.joinpath(*parts[1:])
            elif parts[0] == "art":
                dst = target.joinpath(ART_DIR, *parts[1:])
                has_art = True
            else:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(dst, "wb") as out:
                out.write(src.read())
    try:
        with zipfile.ZipFile(path) as z:
            inside = str(json.loads(z.read("share.json").decode("utf-8")).get("art_in_deck") or "")
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        inside = ""
    art_dir = None
    if has_art:
        art_dir = target / ART_DIR
    elif inside and ".." not in Path(inside).parts:
        art_dir = target.joinpath(*Path(inside).parts)
    cfg = target / "project.json"
    try:                                      # the sender's art folder isn't on your PC
        data = json.loads(cfg.read_text(encoding="utf-8"))
        data["art_root"] = str(art_dir) if art_dir is not None and art_dir.is_dir() else ""
        cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except (OSError, ValueError):
        pass
    return target
