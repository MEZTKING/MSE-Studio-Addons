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
| **Formats** | `formats` | Deck formats – house rules: size, copies, a commander, life, banned cards (MSE Studio 0.25.0). No code. |
| **Ability templates** | `templates` | Ability wordings for the Templates… window and card ideas (MSE Studio 0.25.0). No code. |
| **Characters** | `characters` | Characters' stories and the abilities picked for them, for the Cards page's *Abilities from a character's story…* (MSE Studio 0.25.0). No code. |
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
| `formats` | Formats: the format files in the add-on, e.g. `["formats/house.json"]` (0.25.0). |
| `templates` | Ability templates: text files in the template format, e.g. `["templates.txt"]` (0.25.0). |
| `characters` | Characters: their files, e.g. `["characters.json"]` (0.25.0). |
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
  before, `main.order_tab.real_pictures(entries)`).
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
- **Painting card art** (MSE Studio 0.25.0):
  `picture_tools.register_painter(label, run, owner=self)` makes MSE Studio's
  *Paint this card's art* (Ctrl+Shift+D, the Cards page's art menu) open your
  add-on instead of MSE Studio's own paint window: `run(card, base,
  start_blank)` – `base` a PIL picture to start from (the art just edited) or
  None – returns True when it opened. `picture_tools.painter()` is the one
  registered now (see the paint-studio add-on).
- **Card art from your add-on** (MSE Studio 0.25.0):
  `picture_tools.register_art_source(id, label, find, tooltip="",
  owner=self)` – `id` is your add-on's id – offers your pictures as *Art for
  your cards* when a deck is made from a prompt, in the Cards page's
  **New art ▾** and when cards are right-clicked. `find(info, cancel)` runs on
  a worker thread (no widgets): `info` is `{"name", "type", "art" (what the
  picture should show, when known), "deck", "theme", "prompt", "size" ((w, h)
  of the art box)}`, `cancel()` is True once Stop is pressed; return the
  picture's bytes, a file path, or `{"data" or "path", "credit"}` (where it
  came from, kept with the deck) – None when nothing was found. Put
  `"art_source": {"label": "…", "tooltip": "…"}` in addon.json too: the
  choice is offered before a deck (and your page) is open. Unregister in
  `shutdown()` (`unregister_art_source(id)`).
- **Your own cards from pictures** (MSE Studio 0.17.0):
  `main.decklists_tab.add_custom(entries, source, frame=…, pictures=[…],
  keep_unknown=True)` adds cards to edit – the real card's text (when the
  entries were looked up), in a frame (`"real"`, `"mine"`, `"same"` or a
  frame's name), each with its own picture as the art (a file, or `(file,
  [x, y, w, h])`), fitted like MSE's Force to fit.
- **Frames** (MSE Studio 0.17.0): MSE's data folder is
  `mse_studio.core.styles.data_dir(main.settings.mse_path)`. Add a frame with
  MSE Studio's frame-pack installer – a zip with a `magic-<name>.mse-style`
  folder: `mse_studio.core.mse_packages.install_zip(zip, data_dir,
  backup_root=…)` – and take one out with `remove_package(data_dir, folder_name,
  backup_root)` (moved, never deleted). Then `main.frames_changed()` refreshes
  the frame lists. Never write MSE's folder yourself.
- **Deleting** (MSE Studio 0.17.0): `mse_studio.gui.common.delete_key(widget,
  fn)` makes the Delete key run `fn` on a list, grid or table, and
  `ask_delete(parent, text)` is True right away – or asks, when the user ticked
  Settings → Behaviour → *Ask before deleting*. Use them so your page deletes
  like the rest of MSE Studio.
- **A card's biggest picture** (MSE Studio 0.17.0):
  `mse_studio.core.decklists.fetch_full(card)` downloads a real card's PNG
  from Scryfall (once) and returns the file.
- **A browser that stays on one site** (MSE Studio 0.18.0):
  `WebPanel(parent, url, …, stay_on=("example.com",))` doesn't follow links to
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
  set in Settings → AI (0.25.0: Settings → Advanced → Experimental → AI) – the
  add-on passes `main.settings` and never reads the key itself.
  `not_ready(settings)` says why it can't be used yet ("" when it can),
  `service(settings)` names it for the page,
  `ask_json(settings, system, prompt, images=[png bytes], schema=…)` returns
  one JSON object (Claude, ChatGPT, Gemini… – pictures for the ones that see),
  `picture_not_ready(settings)` / `make_picture(settings, prompt, size=…)` make
  a picture (PNG bytes) with services that do (OpenAI gpt-image-1, xAI…; the
  model is the AI settings' *Picture model*). They go over the internet: call
  them only from a button the user pressed, in a `Job`, and say on the page
  which service is used.
  0.25.0: `ask_json(…, cache=True)` when the same `system` goes out several
  times in a row (Claude keeps it a few minutes and charges a tenth for it
  again); an answer that was cut off raises `AnswerCut`, one that isn't JSON
  `AnswerUnusable` (both `AiError`s – asking once more usually works). The
  tokens every answer used are counted (`mse_studio.ai.usage`: `mark()` /
  `since(mark)` for your job, `used_text(…)` to show it,
  `cost(model, tokens_in, tokens_out)` for Claude's prices).
- **AI switched off** (MSE Studio 0.25.0): AI is an experiment people switch
  on (Settings → Advanced → Experimental → AI – off until they do). Off, MSE
  Studio shows no AI option or wording at all, and add-ons do the same:
  `for_addons.enabled(settings)` is False – hide your AI buttons and text
  (`not_ready` says it's switched off). For older MSE Studio:
  `getattr(ai, "enabled", lambda s: True)(settings)`.
- **Keywords checked by AI** (MSE Studio 0.25.0): `mse_studio.ai.keyword_check`
  asks the AI service about a deck's keywords – MSE Studio's
  (`main.project.set.keywords`) or a `.deck.json`'s. `cards_using(keywords,
  [(card name, rules text)])` picks a few cards using each;
  `check_keywords(settings, keywords, uses, deck_name, engine=False,
  progress=…)` returns `(verdicts, notes)`: each `KeywordVerdict` has
  `keyword`, `verdict` (fine, unclear or problem), `problems`, `questions`
  (what only the deck's author can decide), `reminder` (better wording, ""
  to keep it) and `similar`, and with `engine=True` also `tier` (script,
  engine or manual – for a rules engine like Forge) and `how`. It goes over
  the internet: only with `for_addons.enabled(settings)`, from a button, in a
  `Job`; it raises `for_addons.AiError` with a message to show.
- **Planned, not in MSE Studio yet**: `edit_picture` / `picture_edit_not_ready`
  (AI repaints the white part of a mask) and every page in a scroll area – made
  for 0.24.0, which wasn't released. Use them only behind a fallback, as Art
  only does.
- **Versions of a card** (MSE Studio 0.25.0): `mse_studio.core.versions`. An
  alternate is played as its card (counted once, always its rules); an art
  card is a picture of a card, never played. `info(project)` gives, by card
  index, `kind` ("", "alt", "art"), `of` (the card's index or -1),
  `versions(i)`, `card_of(i)`, `counts(i)`; `counted(project)` is the cards
  that count for the deck (use it rather than `project.set.cards` for sizes
  and checks – `decklists.deck_cards` already does). `add_version(project, i,
  kind)`, `set_version`, `unlink`, `share_rules`, `zone(project, i)`. Copies
  and backs of a version are kept under `order.card_key(project, card)`
  ("#" + its id), so read them with `order.quantity(project, card)`. Card ids
  (`deck_export.card_ids`) are steady: they stay with their card.
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
  `source_label(key)`.
- **Printing** (MSE Studio 0.25.0): `main.choose_card_back()` (the deck's card
  back from the gallery), `main.print_home(rows)`, `main.proof_sheet()`,
  `main.make_backs(rows)`, `main.cards_tab.set_copies(rows)`;
  `mse_studio.pipeline.order` has every card's print slot – `slots(project)` –
  and `readiness(project)`. One back card can be on several cards' backs (a
  card and its alternates share their back): `order.ties(project)` is front →
  back card, `order.fronts_of(project)` back card → its fronts,
  `order.roles(project)` every card's *Front · back: …* / *Back of …*.
- **Other add-ons' pages** (MSE Studio 0.25.0): `main.addon_page(id)` is an
  installed add-on's page (or None); `main.open_addon_page(id, why)` shows it,
  or offers to get it; `main.offer_addon(id, why, then=fn)` installs one from
  the store after asking (`fn(page)` once it's there) – only when one of the
  user's add-on lists has it; `main.addon_available(id)` says whether it's
  installed or listed, so a page can leave out what nobody can get. `main.playtest_tab` is the
  Playtest add-on's page or None.
- **Characters' stories** (MSE Studio 0.25.0): `mse_studio.gui.lore_dialog.open_for(main,
  name="", story="")` opens *Abilities from a character's story* for a name
  (looked up) or a story you already have (`story` is shown as it is).
  `mse_studio.core.lore`: `lookup(name, series, kind=…)` finds their story
  online; `cast(series, kind)` → `(members, where from)` – a series'
  characters, the main ones first (`CastMember`: `name`, `role` "main",
  "boss", "villain", "supporting" or "", `text`, `source`), from AniList or
  the series' fan wiki (the one named after the series; its main character,
  boss and villain categories); `character_card(name, text, about="", kept=(), role="")` – a
  `card_ideas.CardIdea` for them (the type, colours, cost and abilities their
  story fits; `card_ideas.add_to_deck(project, ideas)` adds it). `lookup` and
  `cast` go online: run them in a `Job`. `SOURCE_KINDS` – what a story can be
  from (`"anime"`, `"game"`, `"book"`, `"screen"`, `"comic"`). See the lore
  add-on.
- **Taken out of MSE Studio in 0.25.0** (now in the Playtest add-on):
  `mse_studio.gui.playtest_tab` and `core.playtest`. An add-on that needs one
  of them is out of date: MSE Studio says so on the Add-ons page.
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
"lifegain", a character's name …). A list's `"group"` (0.25.0, e.g.
`"Creature types"`) is the heading it's listed under – without one, the
add-on's name. The lists show up in **Card ideas → Example cards**, and *Make
this card* / *Add ticked to deck* copy cards into the open deck.

## Format add-ons

Deck formats for the Deck page and the New deck window (MSE Studio 0.25.0) –
the same files people make under **My formats** and share with *Export*:

```json
{"id": "house-formats", "name": "House formats", "version": "1.0.0",
 "kind": "formats", "min_app_version": "0.25.0",
 "description": "Our playgroup's formats.",
 "formats": ["formats/house.json"]}
