"""Public Google Drive folders, read the way a browser shows them: the
folder's list (no Google account or API key needed – only folders shared
with "anyone with the link"), thumbnails, and full-size downloads (including
Google's "can't scan this file for viruses" step for big files)."""
from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MSE-Studio"
LIST_URL = "https://drive.google.com/embeddedfolderview?id={id}#list"
THUMB_URL = "https://drive.google.com/thumbnail?id={id}&sz=w{w}"
DOWNLOAD_URL = "https://drive.google.com/uc?export=download&id={id}"
PICTURE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")
TEXT_EXT = (".txt", ".dek", ".dec")


class DriveError(RuntimeError):
    pass


def _http(url: str, timeout: float = 60) -> bytes:
    """GET (tests replace this)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


@dataclass
class Item:
    id: str
    name: str
    folder: bool = False
    path: str = ""                 # sub-folders it's in ("Tokens/…")

    @property
    def picture(self) -> bool:
        return not self.folder and self.name.lower().endswith(PICTURE_EXT)

    @property
    def text(self) -> bool:
        return not self.folder and self.name.lower().endswith(TEXT_EXT)


def folder_id(link: str) -> str:
    """The folder id in a Google Drive link ("" if it isn't one)."""
    link = (link or "").strip()
    m = re.search(r"drive\.google\.com/(?:drive/(?:u/\d+/)?folders/|embeddedfolderview\?id=|"
                  r"open\?id=|folderview\?id=)([\w-]{10,})", link)
    if m:
        return m.group(1)
    return link if re.fullmatch(r"[\w-]{25,}", link) else ""


def folder_link(fid: str) -> str:
    return f"https://drive.google.com/drive/folders/{fid}"


def parse_listing(page: str) -> tuple[str, list[Item]]:
    """(folder name, items) from an embeddedfolderview page."""
    m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
    title = html.unescape(m.group(1)).strip() if m else ""
    title = re.sub(r"\s*[-–]\s*Google Drive\s*$", "", title)
    items = []
    for chunk in re.split(r'<div[^>]+class="flip-entry"', page)[1:]:
        m_id = re.search(r'id="entry-([\w-]+)"', chunk)
        m_name = re.search(r'class="flip-entry-title"[^>]*>(.*?)</div>', chunk, re.S)
        if not m_id or not m_name:
            continue
        href = re.search(r'href="([^"]+)"', chunk)
        href = html.unescape(href.group(1)) if href else ""
        is_folder = "/folders/" in href or "vnd.google-apps.folder" in chunk
        items.append(Item(m_id.group(1), html.unescape(re.sub(r"<[^>]+>", "", m_name.group(1)))
                          .strip(), is_folder))
    return title, items


def list_folder(fid: str, http: Optional[Callable] = None, depth: int = 3,
                progress: Optional[Callable[[str], None]] = None, cancel=None,
                _path: str = "") -> tuple[str, list[Item]]:
    """Everything in a shared folder and its sub-folders (``depth`` deep)."""
    get = http or _http
    try:
        page = get(LIST_URL.format(id=fid)).decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        raise DriveError(f"Google Drive didn't show the folder ({e}). Check that it's shared "
                         "with \"anyone with the link\".") from e
    if "flip-entry" not in page and "flip-entries" not in page:
        raise DriveError("That Google Drive folder isn't public (or the link is wrong) – it "
                         "needs to be shared with \"anyone with the link\".")
    title, items = parse_listing(page)
    out = []
    for it in items:
        it.path = _path
        if it.folder:
            if depth > 0 and not (cancel is not None and getattr(cancel, "cancelled", False)):
                if progress:
                    progress(f"Reading {(_path + '/' if _path else '') + it.name}…")
                try:
                    _t, sub = list_folder(it.id, get, depth - 1, progress, cancel,
                                          f"{_path}/{it.name}".strip("/"))
                    out += sub
                except DriveError:
                    continue
        else:
            out.append(it)
    return title, out


def thumbnail_url(file_id: str, width: int = 320) -> str:
    return THUMB_URL.format(id=file_id, w=width)


def download(file_id: str, http: Optional[Callable] = None, timeout: float = 120) -> bytes:
    """A file at full size. Big files first show Google's virus-scan notice:
    its "download anyway" form is followed."""
    get = http or _http
    data = get(DOWNLOAD_URL.format(id=file_id))
    if data[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
        page = data.decode("utf-8", errors="replace")
        form = re.search(r'<form[^>]+id="download-form"[^>]+action="([^"]+)"(.*?)</form>',
                         page, re.S)
        if form:
            fields = dict(re.findall(r'name="(\w+)"\s+value="([^"]*)"', form.group(2)))
            url = html.unescape(form.group(1)) + "?" + urllib.parse.urlencode(fields)
        else:
            m = re.search(r'href="(/uc\?export=download[^"]+)"', page)
            if not m:
                raise DriveError("Google Drive didn't give the file (it may be private, or "
                                 "downloaded too often today – try again later).")
            url = "https://drive.google.com" + html.unescape(m.group(1))
        data = get(url)
        if data[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
            raise DriveError("Google Drive didn't give the file (downloaded too often today? "
                             "Try again later).")
    return data
