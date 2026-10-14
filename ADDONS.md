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
  then `main.order_tab.real_pictures(entries)` makes the print files.
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
  browser. The MPCFill add-on is an example.
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

The deck file (`.deck.json`) is described in
MSE Studio's `docs/MTG_ENGINE_BRIEF.md` (section 5, the hand-off from MSE Studio).
Anyone can also make one by hand: **File → Export → Deck data → MSE Studio deck file**.

Installed add-ons live in `%APPDATA%\MSE Studio\addons\<id>`. Add-ons that
come with MSE Studio (such as mpc-autofill) are in the app's
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

Other lists (a friend's, or a private test list) can be added with
**Lists…** on the Add-ons page (one `index.json` address per line); add-ons from every list are shown together,
and the newest version of each id wins.

## Bundled: mpc-autofill

MSE Studio comes with a copy of the
[mpc-autofill](https://github.com/chilli-axe/mpc-autofill) desktop tool
(GPL-3.0) for the Order page's **Send to MPC**. Another copy or version can
be chosen on the Order page; installing an add-on with the id
`mpc-autofill` replaces the bundled one too.
