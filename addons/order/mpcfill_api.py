"""MPCFill: print-ready card pictures from the community's drives, for the
deck's real cards (MSE Studio asks this add-on before Scryfall).

MPCFill's web page (mpcfill.com) is only a page: it talks to a *server* that
searches the pictures, and full-size pictures come from an *image server*.
The addresses of both are written into the page's scripts, so they can be
found from the page itself (``discover``), or given by hand (MPCFill… on the
Order page).

Everything here only asks for data – the names of your real cards go to your
MPCFill server when their pictures are got, nothing is uploaded.
(Until MSE Studio 0.25 this was mse_studio.core.mpcfill.)"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

from mse_studio import __version__

SITE = "https://mpcfill.com"
PAGE_SIZE = 60                     # results per page (MPCFill allows up to 100)
CARD_TYPES = ("CARD", "CARDBACK", "TOKEN")
SORTS = {"nameAscending": "Name A–Z", "nameDescending": "Name Z–A",
         "dateCreatedDescending": "Newest first", "dateCreatedAscending": "Oldest first",
         "dateModifiedDescending": "Recently changed"}
_PUNCT = re.compile(r"""[~`!@#$%^&*(){}\[\];:"'’<,.>?/\\|_+=]""")
_URL = re.compile(r"""https?://[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}(?::\d+)?(?:/[A-Za-z0-9._~/-]*)?""")
# addresses in the page's scripts that are never MPCFill's servers
_NOT_SERVERS = re.compile(
    r"(makeplayingcards|printerstudio|github|google(?!usercontent)|gstatic|sentry|buymeacoffee|"
    r"patreon|discord|w3\.org|reactjs|react\.dev|nextjs|vercel|schema\.org|mozilla|"
    r"cloudflareinsights|jsdelivr|unpkg|bootstrap|scryfall|wizards|mtgjson|reddit|twitter|"
    r"youtube|ko-fi|paypal|elastic\.co|fb\.me|stackoverflow|npmjs|example\.com|localhost)", re.I)


class MpcfillError(RuntimeError):
    pass


# ------------------------------------------------------------------ network
def _http(url: str, data: Optional[bytes] = None, timeout: float = 60) -> bytes:
    """GET (or POST JSON ``data``). Tests replace this."""
    headers = {"User-Agent": f"MSE-Studio/{__version__}", "Accept": "*/*"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _json(url: str, body: Optional[dict] = None, timeout: float = 60):
    raw = _http(url, json.dumps(body).encode("utf-8") if body is not None else None, timeout)
    return json.loads(raw.decode("utf-8"))


def clean_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    return url if re.match(r"https?://", url, re.I) else "https://" + url


def server_from_link(text: str) -> str:
    """A server address in a shared MPCFill link (…?server=https://…), else ""."""
    q = urllib.parse.urlparse((text or "").strip()).query
    found = urllib.parse.parse_qs(q).get("server") or []
    return clean_url(found[0]) if found else ""


def query(name: str) -> str:
    """A card name the way MPCFill's search wants it (lower case, no punctuation)."""
    return " ".join(_PUNCT.sub("", (name or "").lower().strip()).split())


# ------------------------------------------------------------------ finding the servers
@dataclass
class Found:
    server: str = ""
    images: str = ""
    tried: list = field(default_factory=list)


def _is_server(url: str) -> bool:
    try:
        data = _json(f"{url}/2/info/", timeout=15)
    except Exception:  # noqa: BLE001 - not a server
        return False
    return isinstance(data, dict) and "info" in data


def _is_image_server(url: str, card_id: str) -> bool:
    try:
        data = _http(f"{url}/images/google_drive/small/{card_id}.jpg", timeout=20)
    except Exception:  # noqa: BLE001
        return False
    return data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:4] == b"RIFF"


def _candidates(text: str) -> list[str]:
    """Web addresses in a page or script that could be a server, most likely first."""
    out = []
    for u in _URL.findall(text):
        u = u.rstrip("/.")
        if _NOT_SERVERS.search(u) or re.search(r"\.(js|css|png|jpe?g|svg|ico|woff2?|json)$", u):
            continue
        if u not in out:
            out.append(u)
    # a bare host first, then hosts with a path (an API under /api…)
    return sorted(out, key=lambda u: (urllib.parse.urlparse(u).path not in ("", "/"), len(u)))


def discover(site: str = SITE, progress: Optional[Callable[[str], None]] = None,
             max_scripts: int = 80) -> Found:
    """Read MPCFill's page and its scripts for the server and the image server
    addresses, and check them. A link with ?server=… is used as it is."""
    say = progress or (lambda _m: None)
    found = Found()
    given = server_from_link(site)
    if given:
        found.server = given
    page_url = site if given or "/explore" in site else clean_url(site) + "/explore"
    say("Reading MPCFill's page…")
    try:
        page = _http(page_url, timeout=30).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        if found.server:
            return found
        raise MpcfillError(f"Couldn't open {page_url}: {e}") from None
    base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(page_url))
    scripts = re.findall(r"""<script[^>]+src=["']([^"']+\.js[^"']*)["']""", page)
    texts = [page]
    for k, src in enumerate(scripts[:max_scripts]):
        say(f"Reading MPCFill's scripts ({k + 1} of {min(len(scripts), max_scripts)})…")
        try:
            texts.append(_http(urllib.parse.urljoin(base + "/", src), timeout=30)
                         .decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001 - one script less
            continue
    cands = []
    for t in texts:
        cands += [c for c in _candidates(t) if c not in cands]
    found.tried = cands
    if not found.server:
        for c in cands:
            say(f"Trying {c}…")
            if _is_server(c):
                found.server = c
                break
    if not found.server:
        return found
    # the image server: check the candidates with a picture the server knows
    try:
        cards, _n = explore(found.server, "", page_size=1)
        card_id = cards[0]["id"] if cards else ""
    except Exception:  # noqa: BLE001
        card_id = ""
    if card_id:
        for c in cands:
            if c != found.server and _is_image_server(c, card_id):
                found.images = c
                break
    return found


# ------------------------------------------------------------------ searching
def sources(server: str) -> list[dict]:
    """MPCFill's sources (the drives), in its own order: {pk, name, key, link, about}."""
    res = _json(f"{server}/2/sources/").get("results") or {}
    out = []
    for key, src in res.items():
        if not isinstance(src, dict):
            src = {}
        try:
            pk = int(src.get("pk", key))
        except (TypeError, ValueError):
            continue
        out.append({"pk": pk, "name": src.get("name") or str(key), "key": src.get("key", ""),
                    "link": src.get("externalLink") or "", "about": src.get("description") or ""})
    return out


def search_settings(source_pks: list[int], min_dpi: int = 0, max_dpi: int = 1500,
                    languages: Optional[list] = None, exclude_tags: Optional[list] = None,
                    include_tags: Optional[list] = None, fuzzy: bool = False) -> dict:
    return {"searchTypeSettings": {"fuzzySearch": fuzzy, "filterCardbacks": False},
            "sourceSettings": {"sources": [[pk, True] for pk in source_pks]},
            "filterSettings": {"minimumDPI": int(min_dpi), "maximumDPI": int(max_dpi),
                               "maximumSize": 30, "languages": list(languages or []),
                               "includesTags": list(include_tags or []),
                               "excludesTags": list(["NSFW"] if exclude_tags is None
                                                    else exclude_tags)}}


def card_info(v: dict, key: str = "") -> dict:
    """The parts of an MPCFill card the app uses."""
    canon = v.get("canonicalCard") or {}
    artist = v.get("canonicalArtist") or {}
    return {"id": str(v.get("identifier") or key), "name": v.get("name", ""),
            "dpi": int(v.get("dpi") or 0),
            "source": v.get("sourceName") or v.get("source", ""),
            "source_id": v.get("sourceId"), "source_type": v.get("sourceType", "Google Drive"),
            "thumb": v.get("mediumThumbnailUrl") or v.get("smallThumbnailUrl", ""),
            "small": v.get("smallThumbnailUrl") or v.get("mediumThumbnailUrl", ""),
            "extension": v.get("extension", "png"), "type": v.get("cardType", "CARD"),
            "size": int(v.get("size") or 0), "language": v.get("language", ""),
            "tags": list(v.get("tags") or []), "created": v.get("dateCreated", ""),
            "set": canon.get("expansionCode", ""), "artist": artist.get("name", "")}


def explore(server: str, text: str = "", page: int = 0, page_size: int = PAGE_SIZE,
            sort: str = "nameAscending", card_types=CARD_TYPES, source_pks: Optional[list] = None,
            min_dpi: int = 0, max_dpi: int = 1500, languages: Optional[list] = None,
            exclude_tags: Optional[list] = None) -> tuple[list[dict], int]:
    """One page of MPCFill's Explore search: (cards, how many there are in all)."""
    if source_pks is None:
        source_pks = [s["pk"] for s in sources(server)]
    body = {"cardTypes": list(card_types), "pageSize": int(page_size),
            "pageStart": int(page) * int(page_size), "sortBy": sort,
            "query": query(text) or None,
            "searchSettings": search_settings(source_pks, min_dpi, max_dpi, languages,
                                              exclude_tags)}
    res = _json(f"{server}/2/exploreSearch/", body)
    cards = [card_info(c) for c in res.get("cards") or [] if isinstance(c, dict)]
    return cards, int(res.get("count") or len(cards))


# ------------------------------------------------------------------ full-size pictures
def drive_url(drive_id: str) -> str:
    return f"https://drive.usercontent.google.com/download?id={drive_id}&export=download&confirm=t"


def image_urls(card_id: str, images: str = "", thumb: str = "", dpi: int = 1200) -> list[str]:
    """Where to get a picture full size, best first: MPCFill's image server,
    then Google Drive itself (for drives that share their files)."""
    out = []
    if images:
        out.append(f"{clean_url(images)}/images/google_drive/full/{card_id}.jpg?"
                   f"dpi={int(dpi)}&jpgQuality=100")
    out.append(drive_url(card_id))
    return out


def is_picture(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or \
        (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def download(card_id: str, images: str = "", timeout: float = 120,
             http: Optional[Callable] = None) -> bytes:
    """A picture full size (raises MpcfillError when none of the places has it)."""
    get = http or _http
    last = ""
    for url in image_urls(card_id, images):
        try:
            data = get(url, timeout=timeout)
        except Exception as e:  # noqa: BLE001 - try the next place
            last = str(e)
            continue
        if is_picture(data):
            return data
        last = "the answer wasn't a picture (the drive may not share it, or it's busy)"
    raise MpcfillError(f"Couldn't get the picture: {last}. "
                       f"{'' if images else 'Set the image server (MPCFill settings) – '}"
                       f"or try again later.")


# ------------------------------------------------------------------ real cards' pictures
SEARCH_BATCH = 100
KEEP_CHOICES = 8


def server_url(server: str) -> str:
    """The MPCFill server to ask, or "" when none is set (mpcfill.com itself is
    only the web page, not a server)."""
    url = (server or "").strip().rstrip("/")
    if not url or re.fullmatch(r"(https?://)?(www\.)?mpcfill\.com", url, re.I):
        return ""
    return clean_url(url)


def server_problem(server: str, e: Exception) -> str:
    text = str(e)
    if "404" in text:
        return (f"{server} isn't an MPCFill server (it answered \"not found\") – check it: "
                f"Order page → MPCFill…")
    return f"The MPCFill server {server} didn't answer ({text[:120]})"


def search(names: list[str], server: str, cancel=None) -> dict[str, list[str]]:
    """Picture ids per card name, best first ([] for names MPCFill doesn't have)."""
    settings = search_settings([s["pk"] for s in sources(server)])
    names = list(dict.fromkeys(n for n in names if n))
    out: dict[str, list[str]] = {}
    for i in range(0, len(names), SEARCH_BATCH):
        if cancel is not None and getattr(cancel, "cancelled", False):
            break
        chunk = names[i:i + SEARCH_BATCH]
        body = {"queries": {str(k): {"query": query(n), "cardType": "CARD"}
                            for k, n in enumerate(chunk)},
                "searchSettings": settings}
        res = _json(f"{server}/3/editorSearch/", body).get("results") or {}
        for k, n in enumerate(chunk):
            out[n] = [str(x) for x in res.get(str(k)) or []]
    return out


def details(ids: list[str], server: str) -> dict[str, dict]:
    """What MPCFill knows about pictures: {id: choice} as MSE Studio keeps them
    with the card ({"id", "name", "dpi", "source", "thumb", "extension"})."""
    out: dict[str, dict] = {}
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 500):
        res = _json(f"{server}/2/cards/", {"cardIdentifiers": ids[i:i + 500]}).get("results") or {}
        for k, v in res.items():
            if isinstance(v, dict):
                out[k] = {"id": k, "name": v.get("name", ""), "dpi": int(v.get("dpi") or 0),
                          "source": v.get("sourceName") or v.get("source", ""),
                          "thumb": v.get("mediumThumbnailUrl") or v.get("smallThumbnailUrl", ""),
                          "extension": v.get("extension", "png")}
    return out


def find(names: list[str], server: str, cancel=None) -> dict[str, list[dict]]:
    """The pictures MPCFill has of each card name, best first."""
    server = server_url(server)
    if not server:
        return {}
    from mse_studio.pipeline.common import Cancelled
    try:
        hits = search(names, server, cancel)
        info = details([i for ids in hits.values() for i in ids[:KEEP_CHOICES]], server)
    except Cancelled:
        raise
    except Exception as e:  # noqa: BLE001 - said once, Scryfall's pictures are used
        raise MpcfillError(server_problem(server, e)) from None
    return {n: [info[i] for i in ids if i in info][:KEEP_CHOICES] for n, ids in hits.items()}


def make_source(get_servers: Callable[[], dict]):
    """MSE Studio's picture source for real cards: MPCFill. ``get_servers()``
    → {"server", "images"} as they're set now (read on a worker thread: a
    plain dict, no widgets)."""
    from mse_studio.pipeline import real_cards as rc

    def ready() -> str:
        return "" if server_url(get_servers().get("server", "")) else \
            "set up its server first: Order page → MPCFill…"

    return rc.PictureSource(
        key=rc.MPCFILL, label="MPCFill",
        find=lambda names, cancel=None: find(names, get_servers().get("server", ""), cancel),
        fetch=lambda pick, timeout=120: download(pick, get_servers().get("images", ""), timeout),
        ready=ready)