```

`formats/house.json` holds one format or a list of them:

```json
[{"key": "big-table", "name": "Big table", "size": 120, "exact": true,
  "copies": 1, "commander": "commander", "life": 30, "sideboard": 0,
  "legality": "commander", "banned": ["A card's name"],
  "about": "What it is and the rules the checks can't know."}]
```

`commander`: `""`, `"commander"` or `"oathbreaker"`; `copies`: 0 = any number;
`legality`: a Scryfall legality list (`"commander"`, `"duel"`, `"premodern"`…)
or `""` for any card; `banned` adds names on top. Keys can't be MSE Studio's
own formats' (`commander`, `standard`…). A deck using one keeps its rules in
its `project.json`, so it opens the same elsewhere.

## Click area add-ons

Where you click to edit each field on a frame (Cards page → right-click the
card → *Fix click areas*), fixed by someone and shared (MSE Studio 0.25.0).
**Share…** in that window saves your fixes for the frame as such an add-on;
others install it (Add-ons → *Install from file…*, or from the store) and
click in the right places too. Their own fixes still come first; MSE
Studio's automatic boxes come last.

```json
{"id": "click-areas-m15-altered", "name": "Click areas for m15-altered",
 "version": "1.0.0", "kind": "click-areas", "min_app_version": "0.25.0",
 "description": "Where you click on the m15-altered frame, fixed by hand.",
 "click_areas": ["click_areas.json"]}
