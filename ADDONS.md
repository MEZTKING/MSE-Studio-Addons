# MSE Studio add-ons

Add-ons extend MSE Studio. They are installed, updated, switched on and off
from the **Add-ons** page (Manage → Add-ons), which also shows the **store**:
every add-on in the public list, read live each time the page opens.

There are three sorts:

| Sort | `kind` | What it is |
|---|---|---|
| **Program** | `game-engine`, `tool`, `exporter`, `art`, `other` | A separate program MSE Studio starts (any language). They talk through files. |
| **Page** | `page` | A new page in MSE Studio's side rail, written in Python with PySide6. Runs **inside** MSE Studio. |
| **Card list** | `cards` | Example cards (JSON) for the card idea maker. No code. |
| **Upscaling models** | `models` | Extra models for Upscayl (`.param` + `.bin`), offered on the Upscale page. No code. |

Video capture (screenshots from videos into episode folders) and Pictures
(pictures from web pages, the clipboard and your screenshots) are page add-ons
in the store (they came with MSE Studio until 0.14).

## What an add-on is

A **zip** file with an `addon.json` at its root (or inside one top folder),
plus the program and anything it needs:

```
my-engine-0.1.0.zip
└── my-engine/
    ├── addon.json
    └── bin/My Engine.exe …
```

`addon.json`:

```json
{
  "id": "my-engine",
  "name": "My Engine",
  "version": "0.1.0",
  "kind": "game-engine",
  "description": "Play and simulate games with your MSE Studio decks.",
  "author": "MEZTKING",
  "homepage": "https://github.com/MEZTKING/MSE-Studio-Engine",
  "license": "GPL-3.0",
  "min_app_version": "0.10.0",
  "run": {"windows": "bin/My Engine.exe", "args": ["--decks", "{decks}"]}
}
```

