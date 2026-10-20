# Program add-on template (game engines, tools)

A separate program that MSE Studio starts – any language.

- `run.windows`: the program, inside the add-on's folder.
- `run.args`: `{decks}` = the chosen decks' `.deck.json` files separated by `;`,
  `{deck}` = the first one, `{folder}` = the add-on's own folder.
- A `game-engine` gets a deck picker when it starts. The deck file format is in
  MSE Studio's `docs/MTG_ENGINE_BRIEF.md`.

Programs are usually too big for this repository: build the zip (with
`addon.json` at its root, next to `bin/`), attach it to a release of the
program's own repository, and add an entry to `external.json` here with the
same fields as `addon.json` plus `"download": "https://…/my-engine-0.1.0.zip"`.