```

`click_areas.json` is the same as *Export…* saves: `{"<frame>": {"<field>":
[x, y, w, h] or null}}` – the box as parts of the card's width and height
(0–1), `null` for "no click area" (the frame doesn't show that field). One
file can hold several frames.

## Ability template add-ons

Ability wordings for the **Templates…** window (Cards page, beside the rules
text) and the card ideas – shared by someone (MSE Studio 0.25.0). In the
Templates window, **Share → My templates as an add-on…** saves your own
templates as such an add-on; *My templates as a file…* saves a text file the
other person adds with *Share → Add templates from a file…*.

```json
{"id": "templates-fire", "name": "Fire templates", "version": "1.0.0",
 "kind": "templates", "min_app_version": "0.25.0",
 "description": "Burning wordings for red decks.",
 "templates": ["templates.txt"]}
```

`templates.txt` is in MSE Studio's own template format: `[section]` lines
(`burn`, `draw`, `tokens`… – the deck jobs, or your own word) and one
template a line, `colours | card types | text`:

```
[burn]
R | creature | Whenever CARDNAME attacks, it deals 1 damage to each opponent.
R | instant | CARDNAME deals [N] damage to any target.
```

Colours are `W U B R G`, `C` for colourless or `*` for any; card types are
`creature`, `instant`, `sorcery`, `artifact`, `enchantment`, `planeswalker`,
`land`, `spell`, `permanent` or `*`. `CARDNAME` becomes the card's name in
MSE, `\n` starts a new line and `[bracketed]` parts are for the user to fill
in. They show in the Templates window with the add-on's name.

## Character add-ons

Characters' stories and the abilities picked for them, for **Abilities from
a character's story…** on the Cards page (under the rules text, and in
*Ideas*) – MSE Studio 0.25.0. In that window, **Share → This character as an
add-on…** (or *Every character of this deck as an add-on…*) makes one; *This
character as a file…* saves a `.character.json` the other person opens with
*Saved → Open a character file…*. Installed ones are under **Saved ▾** there.

```json
{"id": "characters-my-heroes", "name": "Characters: my heroes",
 "version": "1.0.0", "kind": "characters", "min_app_version": "0.25.0",
 "description": "Our heroes' stories and abilities.",
 "characters": ["characters.json"]}
