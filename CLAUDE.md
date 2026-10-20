# Working on MSE Studio add-ons

This repository is the add-on **store** for MSE Studio (a PySide6 desktop app
around Magic Set Editor 2.5.7 for custom Magic: The Gathering Commander decks:
MSE draws the cards → Upscayl enlarges them → they're printed through
MakePlayingCards). Every copy of MSE Studio reads `index.json` from `main`.

MSE Studio itself lives in the private repository **MEZTKING/MSE**. Its code
is the API add-ons use; read it (`mse_studio/core`, `mse_studio/pipeline`,
`mse_studio/gui`) when an add-on needs something from it. The full add-on
guide is [ADDONS.md](ADDONS.md) (a copy of `docs/ADDONS.md` there; keep the
two the same).

## Ground rules

- **Pushing to `main` publishes.** The *Publish add-ons* action zips every
  add-on version that has no release yet, makes the release
  `<id>-v<version>` and rewrites `index.json`, so everyone's store has it
  within minutes. **The owner wants store changes published straight to
  `main` – don't ask first.** Develop on a branch if you like, check it
  (`build_index.py --check`, a smoke test), then merge it into `main` and
  push. Add-ons that need an MSE Studio that isn't out yet still go out:
  their `min_app_version` keeps older copies from installing them.
- **Raise `version`** in `addon.json` whenever anything in `addons/<id>/`
  changes. The same version is never zipped again, so a change without a new
  version never reaches anyone.
- **Never edit `index.json` by hand** – it's written by `tools/build_index.py`.
  Add-ons hosted elsewhere go in `external.json`.
- **`min_app_version`** = the oldest MSE Studio that has everything the add-on
  uses. Raise it when the add-on starts using something new from MSE Studio.
- Run `python tools/build_index.py --check` before pushing.
- Page and program add-ons run code on people's computers, and MSE Studio tells
  them store add-ons were checked. Every change to one must pass the checklist
  in [CONTRIBUTING.md](CONTRIBUTING.md): no hidden network calls, no files
  outside the deck / add-on / its data folder / what the user picked (MSE's
  data folder and fonts only through MSE Studio's installers), no `eval`/`exec`, no
  downloading code, no touching MSE Studio's settings (API keys live there).
- Card lists: the authors' own wording – no real cards' text or art.
- Commits have no attribution lines (no Co-Authored-By, no session links).
  No model names in commits or files.

## The three sorts

| Sort | `kind` | What | Template |
|---|---|---|---|
| Page | `page` | A page in MSE Studio's side rail (Python + PySide6), runs inside MSE Studio | `templates/page-addon` |
| Card list | `cards` | Example cards (JSON) for *Card ideas → Example cards* | `templates/card-list-addon` |
| Program | `game-engine`, `tool`, `exporter`, `art`, `other` | A separate program MSE Studio starts with the chosen decks' `.deck.json` files | `templates/program-addon` |
| Formats | `formats` | Deck formats (house rules) for the Deck page and New deck window: `"formats": ["formats/….json"]`, the same files as My formats → Export (needs MSE Studio 0.25.0) | `addons/more-formats` |
| Click areas | `click-areas` | Where you click to edit each field on a frame, fixed by hand: `"click_areas": ["click_areas.json"]` – what *Share…* in MSE Studio's Click areas window makes (needs MSE Studio 0.25.0) | ADDONS.md → Click area add-ons |
| Upscaling models | `models` | `.param` + `.bin` model pairs for Upscayl in a `models` folder, offered on the Upscale page (needs MSE Studio 0.12.1) | `addons/anime-upscaling-models` |
| Ability templates | `templates` | Ability wordings for the Templates… window: `"templates": ["templates.txt"]`, MSE Studio's template format – what *Share → My templates as an add-on…* makes (needs MSE Studio 0.25.0) | ADDONS.md → Ability template add-ons |
| Characters | `characters` | Characters' stories and picked abilities for Cards → *From a story…*: `"characters": ["characters.json"]` – what *Share → This character as an add-on…* makes (needs MSE Studio 0.25.0) | ADDONS.md → Character add-ons |

Big files (models, programs) aren't committed: list them in `fetch` (`path`,
`url` pinned to a commit or release tag, `sha256`) and `tools/build_index.py`
downloads and checks them when it builds the zip. A file released only inside
a zip: `"extract": "<file name>"` (the zip's sha256 is checked, that file goes
into the add-on). Credit model authors in the add-on's
README.

