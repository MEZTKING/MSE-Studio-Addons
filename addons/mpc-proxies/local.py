"""Proxy decks on this PC: folders and zips you downloaded (a Google Drive
download is a zip like "Monster Hunter Proxies-20250809T134712Z-1-001.zip",
big ones in several parts). Nothing is extracted: pictures are read from the
folder or the zip when they're shown or added."""
from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .gdrive import PICTURE_EXT, TEXT_EXT, Item

# Google Drive's download name: "<folder>-20250809T134712Z-1-001"
STAMP = re.compile(r"-\d{8}T\d{6}Z(?:-\d+-\d{3})?$", re.I)
# folders that sort a deck's cards (not decks of their own)
SORTING = re.compile(r"^(?:artifacts?|creatures?|enchantments?|instants?|sorcer(?:y|ies)|lands?|"
                     r"planeswalkers?|battles?|tokens?|extras?|bonus|commanders?|cards?|deck|"
                     r"main(?: ?deck)?|side(?:board)?|backs?|card ?backs?|emblems?|alt(?:ernate)?s?"
                     r"(?: arts?)?|basics?|basic lands?|front|fronts|double[- ]faced|dfcs?)$", re.I)
SKIP = re.compile(r"(?:^|/)(?:__MACOSX|\.)|(?:^|/)(?:thumbs\.db|desktop\.ini)$", re.I)
MAX_DEPTH = 5


@dataclass
class LocalDeck:
    title: str
    sources: list = field(default_factory=list)     # folders and zip files (str paths)

    @property
    def key(self) -> str:
        return "local:" + "|".join(sorted(s.lower() for s in self.sources))


def deck_title(name: str) -> str:
    """"Monster Hunter Proxies" from "Monster Hunter Proxies-20250809T134712Z-1-001.zip"."""
    stem = name[:-4] if name.lower().endswith(".zip") else name
    return STAMP.sub("", stem).strip(" -_") or stem


def _pictures_inside(folder: Path, depth: int = 3) -> bool:
    try:
        for entry in os.scandir(folder):
            if entry.is_file() and entry.name.lower().endswith(PICTURE_EXT):
                return True
            if entry.is_dir() and depth > 0 and _pictures_inside(Path(entry.path), depth - 1):
                return True
    except OSError:
        return False
    return False


def is_one_deck(folder: Path) -> bool:
    """A deck's own folder (pictures, or type folders like Creature and Land)
    rather than a folder of decks."""
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return False
    if any(e.is_file() and e.name.lower().endswith(PICTURE_EXT) for e in entries):
        return True
    dirs = [e for e in entries if e.is_dir() and not SKIP.search(e.name)]
    zips = [e for e in entries if e.is_file() and e.name.lower().endswith(".zip")]
    if zips:
        return False
    return bool(dirs) and sum(bool(SORTING.match(e.name)) for e in dirs) >= max(1, len(dirs) // 2)


def scan(root: str | Path) -> list[LocalDeck]:
    """The decks in a folder: the folder itself when it's one deck, else each
    folder and zip in it (the parts of one download together; a zip that was
    also extracted next to it counts once)."""
    root = Path(root)
    if not root.exists():
        return []
    if root.is_file():
        return [LocalDeck(deck_title(root.name), [str(root)])] if root.suffix.lower() == ".zip" \
            else []
    if is_one_deck(root):
        return [LocalDeck(deck_title(root.name), [str(root)])]
    by_title: dict[str, LocalDeck] = {}
    folders: set = set()
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name.lower())
    except OSError:
        return []
    for e in entries:
        if SKIP.search(e.name):
            continue
        if e.is_dir():
            if not _pictures_inside(Path(e.path), MAX_DEPTH):
                continue
            title = deck_title(e.name)
            folders.add(title.lower())
            by_title.setdefault(title.lower(), LocalDeck(title)).sources.append(e.path)
    for e in entries:
        if e.is_file() and e.name.lower().endswith(".zip"):
            title = deck_title(e.name)
            if title.lower() in folders:          # already extracted next to it
                continue
            by_title.setdefault(title.lower(), LocalDeck(title)).sources.append(e.path)
    return sorted(by_title.values(), key=lambda d: d.title.lower())


def _wrapper(parts: list[str]) -> int:
    """How many leading folders every file shares (a zip's "Deck name/" folder)."""
    if not parts:
        return 0
    first = parts[0].split("/")[:-1]
    n = 0
    for i, name in enumerate(first):
        if SORTING.match(name):                   # "Creature/" is the cards' type: kept
            break
        if all(p.split("/")[:-1][i:i + 1] == [name] for p in parts):
            n = i + 1
        else:
            break
    return n


def _item(kind: str, ident: str, rel: str) -> Item:
    folders = rel.split("/")[:-1]
    return Item(ident, rel.split("/")[-1], False, "/".join(folders), kind)


def list_items(sources: list[str], cancel=None) -> list[Item]:
    """Every picture and text file of a deck (its folders and zips)."""
    out: list[Item] = []
    for src in sources:
        p = Path(src)
        if cancel is not None and getattr(cancel, "cancelled", False):
            break
        if p.is_dir():
            rels = []
            for folder, dirs, files in os.walk(p):
                depth = len(Path(folder).relative_to(p).parts)
                dirs[:] = [d for d in dirs if not SKIP.search(d)] if depth < MAX_DEPTH else []
                for f in files:
                    rel = str(Path(folder, f).relative_to(p)).replace(os.sep, "/")
                    if not SKIP.search(rel) and f.lower().endswith(PICTURE_EXT + TEXT_EXT):
                        rels.append(rel)
            cut = _wrapper(rels)
            for rel in sorted(rels, key=str.lower):
                out.append(_item("file", str(p / rel), "/".join(rel.split("/")[cut:])))
        elif p.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(p) as z:
                    names = [n for n in z.namelist() if not n.endswith("/") and not SKIP.search(n)
                             and n.lower().endswith(PICTURE_EXT + TEXT_EXT)]
            except (OSError, zipfile.BadZipFile):
                continue
            cut = _wrapper(names)
            for n in sorted(names, key=str.lower):
                out.append(_item("zip", f"{p}::{n}", "/".join(n.split("/")[cut:])))
    return out


def read(item: Item) -> bytes:
    """A local picture or text file's bytes."""
    if item.kind == "zip":
        zpath, member = item.id.split("::", 1)
        with zipfile.ZipFile(zpath) as z:
            return z.read(member)
    return Path(item.id).read_bytes()


def stamp(item: Item) -> str:
    """Changes when the file does (for the thumbnail cache)."""
    path = item.id.split("::", 1)[0]
    try:
        st = os.stat(path)
        return f"{st.st_mtime_ns}-{st.st_size}"
    except OSError:
        return "0"
