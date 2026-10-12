# Card list add-on template

Example cards for MSE Studio's **Card ideas** page. No code – just JSON.

- Field names are MSE's: `name`, `casting_cost` (MSE notation: `2WU`),
  `super_type`, `sub_type`, `rule_text` (`\n` = new line, `CARDNAME` = the
  card's name), `flavor_text`, `power`, `toughness`, `loyalty`, `rarity`.
- Only `name` is needed. `tags` help the idea maker match clues ("knight",
  "lifegain", a character's name…).
- One add-on can have several lists: `"cards": ["lists/a.json", "lists/b.json"]`.