**Playtest** was MSE Studio's own page until 0.25: MSE Studio's tests install
it – and Card database, More example cards, More formats and Paint studio –
from this repository (its build checks out `main`), so a change to them must
keep MSE Studio's tests passing – run them with the app's
source next to this repository (`python -m pytest` there finds it, or set
`MSE_STUDIO_ADDONS`).

The folder name under `addons/` is the add-on's `id`.

## Page add-ons

```json
"page": {"module": "my_page", "class": "MyPage", "title": "My page",
         "icon": "extension", "section": "Create", "order": 60,
         "tooltip": "What it does, in a few words"}
```

- `section`: `Create`, `Produce`, `Review` or `Manage`. `order` (default 50)
  sorts add-on pages within a section; MSE Studio's own use 10 (Video
  capture), 11 (Pictures), 20 (Card ideas).
- `icon`: a file name (no `.svg`) from MSE Studio's `mse_studio/resources/icons`.
- The add-on folder is loaded as the package `mse_addon_<id>`, so
  `from . import helpers` works (plain `import helpers` too). When an add-on
  is updated, its old modules are dropped and the new code is loaded.
- Pages are rebuilt (old widgets deleted) when add-ons are installed,
  switched on/off or removed – no restart.

```python
class MyPage(QWidget):
    def __init__(self, main):   # MSE Studio's main window
    def load(self):             # a deck was opened / Settings changed (optional)
    def refresh(self):          # the page was opened (optional)
    def shutdown(self):         # the deck closes / MSE Studio quits (optional)
```

What a page can use (all optional; check `main.project is None` = no deck open):

