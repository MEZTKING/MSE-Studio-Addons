"""Public Google Drive folders, read the way a browser shows them: the
folder's list (no Google account or API key needed – only folders shared
with "anyone with the link"), thumbnails, and full-size downloads (including
Google's "can't scan this file for viruses" step for big files).

Google has two pages that list a folder; when one is refused the other is
tried."""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Callable, Optional

# Google answers some apps' own names with "403"; it's asked like a browser
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
LIST_URL = "https://drive.google.com/embeddedfolderview?id={id}#list"
FOLDER_URL = "https://drive.google.com/drive/folders/{id}?hl=en"
THUMB_URLS = ("https://drive.google.com/thumbnail?id={id}&sz=w{w}",
              "https://lh3.googleusercontent.com/d/{id}=w{w}")
THUMB_URL = THUMB_URLS[0]
DOWNLOAD_URLS = ("https://drive.usercontent.google.com/download?id={id}&export=download&confirm=t",
                 "https://drive.google.com/uc?export=download&id={id}")
DOWNLOAD_URL = DOWNLOAD_URLS[1]
FOLDER_MIME = "application/vnd.google-apps.folder"
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
PICTURE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")
TEXT_EXT = (".txt", ".dek", ".dec")


class DriveError(RuntimeError):
    pass


def _http(url: str, timeout: float = 60) -> bytes:
    """GET (tests replace this)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*",
                                               "Accept-Language": "en"})
    with _opener.open(req, timeout=timeout) as r:      # keeps Google's cookies
        return r.read()


@dataclass
class Item:
    id: str
    name: str
    folder: bool = False
    path: str = ""                 # sub-folders it's in ("Tokens/…")
    kind: str = "drive"            # drive | file (on this PC) | zip (in a zip on this PC)

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


def _js_unescape(s: str) -> str:
    """A JavaScript string's escapes (\\x22, \\u0026, \\/…) as characters."""
    def one(m):
        e = m.group(1)
        if e[0] in "xu" and len(e) > 1:
            return chr(int(e[1:], 16))
        return {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(e, e)
    return re.sub(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.)", one, s)


def parse_folder_page(page: str) -> Optional[tuple[str, list[Item]]]:
    """(folder name, items) from the folder's own page (drive/folders/…),
    where the list is kept in a script; None when it isn't there. That page
    shows the first 50 or so files of a folder."""
    m = re.search(r"window\['_DRIVE_ivd'\]\s*=\s*'((?:[^'\\]|\\.)*)'", page)
    if not m:
        return None
    try:
        data = json.loads(_js_unescape(m.group(1)))
    except ValueError:
        return None
    t = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
    title = re.sub(r"\s*[-–]\s*Google Drive\s*$", "", html.unescape(t.group(1)).strip()) if t else ""
    items = []
    for e in (data[0] if data and isinstance(data[0], list) else []):
        if isinstance(e, list) and len(e) > 3 and isinstance(e[0], str) and isinstance(e[2], str):
            items.append(Item(e[0], e[2], e[3] == FOLDER_MIME))
    return title, items


def read_folder(fid: str, http: Optional[Callable] = None) -> tuple[str, list[Item]]:
    """(folder name, items) of one shared folder – not its sub-folders."""
    get = http or _http
    problems = []
    try:
        page = get(LIST_URL.format(id=fid)).decode("utf-8", errors="replace")
        if "flip-entry" in page or "flip-entries" in page:
            return parse_listing(page)
        problems.append("its list page was empty")
    except Exception as e:  # noqa: BLE001 - the other page is tried
        problems.append(str(e))
    try:
        page = get(FOLDER_URL.format(id=fid)).decode("utf-8", errors="replace")
        found = parse_folder_page(page)
        if found is not None:
            return found
        problems.append("its folder page had no list")
    except Exception as e:  # noqa: BLE001
        problems.append(str(e))
    raise DriveError("Google Drive didn't show the folder (" + "; ".join(problems) + "). Check "
                     "the link and that the folder is shared with \"anyone with the link\". "
                     "Or download the folder in your browser (Download all) and add the zip "
                     "with Add from this PC.")


def list_folder(fid: str, http: Optional[Callable] = None, depth: int = 3,
                progress: Optional[Callable[[str], None]] = None, cancel=None,
                _path: str = "") -> tuple[str, list[Item]]:
    """Everything in a shared folder and its sub-folders (``depth`` deep)."""
    get = http or _http
    title, items = read_folder(fid, get)
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


def thumbnail(file_id: str, width: int = 320, http: Optional[Callable] = None) -> bytes:
    """A small picture of a file (Google's thumbnail, or its picture server)."""
    get = http or _http
    last: Exception | None = None
    for url in THUMB_URLS:
        try:
            data = get(url.format(id=file_id, w=width))
            if not data[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
                return data
        except Exception as e:  # noqa: BLE001 - the next address
            last = e
    raise DriveError(f"No thumbnail ({last})")


def download(file_id: str, http: Optional[Callable] = None, timeout: float = 120) -> bytes:
    """A file at full size. Big files first show Google's virus-scan notice:
    its "download anyway" form is followed."""
    get = http or _http
    try:                                # Google's download server (skips the virus notice)
        data = get(DOWNLOAD_URLS[0].format(id=file_id))
        if not data[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
            return data
    except Exception:  # noqa: BLE001 - the older address below
        pass
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
