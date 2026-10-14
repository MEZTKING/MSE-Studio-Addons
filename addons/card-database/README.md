# Card database

Every Magic card on your PC, from Scryfall's bulk data, on a **Card database**
page under Review.

- **Import** a Scryfall bulk file you downloaded (`.json`, `.jsonl`, or either
  compressed as `.gz` – like `all-cards-20261013091836.jsonl.gz`), or
  **Download** one here. *Oracle cards* (one of each card, about 160 MB) is
  enough; *Default cards* has every printing, which the Card prices add-on
  uses to find each card's cheapest printing. *All cards* works too: only its
  English printings are kept.
- **Search**: name, rules text, type, colours (within a commander's colours),
  mana value, rarity, Commander-legal (and a top price with the Card prices
  add-on); sort by name, mana value, price, popularity (EDHREC) or newest.
  **Random** picks cards for you.
- **Add** cards to your deck as real cards, or as your own cards to edit and
  draw in your frames – a quick way to make more custom cards from an idea.
- **Build** a whole 100-card Commander deck around a commander: ramp, card
  draw, removal, board wipes, cards that fit the commander, lands and basics
  split by the colours' mana symbols.
  - **Play style**: balanced, aggressive, defensive (control), ramp, go wide
    (tokens), voltron, spells, combo, graveyard or casual – each sets the
    numbers and the kind of cards it likes. **Power**: casual, focused or
    high power.
  - **Themes**: 40+ ready-made ones – +1/+1 counters, tokens, sacrifice, life
    gain, graveyard, artifacts, landfall, blink, treasure, superfriends…
    and tribes (Dragons, Elves, Zombies, Goblins…) – tick as many as you
    like, and add your own words. **Leave out** extra turns, land
    destruction, tutors or locks.
  - The deck shows **the cards' pictures** (show one group at a time). Pick
    cards – Ctrl/Shift+click – and add them to your deck as real cards or to
    edit; **Another card for this job** swaps one; **Take out of the deck**.
  - **Make a new deck with it…** starts a new deck with all of it as real
    cards (the commander as its commander), or **Save as a decklist**.
- While it's installed, **Decklists** look cards up here first (no waiting for
  Scryfall).

Needs MSE Studio 0.15.1 (earlier Windows builds were missing a part of Python it uses, so the page couldn't start); *Make a new deck with it* fills in the deck's name with 0.18.0. The database is kept in MSE Studio's add-on data
folder, so updating the add-on keeps it; removing the add-on offers to delete
it.

## Network

Only when you press Download (Scryfall's bulk data), and for card pictures
(Scryfall's image server).

## Credits

Card data from [Scryfall](https://scryfall.com) (bulk data, updated daily).
This add-on isn't made or endorsed by Scryfall or Wizards of the Coast. Magic:
The Gathering card text and pictures are © Wizards of the Coast.
