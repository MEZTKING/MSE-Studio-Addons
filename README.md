# MSE Studio add-ons

The add-on store for **MSE Studio** (the desktop app around Magic Set Editor
for custom Magic card decks). Every copy of MSE Studio reads
[`index.json`](index.json) from here when its **Add-ons** page opens, and shows
the add-ons under **Store** – install, update, switch off or remove them with
one click.

## Installing add-ons

In MSE Studio: **Manage → Add-ons**. The store is read when the page opens (or
press **Refresh the store**). Pick an add-on → **Install**. Installed add-ons
get an **Update** button when a newer version is listed here.

## What's here

| Add-on | Kind | What it does |
|---|---|---|
| [Deck notes](addons/deck-notes) | Page | A notes page for each deck, saved as `notes.md` in the deck's folder, with a checklist of the deck's cards. |
| [MPCFill](addons/mpcfill) | Page | mpcfill.com right inside MSE Studio (opens on Explore, stays on MPCFill): pictures you download show up as cards – add them to your order or to your deck to edit – and an order (Download → XML) becomes real cards printed with the pictures you picked. |
| [Card database](addons/card-database) | Page | Every Magic card on your PC from Scryfall's bulk data: search, random cards, build a Commander deck around a commander in a play style and themes you pick (see the cards, pick some, or start a new deck with all of it), add cards as real or your own. |
| [Card prices](addons/card-prices) | Page | What a deck's real cards cost at TCGplayer and Cardmarket: cheapest printings, totals per store, the cheapest mix, in your currency. |
| [Proxy decks](addons/mpc-proxies) | Page | Proxy decks from r/mpcproxies, Ko-fi and Discord (their Google Drive) or your own PC: tick cards with a click, filter by type or by what's written on the picture (no text, no rules text), add them to your order (printed as they are, with the maker's credit) or to your deck to edit in the deck's own frame; see which cards came from which deck. |
| [Deck sharing](addons/deck-sharing) | Page | Share decks with friends through a shared OneDrive, Google Drive or Dropbox folder, or send one as a file; a friend's deck opens as a new deck of yours. |
| [Frame studio](addons/frame-studio) | Page | Make an MSE frame from pictures – a proxy maker's blank frames (also Photoshop files and Proxyshop templates: each colour put together from its layers, the text placed from its text layers) or your own, with the fonts that came with them: check where the text and art go, colours and fonts, and your cards can use it. |
| [Art only](addons/art-only) | Page | Just the art of a card for your own cards: cut out of its window, or with the frame and text painted over on full-art cards. Adds *Keep only the art* to Decklists and Proxy decks. |
| [Video capture](addons/capture) | Page | Screenshots from a video or game with a hotkey, sorted into episode folders. Came with MSE Studio until 0.15.0. |
| [Picture grabber](addons/picture-grabber) | Page | Pictures from web pages and folders, with a live mode for the biggest version of each picture. Came with MSE Studio until 0.15.0. |
| [Dragon cards](addons/dragon-cards) | Card list | Twelve dragon ideas in every colour, with a dragon commander. |
| [Anime archetypes](addons/anime-archetypes) | Card list | The hero, the rival, the mentor, the mascot, the sealed evil… as cards. |
| [Gear and auras](addons/gear-and-auras) | Card list | Equipment and Auras for Voltron decks. |
| [Anime upscaling models](addons/anime-upscaling-models) | Upscaling models | Real-ESRGAN AnimeVideo v3 (2×/3×/4×) and 4xHFA2k. |
| [NMKD upscaling models](addons/nmkd-upscaling-models) | Upscaling models | NMKD Siax and NMKD Superscale. |
| [Fast upscaling models](addons/fast-upscaling-models) | Upscaling models | Real-ESRGAN General v3 and 4xLSDIRCompactC3 – quick, for big batches. |
| [Photo and restoration models](addons/photo-upscaling-models) | Upscaling models | 4xNomos8kSC, 4xLSDIR, 4xLSDIRplusC, Uniscale Restore, "Unknown". |

Card lists show up in MSE Studio's **Card ideas → Example cards**; upscaling
models in the **Upscale** page's model list (Upscayl's own stays the default).

## Three sorts of add-on

| Sort | `kind` | Runs code? | Template |
|---|---|---|---|
| **Page** – a new page in MSE Studio's side rail (Python + PySide6) | `page` | Yes, inside MSE Studio | [templates/page-addon](templates/page-addon) |
| **Card list** – example cards for Card ideas (JSON) | `cards` | No | [templates/card-list-addon](templates/card-list-addon) |
| **Program** – game engines and tools MSE Studio starts | `game-engine`, `tool`, … | Yes, as its own program | [templates/program-addon](templates/program-addon) |
| **Upscaling models** – extra models for Upscayl | `models` | No | see the anime-upscaling-models add-on |

The full `addon.json` reference is in MSE Studio's
[ADDONS.md](ADDONS.md) (the same guide as in MSE Studio).

## Adding an add-on (or a new version)

1. Copy a template to **`addons/<id>/`** – the folder name is the add-on's `id`.
2. Fill in `addon.json` (`version` like `1.0.0`, `min_app_version` = the oldest
   MSE Studio it works with).
3. Test it: zip the folder and use **Add-ons → Install from file…** in MSE Studio.
4. Commit and push to `main`.

The **Publish add-ons** action then does the rest: it checks every
`addon.json`, zips each version that hasn't been released yet, attaches it to a
release called `<id>-v<version>`, and rewrites `index.json` with the download
link. Everyone's store shows it the next time their Add-ons page opens.

**New version:** change the files, raise `version` in `addon.json`, push. The
old releases stay, so nothing breaks for anyone.

**Download counts** in the store come from the releases; the action refreshes
them once a day.

## Add-ons kept somewhere else

Big programs (game engines) live in their own repository and attach their zip
to their own releases. List them in [`external.json`](external.json) – the same
fields as `addon.json` plus `"download": "https://…zip"`. The action checks them
and adds them to `index.json`.

## Add-ons from other people

Open a pull request that adds `addons/<id>/` (or an `external.json` entry). The
**Check add-ons** action checks it. Before merging an add-on that runs code
(pages and programs), read [CONTRIBUTING.md](CONTRIBUTING.md) – MSE Studio tells
people that store add-ons are checked.

## Layout

```
addons/<id>/            one folder per add-on (what gets zipped)
templates/              starting points for the three sorts
external.json           add-ons hosted elsewhere
index.json              written by the action – don't edit by hand
ADDONS.md               the full add-on guide (addon.json, pages, card lists, programs)
CLAUDE.md               notes for working on add-ons with Claude (API, rules, testing)
plans/                  ideas for future add-ons (not published), e.g. Frame studio
tools/build_index.py    the checker / publisher (python tools/build_index.py --check)
```

`python tools/build_index.py --local` builds the zips and an `index.json` with
file links in `dist/` – add that file's address under **Add-ons → Lists…** in
MSE Studio to try a whole store locally.