| Field | Meaning |
|---|---|
| `id` | Unique, lowercase letters, digits, `-` `_` `.` – also the install folder name |
| `kind` | `game-engine`, `tool`, `exporter`, `art`, `page`, `cards` or `other`. A game engine gets a deck picker when it starts. |
| `version` | `major.minor.patch`. Higher versions in the list become updates. |
| `min_app_version` | The oldest MSE Studio that can run it (older ones show "needs MSE Studio x.y"). |
| `run.windows` | Programs: the program, relative to the add-on folder (it can't point outside it). |
| `run.args` | Programs: arguments. `{decks}` = the chosen decks' `.deck.json` files separated by `;`, `{deck}` = the first one, `{folder}` = the add-on's folder. |
| `page` | Pages: see below. |
| `cards` | Card lists: the list files in the add-on, e.g. `["lists/dragons.json"]`. |
| `fetch` | Big files the store downloads when it builds the zip (see Upscaling models). |
| `tags` | Words for the store's search, e.g. `["art", "fun"]`. |
| `screenshots` | Picture links shown in the store (the first three). |

## Page add-ons

```
hello-page/
├── addon.json
├── hello_page.py
└── helpers.py
```

```json
{
  "id": "hello-page",
  "name": "Hello page",
  "version": "1.0.0",
  "kind": "page",
  "description": "An example page.",
  "min_app_version": "0.11.0",
  "page": {"module": "hello_page", "class": "HelloPage", "title": "Hello",
           "icon": "extension", "section": "Review", "order": 60,
           "tooltip": "An example page"}
}
```

`hello_page.py`:

```python
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from . import helpers           # the add-on's own files (or: import helpers)


class HelloPage(QWidget):
    def __init__(self, main):           # main = MSE Studio's main window
        super().__init__()
        self.main = main
        self.label = QLabel()
        QVBoxLayout(self).addWidget(self.label)

    def load(self):                     # a deck was opened, or Settings changed
        self.label.setText(f"{len(self.main.project.set.cards)} cards in this deck")

    def refresh(self):                  # the page was opened
        self.load()

    def shutdown(self):                 # the deck is closing / MSE Studio quits
        pass
```

- `section` is `Create`, `Produce`, `Review` or `Manage` (anything else → Manage);
  the page goes after that section's own pages. `icon` is one of the icon names
  in MSE Studio's `resources/icons` (without `.svg`).
- `order` (optional, 50 if left out) places add-on pages of the same section:
  lower numbers first, then by name. Video capture uses 10, Pictures 11 and
  Card ideas 20.
- `load()`, `refresh()` and `shutdown()` are optional. Errors in them are logged
  and don't stop MSE Studio; an add-on whose page can't be made is listed as
  *couldn't start* with the error.
- The page can use anything in MSE Studio (`main.project`, `main.settings`,
  `mse_studio.core.*`, `mse_studio.pipeline.*`) and PySide6, Pillow, NumPy and
  OpenCV, which come with MSE Studio. Other packages: put pure-Python ones in
  the add-on's folder.
- **Where to keep things:** a deck's data in a file in `main.project.folder`
  (it goes with the deck and its backups). Anything else – a downloaded
  database, a cache – in `mse_studio.core.addons.data_dir("<id>")` (MSE Studio
  0.13.0): it stays when the add-on is updated, and removing the add-on offers
  to delete it. Not in the add-on's own folder: that's replaced on every update.
- Don't put an event filter on the whole app
  (`QApplication.instance().installEventFilter`): with the built-in browser
  it crashes MSE Studio. Put it on your own widgets.
- Keep the jobs you start (`mse_studio.gui.common.Job` / `start`) in a list and
  call `mse_studio.gui.common.forget(jobs)` in `shutdown()` (MSE Studio
  0.13.0): they stop, and none calls the page back after it's gone.
- **Real cards with your pictures** (MSE Studio 0.15.0): add them with
  `mse_studio.core.decklists.add_to_project(project, entries)`, then
  `mse_studio.pipeline.real_cards.use_picture(project, entry, picture, side,
  credit)` prints each with a picture file (MPC's bleed is added when it
  hasn't got it; `credit` – who made it, where from – stays with the card),
  then `main.real_pictures(entries)` makes the print files (MSE Studio 0.25.0;
  before, `main.order_tab.real_pictures(entries)` – the Order page did it).
- **Web pages** (MSE Studio 0.16.0): `mse_studio.gui.web_window` is a browser
  inside MSE Studio (Qt WebEngine) for sites that need a real browser.
  `open_web(parent, url, title, on_picture=fn, picture_label=…,
  on_download=fn, hint=…)` opens it in a window; `WebPanel(parent, url, …)` is
  the same browser to put on a page (make it when the page is first opened,
  and call `close_browser()` in `shutdown()`). `on_picture(picture_url,
  page_url, page_title)` adds *Use this picture* to a picture's right-click
  menu; `on_download(path, page_url)` gets the files the site downloads.
  `web_window.available()` is False in older builds – `open_web` then opens
  your usual browser. Logins and cookies are kept, apart from the user's own
  browser.
- **Print files** (MSE Studio 0.16.0): `mse_studio.pipeline.print_prep.make_print(img,
  spec, margin="auto")` makes a picture print-ready – `"auto"` adds MPC's
  margin unless the picture already has it (`has_mpc_margin(img)`), `"has"`
  only sizes it, `"add"` always adds it.
- **Sharper pictures** (MSE Studio 0.16.0): `mse_studio.gui.thumbs.large()` is a
  second picture cache at 1400 px next to `thumbs.cache()` (300 px) – the same
  `get(source_id, stamp, loader)` and `ready` signal.
- **Picture tools** (MSE Studio 0.17.0): `mse_studio.core.picture_tools.register(id,
  label, run, tooltip=…, owner=self)` adds a tool for card pictures (the Art
  only add-on adds *Keep only the art…*). The Decklists page offers every tool
  when you right-click a card, and other add-ons can too (`picture_tools.tools()`,
  `picture_tools.run(tool, parent, picture, info)`). `run(parent, picture,
  info)` gets the picture file and `{"name", "card" (Scryfall's data or {}),
  "credit", "kind": "real" | "proxy"}`. Register when the page is made; tools
  are cleared when MSE Studio builds the pages again.
- **Your own cards from pictures** (MSE Studio 0.17.0):
  `main.decklists_tab.add_custom(entries, source, frame=…, pictures=[…],
  keep_unknown=True)` adds cards to edit – the real card's text (when the
  entries were looked up), in a frame (`"real"`, `"mine"`, `"same"` or a
  frame's name), each with its own picture as the art (a file, or `(file,
  [x, y, w, h])`), fitted like MSE's Force to fit. Proxy decks uses it.
- **Frames** (MSE Studio 0.17.0): MSE's data folder is
  `mse_studio.core.styles.data_dir(main.settings.mse_path)`. Add a frame with
  MSE Studio's frame-pack installer – a zip with a `magic-<name>.mse-style`
  folder: `mse_studio.core.mse_packages.install_zip(zip, data_dir,
  backup_root=…)` – and take one out with `remove_package(data_dir, folder_name,
  backup_root)` (moved, never deleted). Then `main.frames_changed()` refreshes
  the frame lists. Frame studio is an example; never write MSE's folder
  yourself.
- **Deleting** (MSE Studio 0.17.0): `mse_studio.gui.common.delete_key(widget,
  fn)` makes the Delete key run `fn` on a list, grid or table, and
  `ask_delete(parent, text)` is True right away – or asks, when the user ticked
  Settings → Behaviour → *Ask before deleting*. Use them so your page deletes
  like the rest of MSE Studio.
- **A card's biggest picture** (MSE Studio 0.17.0):
  `mse_studio.core.decklists.fetch_full(card)` downloads a real card's PNG
  from Scryfall (once) and returns the file.
- **A browser that stays on one site** (MSE Studio 0.18.0):
  `WebPanel(parent, url, …, stay_on=("mpcfill.com",))` doesn't follow links to
  other sites (the files the site downloads – pictures on Google's servers –
  still come through); its address bar is read-only. `panel.allowed(url)`
  says where it may go.
- **Fonts** (MSE Studio 0.18.0): install fonts that came with a frame only
  through `mse_studio.gui.advanced.install_font_files(parent, files)` (for the
  Windows user, no administrator needed) – after asking. MSE is started again
  for the next preview (`main.fonts_changed()`), so it draws them.
  `mse_studio.gui.advanced.qt_installed_fonts()` + `mse_studio.core.fonts.
  is_installed(name, installed)` tell which are there already.
- **A new deck** (MSE Studio 0.18.0): `main.new_deck(name=…)` shows the New
  deck window with the name filled in and returns the new deck once it's open
  (None if cancelled) – then add its cards (the Card database add-on's *Make a
  new deck with it*). `main.new_deck(name=…, format="modern")` picks the
  format too (0.21.0).
- **Deck formats** (MSE Studio 0.21.0): `mse_studio.core.formats.of(project)`
  is the deck's format – `.key` (Scryfall's legality name: "commander",
  "standard"…), `.name`, `.size`, `.exact`, `.copies` (1 = singleton),
  `.has_commander`, `.family` ("commander", "singleton60", "constructed",
  "limited"), `.short()` for a hint. `formats.legal_state(fmt, card)` reads a
  real card's legality (`card["legalities"]`, kept with real cards from
  0.21.0). Build for the deck's format (the Card database add-on).
- **Finding real cards** (MSE Studio 0.22.0): `mse_studio.core.card_finder`
  finds real cards by what they do – commander ideas, real cards for a deck's
  gaps. `find(Query(colors=, commander=, roles=, types=, keywords=, words=,
  fmt=, limit=))` returns (cards, where from); `deck_query(project,
  commander=True)` builds a query from the deck's plan. An add-on that knows
  every card offline answers first: `add_finder(fn, "the card database")` in
  the page's `__init__`/`load()`, `remove_finder(fn)` in `shutdown()`; `fn(query)`
  returns Scryfall-like card dicts or None (the Card database add-on).
  (`query.at_least` – only cards whose colour identity has all of these
  colours – was planned for 0.24.0, which wasn't released: not in MSE Studio
  yet.)
- **Automate everything** (MSE Studio 0.21.0): `main.run_everything(ask=False,
  then=fn)` draws, upscales and makes print files without the run summary and
  calls `fn()` when it's done (not when it fails or is stopped).
- **Planeswalkers** (MSE Studio 0.18.0): write a planeswalker's rules text like
  the real card ("+1: Draw a card.", one ability a line). MSE Studio fills the
  frame's own ability and loyalty boxes from it (`mse_studio.core.walkers`)
  when the card is drawn or the deck is saved – cards added with
  `add_custom` get it straight away.
- **AI** (MSE Studio 0.20.0): `mse_studio.ai.for_addons` asks the AI service
  set in Settings → AI – the add-on passes `main.settings` and never reads the
  key itself. `not_ready(settings)` says why it can't be used yet ("" when it
  can), `service(settings)` names it for the page,
  `ask_json(settings, system, prompt, images=[png bytes], schema=…)` returns
  one JSON object (Claude, ChatGPT, Gemini… – pictures for the ones that see),
  `picture_not_ready(settings)` / `make_picture(settings, prompt, size=…)` make
  a picture (PNG bytes) with services that do (OpenAI gpt-image-1, xAI…; the
  model is Settings → AI → *Picture model*). They go over the internet: call
  them only from a button the user pressed, in a `Job`, and say on the page
  which service is used (Frame studio's designer and *Ask AI to match them*).
- **Planned, not in MSE Studio yet**: these were made for 0.24.0, which wasn't
  released – use them only behind a fallback, as Art only and Frame studio do:
  `for_addons.enabled(settings)` (AI switched off unless Settings → AI → *Use
  AI*; fallback `getattr(ai, "enabled", lambda s: True)(s)`), `edit_picture` /
  `picture_edit_not_ready` (AI repaints the white part of a mask), and every
  page in a scroll area.
- **Real cards' actions** (MSE Studio 0.25.0): `mse_studio.gui.real_card_actions`
  does what the Cards page does with a deck's real cards, each taking `main` and
  the cards (`decklists.Entry`): `make_own`, `set_copies`, `picture_from_file`,
  `again` (download again), `set_source(main, entries, key)`, `choose_picture`,
  `set_margin`, `remove` (after asking) / `drop`, and `fill_menu(menu, main,
  entries, parent, then=fn, own_then=fn)` for a right-click menu with all of
  them. Every change is a step in the deck's history. `main.real_pictures(entries
  =None)` gets their pictures and makes their print files (a job of the main
  window, stopped when the deck closes); `main.real_cards_changed()` shows a
  change on the Cards page and the open add-on page. `main.cards_tab.show_real(name)`
  opens a real card on the Cards page.
- **Print-ready pictures for real cards** (MSE Studio 0.25.0):
  `mse_studio.pipeline.real_cards.add_source(PictureSource(key, label, find,
  fetch, ready))` – asked before Scryfall when real cards get their pictures.
  `find(names, cancel)` returns {card name: [choice, …] best first} (a choice is
  `{"id", "name", "dpi", "source", "thumb", "extension"}`), `fetch(pick,
  timeout)` the chosen picture's bytes with MPC's margin, `ready()` "" or what
  to set up first. Both run on a worker thread: no widgets, a plain copy of
  your settings. Add it in the page's `__init__`, `remove_source(key)` in
  `shutdown()` (pages being rebuilt clear them all first). `picture_sources()`,
  `source_label(key)`. The Order add-on's MPCFill is one (key `"mpcfill"`).
- **Printing** (MSE Studio 0.25.0): `main.choose_card_back()` (the deck's card
  back from the gallery), `main.print_home(rows)`, `main.proof_sheet()`,
  `main.make_backs(rows)`, `main.cards_tab.set_copies(rows)`;
  `mse_studio.pipeline.order` has the order itself – `slots(project)`,
  `readiness(project)`, `order_xml(project, folder)`, `autofill_path(settings,
  own)` and `launch_autofill(exe, folder, how)` (the only way an add-on starts
  mpc-autofill). The Order add-on is built on these.
- **Other add-ons' pages** (MSE Studio 0.25.0): `main.addon_page(id)` is an
  installed add-on's page (or None); `main.open_addon_page(id, why)` shows it,
  or offers to get it; `main.offer_addon(id, why, then=fn)` installs one from
  the store after asking (`fn(page)` once it's there). `main.order_tab` is the
  Order add-on's page – or, without it, a stand-in with `real_pictures()` and
  `refresh()` for add-ons made before 0.25 – and `main.playtest_tab` the
  Playtest add-on's page or None.
- **Taken out of MSE Studio in 0.25.0** (now in the Order and Playtest
  add-ons): `mse_studio.gui.order_tab`, `gui.playtest_tab`, `core.playtest`,
  `core.mpcfill`, `gui.mpcfill_dialog`, and the MPCFill part of `real_cards`
  (`query`, `server_url`, `search`, `details`, `matching_entry`,
  `use_mpcfill`). An add-on that needs one of them is out of date: MSE Studio
  says so on the Add-ons page.
- **A page add-on runs its code inside MSE Studio**, so MSE Studio warns before
  installing one. Only add-ons that were checked are listed in the store.
- Installing, switching off or removing a page add-on rebuilds the pages straight
  away – no restart needed.

## Card list add-ons

```json
{
  "id": "dragon-cards",
  "name": "Dragon cards",
  "version": "1.0.0",
  "kind": "cards",
  "description": "Twelve dragon ideas across the colours.",
  "cards": ["lists/dragons.json"]
}
```

`lists/dragons.json` uses MSE's own field names:

```json
{
  "name": "Dragons",
  "description": "Big flyers with a twist",
  "cards": [
    {"name": "Emberwing Matriarch", "casting_cost": "3RR",
     "super_type": "Creature", "sub_type": "Dragon",
     "rule_text": "Flying\nWhenever another Dragon you control enters, it deals 2 damage to any target.",
     "flavor_text": "", "power": "5", "toughness": "5", "rarity": "rare",
     "tags": ["dragon", "tribal"]}
  ]
}
```

Only `name` is needed; `tags` help the idea maker match clues ("dragon",
"lifegain", a character's name …). The lists show up in **Card ideas →
Example cards**, and *Make this card* / *Add ticked to deck* copy cards into the
open deck.

## Upscaling model add-ons

```json
{
  "id": "anime-upscaling-models",
  "name": "Anime upscaling models",
  "version": "1.0.0",
  "kind": "models",
  "description": "Real-ESRGAN AnimeVideo v3 and 4xHFA2k.",
  "min_app_version": "0.12.1"
}
```

The models are `.param` + `.bin` pairs (Upscayl's NCNN format) in a `models`
folder of the add-on. Each one is offered on the **Upscale** page's model
list as *name (add-on name)*; Upscayl's own model stays the default until it's
picked. Upscayl reads a model's scale from its name (`x4` / `4x`).

Models are big, so the store repository doesn't keep them: list them in
`fetch` instead and the store downloads them – and checks each file's sha256 –
when it builds the add-on's zip:

```json
"fetch": [
  {"path": "models/4xHFA2k.param", "url": "https://raw.githubusercontent.com/upscayl/custom-models/<commit>/models/4xHFA2k.param",
   "sha256": "…"}
]
```

Credit the models' authors in the add-on's README.

A program released only inside a zip (like mpc-autofill's
`autofill-windows.zip`) is fetched with `"extract": "<file name>"`: the zip's
sha256 is checked and only that file goes into the add-on.

The deck file (`.deck.json`) is described in
MSE Studio's `docs/MTG_ENGINE_BRIEF.md` (section 5, the hand-off from MSE Studio).
Anyone can also make one by hand: **File → Export → Deck data → MSE Studio deck file**.

Installed add-ons live in `%APPDATA%\MSE Studio\addons\<id>`. Add-ons that
come with MSE Studio (the Card ideas lists) are in the app's
`resources\addons` folder; an installed copy with the same id replaces the
bundled one.

## Testing an add-on

Add-ons → **Install from file…** → pick the zip. Run it (or open its page)
from the Add-ons page. To replace it, install the new zip; to remove it, use
**Uninstall**. **Switch off** keeps it installed but hides its page and card
lists.

## The store: where to upload add-ons

The store is the public GitHub repository
**[MEZTKING/MSE-Studio-Addons](https://github.com/MEZTKING/MSE-Studio-Addons)**.
Every copy of MSE Studio reads
`https://raw.githubusercontent.com/MEZTKING/MSE-Studio-Addons/main/index.json`
when the Add-ons page opens (at most every 10 minutes, or with **Refresh the
store**).

**The easy way (add-ons kept in that repository):** put the add-on's folder
in `addons/<id>/` and push. A GitHub Action zips each new version, attaches it
to a release (`<id>-v<version>`) and rewrites `index.json` with the download
link and the download count. A new version = change `version` in its
`addon.json` and push. See that repository's README.

**By hand (add-ons with their own repository):**

1. Put each add-on version's zip on a **GitHub release** of its own repository.
2. Add (or update) its entry in **`index.json`** of MSE-Studio-Addons (in
   `external.json` there when the Action manages the list). It holds the same
   fields as `addon.json` plus `download`, the link to the zip:

```json
{
  "addons": [
    {
      "id": "my-engine",
      "name": "My Engine",
      "version": "0.1.0",
      "kind": "game-engine",
      "description": "Play and simulate games with your MSE Studio decks.",
      "author": "MEZTKING",
      "homepage": "https://github.com/MEZTKING/MSE-Studio-Engine",
      "license": "GPL-3.0",
      "min_app_version": "0.10.0",
      "run": {"windows": "bin/My Engine.exe", "args": ["--decks", "{decks}"]},
      "download": "https://github.com/MEZTKING/MSE-Studio-Addons/releases/download/my-engine-v0.1.0/my-engine-0.1.0.zip"
    }
  ]
}
```

That's it: everyone's Add-ons page shows it under *Store*, and people who
have an older version get an **Update** button. The store also shows how many
times each add-on was downloaded (↓ 12), counted from the releases'
downloads.

For a new version: make the new zip, release it, change `version` and
`download` in `index.json`.

**Older versions (MSE Studio 0.19.0):** an entry can also list the versions
people may go back to – `"versions": [{"version": "1.1.0", "download":
"…/my-engine-1.1.0.zip", "date": "2026-10-01"}, …]`, newest first (the
Action fills it from the releases). *Other versions…* on the Add-ons page
installs one of them, and can keep it there (no updates until you update it
yourself); *Update all* updates everything else at once.

Other lists (a friend's, or a private test list) can be added with
**Lists…** on the Add-ons page (one `index.json` address per line); add-ons from every list are shown together,
and the newest version of each id wins.

## mpc-autofill

[mpc-autofill](https://github.com/chilli-axe/mpc-autofill)'s desktop tool
(GPL-3.0, by chilli-axe and contributors) fills a MakePlayingCards order for
you. Until 0.25 MSE Studio came with a copy; now it's the store's
**mpc-autofill** add-on (a program add-on: the unmodified v4.7
`autofill-windows.exe`, downloaded from chilli-axe's release and checked when
the store builds the zip). The Order add-on's **Send to MPC** offers to
install it, and starts it through `mse_studio.pipeline.order.launch_autofill`;
another copy can be chosen on the Order page.

## Retired add-ons

`mse_studio.core.addons.RETIRED` lists add-ons the store doesn't have any more:
an installed copy isn't loaded, and the Add-ons page says what took its place.
**MPCFill** (the mpcfill.com page) was retired in 0.25: real cards' MPCFill
pictures are part of the Order add-on.
