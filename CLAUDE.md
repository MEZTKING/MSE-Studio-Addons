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
  within minutes. Work on a branch and open a pull request (the *Check
  add-ons* action checks it) unless the user asks for it to go out now.
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
  outside the deck / add-on / what the user picked, no `eval`/`exec`, no
  downloading code, no touching MSE Studio's settings (API keys live there).
- Card lists: the authors' own wording – no real cards' text or art.
- Commits end with the attribution lines the session gives you. No model
  names in commits or files.

## The three sorts

| Sort | `kind` | What | Template |
|---|---|---|---|
| Page | `page` | A page in MSE Studio's side rail (Python + PySide6), runs inside MSE Studio | `templates/page-addon` |
| Card list | `cards` | Example cards (JSON) for *Card ideas → Example cards* | `templates/card-list-addon` |
| Program | `game-engine`, `tool`, `exporter`, `art`, `other` | A separate program MSE Studio starts with the chosen decks' `.deck.json` files | `templates/program-addon` |

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
| `main.tabs.setCurrentWidget(main.cards_tab)` + `main.cards_tab.select_row(i)` | Open a card |
| `main.settings` | Read only: `mse_path`, `upscayl_path`, theme… Never write it, never read keys or tokens from it |
| `main.known_frames()`, `mse_studio.core.styles` | The frames MSE has |
| `mse_studio.gui.nav.page_header(title, text)` | The title every page has – use it so the page looks like the others |
| `mse_studio.gui.common`: `Job`, `start`, `error`, `info`, `confirm`, `PathEdit` | `Job(fn)` runs `fn(progress=…, cancel=…)` on a worker thread; `job.signals.progress(done, total, text)`, `.finished(result)`, `.failed(text)`; `start(job)` |
| `mse_studio.gui.icons`: `icon(name)`, `set_icon(button, name)` | Icons that follow the theme |
| PySide6, Pillow, NumPy, OpenCV | Come with MSE Studio. Other packages: pure-Python ones copied into the add-on's folder |

Keep a deck's add-on data in a file in `main.project.folder` (like Deck notes'
`notes.md`), so it goes with the deck and its backups.

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

## Card lists

`lists/<name>.json`: `{"name", "description", "cards": [{"name", "casting_cost",
"super_type", "sub_type", "rule_text", "flavor_text", "power", "toughness",
"rarity", "tags": [...]}]}`. Only `name` is needed. `tags` help Card ideas
match clues (a theme, a keyword, a character).

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

## Plans

`plans/` holds ideas for future add-ons (not published): see
[plans/frame-studio.md](plans/frame-studio.md).
