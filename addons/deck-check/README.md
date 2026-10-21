# Deck check

A page under **Review** that checks exported decks before they're played in a
rules engine. Export a deck with **File → Export → Deck data → MSE Studio deck
file**, then **Open decks…** on the page.

- **Fix in MSE Studio** – data the engine would trip over: mana symbols nobody
  can read, power/toughness that isn't a number, a card's text naming another
  card, names that match no card, different cards sharing one name, a deck
  that isn't 100 cards.
- **Questions for you** – wording that can be read more than one way. Type
  your ruling in the box under the list; **Copy my answers** puts them all on
  the clipboard.
- **Good to know** – alternate arts, art-only versions, new card types.
- **Every card** – each card once, with its other versions under it
  (alternate arts, and "Art Card" pictures that aren't played), and whether
  the Forge rules engine can run it as it is (Forge script), needs new engine
  code, or has to be resolved by hand. Versions count once in the deck size.

Anything can be ignored (**Ignore** under the list) – it moves to *Ignored*
and leaves the counts. The page remembers each deck's last two exports and
warns when card ids move between them. **Save report…** writes `report.html`,
`report.json` and `cards.csv`.

With AI switched on in MSE Studio (Settings → Advanced → Experimental → AI),
**Check keywords with AI** asks the AI service set there whether each of the
deck's own keywords works as written. Nothing else is sent anywhere.

Its data folder keeps the decks you had open, your answers, what you ignored,
the AI's answers and each deck's last two exports' card ids.

`deckcheck/` also runs on its own: `python -m deckcheck my.deck.json --out reports`.
Its list of Magic keywords and card names comes from
[Forge](https://github.com/Card-Forge/forge) (GPL-3.0), so this add-on is
GPL-3.0 too.