```

`characters.json`: `{"characters": [{"name", "series", "story", "abilities":
[...], "sources": [{"title", "url", "source"}], "notes"}]}` – only `name` is
needed. `story` is plain text; `== Heading ==` lines split it into parts, and
the parts under an Abilities (Powers, Skills…) heading are the character's
skills. `abilities` are rules text in the template format's wording
(`CARDNAME` for the card's name). Write stories in your own words – not
copied from somewhere that doesn't allow it.

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

A program released only inside a zip is fetched with `"extract": "<file name>"`: the zip's
sha256 is checked and only that file goes into the add-on.

The deck file (`.deck.json`) is described in
MSE Studio's `docs/MTG_ENGINE_BRIEF.md` (section 5, the hand-off from MSE Studio).
Anyone can also make one by hand: **File → Export → Deck data → MSE Studio deck file**.

Installed add-ons live in `%APPDATA%\MSE Studio\addons\<id>` – or, once someone
has used Settings → Tools → *Move to another folder…* (0.25.0), in the
`MSE Studio files` folder they chose. So never build these paths yourself: use
`addons.data_dir("<id>")`, and `addons.files_dir()` for the folder they're in
(0.25.0; before it, `addons.config_dir()`). Add-ons that
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

**Private add-ons, only for you (MSE Studio 0.25.0):** keep them in a
**private** GitHub repository laid out like this store (`addons/<id>/`,
`tools/build_index.py`, the *Publish add-ons* Action) and let its Action run
`python tools/build_index.py --private`: the download links are then the
releases' file addresses a token can read. In MSE Studio, put a GitHub token
in **Settings → Behaviour → GitHub token** (fine-grained, that repository, *Contents:
Read-only*) and add the list's raw address under **Add-ons → Lists…**
(`https://raw.githubusercontent.com/<you>/<repository>/main/index.json`).
MSE Studio reads it – and downloads its add-ons – with your token, and only
from GitHub; the store marks them *private – only you*. Nobody else's MSE
Studio knows of them: the address is kept in your settings, and the
repository is private. To share one, give someone the address and access to
the repository (or send them the zip).

## Retired add-ons

`mse_studio.core.addons.RETIRED` lists add-ons the store doesn't have any more:
an installed copy isn't loaded, and the Add-ons page says what took its place.
