# Order

Step 4 of making a deck: the **Order** page.

- Every card's front and back side by side, as they'll be printed (size slider,
  *Full quality* for sharp pictures), with how many copies.
- **Before ordering**: what's still missing – the card back, cards not exported
  or printed yet, backs to make, real cards without their pictures – each with a
  button to fix it.
- Card stock and foil, the MPC order size, **Proof sheet (PDF)…**, **Print at
  home…**, the deck's **Card back…**.
- Right-click a card: copies, print it or not, MPC's margin, its back (the
  deck's, its own back face, another card, a picture). Real cards: make them
  your own card, copies, where the picture comes from, another picture, take
  them out.
- **Send to MPC** writes the order file (`order/cards.xml` in the deck) and
  starts [mpc-autofill](https://github.com/chilli-axe/mpc-autofill), which
  uploads every front and back into the right slots on MakePlayingCards in your
  browser and stops before checkout. The first time, it offers to get the
  **mpc-autofill** add-on from the store (or choose your own copy with
  *Change…*).
- **MPCFill…**: real cards printed with MPCFill's community-made, print-ready
  pictures (best first; right-click → *Choose another MPCFill picture…*). Find
  the server from mpcfill.com, or paste it. Without it real cards use
  Scryfall's pictures, enlarged with Upscayl.

Until MSE Studio 0.25 this page – and MPCFill for real cards – came with the
app; now it's here so the app stays smaller for people who print at home or
elsewhere. Your choices (browser, your own mpc-autofill, Full quality, the
MPCFill servers) are carried over the first time it starts and kept in its
data folder. The deck's order settings (copies, backs, stock) are the deck's
own, as before.

Needs MSE Studio 0.25.0 or newer.

## Network

- **MPCFill** (only once a server is set): when a deck's real cards get their
  pictures, their names are sent to your MPCFill server to find pictures, and
  the chosen pictures are downloaded from the image server or Google Drive.
  *Find them from mpcfill.com* reads mpcfill.com's page.
- Nothing else of its own. **Send to MPC** starts mpc-autofill (through MSE
  Studio), which then talks to MakePlayingCards in your browser.

## Programs it starts

Only mpc-autofill, only when you press **Send to MPC**, through MSE Studio's
`order.launch_autofill`: the copy from the mpc-autofill add-on, or a copy you
chose yourself.
