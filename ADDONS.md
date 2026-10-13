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
that come with MSE Studio – switch them off on the Add-ons page if you don't
use them.

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
  lower numbers first, then by name. MSE Studio's own add-on pages use 10
  (Video capture), 11 (Pictures) and 20 (Card ideas).
- `load()`, `refresh()` and `shutdown()` are optional. Errors in them are logged
  and don't stop MSE Studio; an add-on whose page can't be made is listed as
  *couldn't start* with the error.
- The page can use anything in MSE Studio (`main.project`, `main.settings`,
  `mse_studio.core.*`, `mse_studio.pipeline.*`) and PySide6, Pillow, NumPy and
  OpenCV, which come with MSE Studio. Other packages: put pure-Python ones in
  the add-on's folder.
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