| Thing | Use |
|---|---|
| `main.project` | The open deck: `.folder`, `.name`, `.set` (the MSE set), `.config` (the deck's `project.json` dict), `.save_config()`, `.dirty = True` after changing cards |
| `main.project.set.cards` | The cards. `card.name`, `card.text("rule_text")` (plain), `card.raw(field)` (MSE markup), `card.set_text(field, text)`, `card.image`, `card.stylesheet` (its frame). Fields use MSE's names: `name`, `casting_cost`, `super_type`, `sub_type`, `rule_text`, `flavor_text`, `power`, `toughness`, `loyalty`, `rarity`, `illustrator`, `secondary_copyright` |
| `main.project.set.add_card()` / `.remove_card(card)` | Add / remove cards; then `main.cards_tab.reload(row)` |
| `main.record("What changed")` | After changing cards: a step in the deck's history (undo) |
| `decklists.add_to_project(p, entries)` + `real_cards.use_picture(p, entry, picture, side, credit)` + `main.real_pictures(entries)` | Real cards printed with a picture file, the maker's credit kept with the card (0.15.0; `main.real_pictures` is 0.25.0 – before it, `main.order_tab.real_pictures`: use `getattr(main, "real_pictures", None) or main.order_tab.real_pictures`; see the card-database add-on) |
| `main.tabs.setCurrentWidget(main.cards_tab)` + `main.cards_tab.select_row(i)` | Open a card |
| `main.settings` | Read only: `mse_path`, `upscayl_path`, theme… Never write it, never read keys or tokens from it |
| `main.known_frames()`, `mse_studio.core.styles` | The frames MSE has |
| `mse_studio.gui.nav.page_header(title, text)` | The title every page has – use it so the page looks like the others |
| `mse_studio.gui.common`: `Job`, `start`, `forget`, `error`, `info`, `confirm`, `PathEdit` | `Job(fn, label="What it does")` runs `fn(progress=…, cancel=…)` on a worker thread (with a label, Stop cancels it); `job.signals.progress(done, total, text)`, `.finished(result)`, `.failed(text)`; `start(job)`; keep jobs in a list and call `forget(jobs)` in `shutdown()` (0.13.0) |
| `mse_studio.gui.icons`: `icon(name)`, `set_icon(button, name)` | Icons that follow the theme |
| `mse_studio.gui.web_window`: `open_web(parent, url, title, on_picture=, on_download=)`, `WebPanel(parent, url, …)`, `available()` | A browser inside MSE Studio (0.16.0): right-click a picture → your `on_picture(url, page, title)`; files the site downloads → `on_download(path, page)`. Make a `WebPanel` when the page is first opened and `close_browser()` it in `shutdown()` |
| `mse_studio.pipeline.print_prep.make_print(img, spec, margin="auto")`, `has_mpc_margin(img)` | A print file; MPC's margin added only when the picture hasn't got it (0.16.0) |
| `mse_studio.gui.thumbs.cache()` / `.large()` | Picture caches at 300 px / 1400 px (`large` is 0.16.0) |
| `mse_studio.core.picture_tools.register(id, label, run, owner=self)` | A tool for card pictures, offered on the Decklists page – `run(parent, picture, info)` (0.17.0; see the art-only add-on) |
| `picture_tools.register_painter(label, run, owner=self)` | MSE Studio's *Paint this card's art* opens your add-on: `run(card, base, start_blank)` returns True when it opened (0.25.0; see paint-studio) |
| `main.decklists_tab.add_custom(entries, source, frame=, pictures=, keep_unknown=True)` | Your own cards to edit with the text, a frame and their own art, fitted like Force to fit (0.17.0) |
| `mse_packages.install_zip(zip, styles.data_dir(main.settings.mse_path))`, `remove_package(…)`, `main.frames_changed()` | Add or take out an MSE frame – the only way to change MSE's data folder (0.17.0) |
| `mse_studio.gui.common.delete_key(widget, fn)`, `ask_delete(parent, text)` | The Delete key on a list, and Settings' *Ask before deleting* (0.17.0) |
| `WebPanel(…, stay_on=("site.com",))` | A browser that doesn't leave the site (its downloads still come through) (0.18.0) |
| `mse_studio.gui.advanced.install_font_files(parent, files)`, `qt_installed_fonts()` | Install fonts that came with something, after asking – MSE is restarted for previews (`main.fonts_changed()`) (0.18.0) |
| `main.new_deck(name=…)` | The New deck window with a name; returns the new deck or None (0.18.0; see card-database) |
| `main.new_deck(name=…, format=…)`, `mse_studio.core.formats.of(main.project)` | The deck's format: `.key` ("commander", "standard"…), `.size`, `.copies`, `.has_commander`; `formats.legal_state(fmt, card)` (0.21.0; see card-database) |
| `main.run_everything(ask=False, then=fn)` | Draw, upscale and make print files without the summary; `fn()` once done (0.21.0) |
| `mse_studio.core.card_finder`: `add_finder(fn, name)`, `remove_finder(fn)`, `find(Query(...))`, `deck_query(project)` | Answer MSE Studio's real-card searches (commander ideas, real cards for a deck) offline: `fn(query)` returns card dicts or None (0.22.0; see card-database) |
| Planeswalkers | Write the rules text like the real card ("+1: …", one ability a line): MSE Studio fills the walker frame's boxes (`mse_studio.core.walkers`) (0.18.0) |
| `mse_studio.ai.for_addons`: `not_ready(s)`, `service(s)`, `ask_json(s, system, prompt, images=, schema=)`, `picture_not_ready(s)`, `make_picture(s, prompt, size=)` | AI with the service set in Settings → AI (0.25.0: Settings → Advanced → Experimental → AI) (`s` = `main.settings`; the add-on never reads keys). Only from a button, in a `Job`, saying which service (0.20.0). Guard with `try: import` for older MSE Studio |
| `mse_studio.ai.for_addons.enabled(s)` | AI switched on (Settings → Advanced → Experimental → AI; off until the user switches it on). Off: show no AI button or wording at all. Fallback for older MSE Studio: `getattr(ai, "enabled", lambda s: True)(s)` (0.25.0; see art-only) |
| Planned, **not in MSE Studio yet** (made for 0.24.0, which wasn't released) | `edit_picture` / `picture_edit_not_ready`, `card_finder.Query.at_least`, pages in a scroll area. Use them only behind a fallback, as art-only does |
| `main.real_pictures(entries=None)`, `mse_studio.gui.real_card_actions` (`make_own`, `set_copies`, `picture_from_file`, `again`, `set_source`, `choose_picture`, `set_margin`, `remove`, `drop`, `fill_menu`), `main.real_cards_changed()` | The deck's real cards: their pictures, and everything the Cards page does with them – each a step in the history (0.25.0) |
| `real_cards.add_source(PictureSource(key, label, find, fetch, ready))`, `remove_source(key)`, `picture_sources()`, `source_label(key)` | Print-ready pictures for real cards, asked before Scryfall. `find`/`fetch` run on a worker thread (no widgets). Add in `__init__`, remove in `shutdown()` (0.25.0) |
| `main.choose_card_back()`, `main.print_home(rows)`, `main.proof_sheet()`, `main.make_backs(rows)`, `main.cards_tab.set_copies(rows)`, `main.cards_tab.show_real(name)`; `mse_studio.pipeline.order` (`slots`, `readiness`) | Printing (0.25.0) |
| `main.addon_page(id)`, `main.open_addon_page(id, why)`, `main.offer_addon(id, why, then=fn)` | Another add-on's page; offer to install a store add-on – only one the user's lists have; `main.addon_available(id)` (0.25.0). `main.playtest_tab` is the Playtest add-on's page or None |
| Taken out of MSE Studio in 0.25.0 | `gui.playtest_tab`, `core.playtest` – now in the playtest add-on. `core.addons.RETIRED`: add-ons the store dropped, not loaded |
| PySide6, Pillow, NumPy, OpenCV | Come with MSE Studio. Other packages: pure-Python ones copied into the add-on's folder |

Keep a deck's add-on data in a file in `main.project.folder` (like Deck notes'
`notes.md`), so it goes with the deck and its backups. Anything else (a
downloaded database, a cache) goes in `mse_studio.core.addons.data_dir("<id>")`
(MSE Studio 0.13.0): kept on updates, offered for deletion on uninstall. Never
in the add-on's folder – that's replaced on every update.

### Qt mistakes that crashed earlier versions

- Slow work (network, big files, MSE, Upscayl) goes in a `Job`, never on the
  GUI thread.
- Signals that outlive the page (`QApplication.clipboard().dataChanged`,
  `mse_studio.gui.thumbs.cache().ready`, timers, file watchers) connect to a
  **bound method** that starts with `try: … except RuntimeError: return`
  (the widget may be deleted) – never a lambda that holds widgets or list items.
- Never keep a `QListWidgetItem` / `QTreeWidgetItem` in a lambda or timer;
  keep its name and find it again.
- Stop timers, watchers and anything running in `shutdown()`.
- Never `QApplication.instance().installEventFilter(...)` (a filter on the whole
  app): PySide crashes when the built-in browser's own objects pass through
  it (0.16.0). Put the filter on your own widgets.

## Card lists

`lists/<name>.json`: `{"name", "description", "group", "cards": [{"name", "casting_cost",
"super_type", "sub_type", "rule_text", "flavor_text", "power", "toughness",
"rarity", "tags": [...]}]}`. Only `name` is needed. `tags` help Card ideas
match clues (a theme, a keyword, a character). `group` (0.25.0) is the heading
the list sits under in Card ideas ("Creature types", "Play styles"…). The
21 lists made for 0.25 are the `more-example-cards` add-on (Card ideas offers
it), so they update without an app update.

## Wording (match MSE Studio)

Plain, short English for people who aren't programmers: say what a button
does ("Add the ticked cards to my deck"), no jargon, British spelling
("colour"), a tooltip on anything that isn't obvious, and errors that say what
to do next.

## Testing

1. `python tools/build_index.py --check`
2. Zip `addons/<id>` and use **Add-ons → Install from file…** in MSE Studio
   (pages appear straight away; errors show on the Add-ons page), or
   `python tools/build_index.py --local` and add `dist/index.json` under
   **Add-ons → Lists…** to try the whole store.
3. With MSE Studio's source next to this repository, a page can be smoke-tested
   offscreen:

```python
import os; os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
from mse_studio.core import addons
from mse_studio.core.settings import AppSettings
from mse_studio.gui.main_window import MainWindow
w = MainWindow(AppSettings())
addons.install_zip(Path("dist/my-page-0.1.0.zip"))   # from --local
w.rebuild_pages()
w.open_project(Path("path/to/a/deck"))
```

