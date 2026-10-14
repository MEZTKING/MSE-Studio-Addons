# Frame studio – plan

**Frame studio 1.0 is built** (`addons/frame-studio`): an MSE frame made from
pictures – a proxy maker's blank frames (one per colour, PNG or Photoshop
layers), the boxes placed by dragging, text colours and fonts, installed with
MSE Studio's frame-pack installer. Proxy decks links a deck to its frame.
The phases below (restyling an existing frame, AI textures, copying a look,
Photoshop round trips) are still to do.

## The idea

A deck with a theme (a Frieren deck, an Overlord deck) wants frames that
match it: silver filigree and pale blue for Frieren, dark gold and purple for
Overlord. Frame studio makes **a new MSE frame from one you already have**,
restyled for the theme, and later **AI textures from a prompt**. The new
frame shows up in MSE Studio's frame list like any other and prints the same.

It's a **page add-on** (`kind: page`, section Create): optional, and its
heavier parts (an image service) only matter to people who want them.

## How an MSE frame is made (what gets changed)

A frame is a folder in MSE's `data` folder, e.g.
`magic-universes-beyond_750.mse-style/`:

- `style` – MSE script: name (`short name`, `full name`), card size
  (`card width: 750`, `card height: 1046`, `card dpi: 300`), where every field
  goes, fonts, and which picture is drawn for which colour.
- Pictures for each colour, one file per colour letter
  (`w u b r g` + `a` artifact, `c` colourless, `m` multicolour):
  `card/wcard.png` (frame, title and type bars, text box), `pt/wpt.png`
  (power/toughness box), `crown/wcrown.png` (legendary crown),
  `stamp/…`, `alias/…`, `stampbackground/…`.
- Masks and blends: `*_blend_*.png` for hybrid / multicolour cards,
  `*_mask.png` for borders, foil, corners.

So a restyled frame = a copy of the folder with a new name, the same `style`
script (only the names changed) and new pictures. Nothing in MSE has to
change, and the deck's cards keep working when the frame is swapped
(MSE Studio's Frame tab).

## Phase 1 – Restyle a frame (no AI)

1. **Pick a base frame** from the frames MSE has (`main.known_frames()`,
   `mse_studio.core.styles.list_styles`). Start with the m15 / Universes
   Beyond family (what the decks use); others later.
2. **Find the parts of the frame picture.** MSE Studio already knows where
   each field's box is on a frame (`mse_studio.pipeline.style_boxes`, used for
   click areas). From those: title bar (name box), type bar (type box), text
   box (rules box), art window, and "frame" = the rest of the non-transparent
   pixels. The user can nudge a part by painting on it if the guess is off.
3. **Restyle each part**, for each colour picture, with Pillow / NumPy /
   OpenCV (they come with MSE Studio):
   - recolour (hue, saturation, brightness, tint with a colour, gradient),
   - lay a texture picture over a part (the user's own picture: marble,
     parchment, a pattern), keeping the original shading (multiply / overlay)
     and the transparency,
   - text box: lighter / darker / see-through, so rules text stays readable,
   - one theme for all colours, or per colour (keep the colour cue: a white
     card should still read as white).
4. **Preview** on a sample card of the open deck with MSE itself
   (`main.previewer()` renders through MSE's command line).
5. **Save** as a new frame folder in MSE's `data` folder
   (`magic-universes-beyond_750-frieren.mse-style`, full name "Universes
   Beyond – Frieren"), then refresh MSE Studio's frame list. A theme can be
   saved as a small JSON file and applied to another base frame.

Size: medium. Most of the work is step 2 (finding the parts reliably) and
making the result look good on all eight colours.

## Phase 2 – AI textures from a prompt

- The user writes or picks a prompt ("ornate elven silver filigree, pale blue
  and white, soft glow – for Frieren"), Frame studio adds what frames need
  (seamless, no text, no faces, top-down, high resolution).
- Pictures come from an image service the user sets up with **their own key**
  in the add-on (OpenAI images, Stability, or a local ComfyUI / Automatic1111
  server on their PC). Nothing is sent anywhere until they press Generate, and
  the page says where it goes. The key is kept in the add-on's own settings
  file, never in MSE Studio's settings.
- The textures go into Phase 1's parts (frame, bars, text box), so the
  layout, text and print sizes never change – the AI only paints the surface.
- A gallery of results to choose from; keep the prompt with the theme.

Size: medium on top of Phase 1, plus whatever the image service costs per
picture. Results vary, so choosing between a few is part of the design.

## Phase 3 – Copy the look of a real frame

The user gives a picture of a frame they like (a scan, a screenshot). Frame
studio takes its colours and textures (palette, a texture sample per part) and
applies them in Phase 1. Redrawing another frame's shapes is out of scope.

## Phase 4 – Photoshop for advanced users

For the best frames: design them in Photoshop (or Photopea, the free one in
a browser, which reads the same files and runs the same scripts).

1. **Open in Photoshop** – Frame studio writes the base frame's pictures
   (every colour's `card`, `pt`, `crown`… picture) and a small Photoshop
   script (`.jsx`). The script builds one document per colour, each picture
   as a named layer in its place, with guides for every field box (title,
   type line, rules box, art window, P/T) so text never ends up under
   decoration. No PSD library is needed in MSE Studio: Photoshop builds the
   PSD itself.
2. The user paints, adds textures, effects, anything Photoshop does – as long
   as the named layers stay (extra layers are merged into the one they're in).
3. **Export for MSE Studio** – a second script, run in Photoshop, saves each
   named layer back as the right PNG (`card/wcard.png`, `pt/wpt.png`…), with
   transparency, at the frame's size.
4. Frame studio reads that folder, checks every picture is there and the
   right size, previews on a card of the deck, and installs the frame (as in
   Phase 1). Changing it later = edit the PSD, export again.

Size: small to medium (the two scripts and the check), and the most
powerful option. The scripts are plain text in the add-on; they only read
and write files in the folder Frame studio made.

## Templates

Phase 1 themes saved as small JSON files (colours, texture pictures, text box
opacity) can be shared: a **frame themes** add-on sort (like card lists) would
let the store offer ready themes – "Elven silver", "Necromancer gold", "Ink
wash" – applied to any base frame in one click.

## What MSE Studio needs to give add-ons for this

- The frame list and MSE's `data` folder (there already).
- Field boxes of a frame (`style_boxes`) – make that a documented, stable call.
- A way to refresh the frame list after a frame is added (a small
  `main.frames_changed()`).
- Rendering one card with a given frame (the preview renderer has this).

## Licences

Full Magic Pack frames are community-made. Restyled copies for your own
printed decks are fine; don't publish other people's frame pictures in the
store. Frame studio itself can be in the store; the frames it makes stay on
the user's computer (they could share their own theme files).

## Open questions for later

- Which base frames first (Universes Beyond / m15, full-art anime frames)?
- One theme per deck, or per card (e.g. a different look for the commander)?
- Which image service to support first?
- Photoshop scripts: one document per colour, or one document with a layer
  group per colour?
