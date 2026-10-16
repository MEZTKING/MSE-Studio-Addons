# Frame studio

Make a Magic Set Editor frame from a frame template – or design one – on a
**Frame studio** page under Create. Use it for the blank frames a proxy maker shares or sells with a deck
(one picture per colour, often in a "templates" folder), or for frames you
drew yourself. Your cards can then use the frame like any other, so a proxy
deck's cards can be edited in their maker's own frame.

1. **New frame…** (*New frame from a template*) – add the template: a folder,
   picture files or a Photoshop file. Frame studio works out which picture
   is which colour from its name ("White.png", "wcard.png", "Frame_U.png"…)
   or, when the names say nothing, from its colours: check the choices –
   each row only offers what fits it (a colour's frame, a P/T box or a mana
   symbol). **Match automatically** fills the ones not chosen yet; **Ask AI
   to match them** sends one sheet of small numbered pictures (and their
   names) to the AI service set up in MSE Studio's Settings (MSE Studio 0.20.0),
   which says what each is for. Pictures with MPC's 1/8 in margin ("bleed") are
   trimmed for you.
   - **Photoshop files** are read in the background (a progress bar, and
     Stop). When the file has its colours as layers or groups named White,
     Blue… (side by side, also inside groups like "Pinlines" or "Text box"),
     each colour's frame is **put together for you** – that colour's layers,
     without the sample text, the art and the set symbol. The P/T box becomes
     its own picture (so only creatures get one). The file's groups, the
     whole file and every single layer can be picked too. Groups, layer
     masks, opacity, clipping masks and the usual blend modes are drawn;
     layer effects (shadows, glows, strokes) aren't – *All layers* is
     Photoshop's own picture with them, for the colour the file was saved
     showing. 8-bit RGB, greyscale and CMYK files.
   - **Templates made for Proxyshop** (and others like them – groups such as
     *Pinlines & Textbox*, *Name & Title Boxes*, *Background* and *PT Box*,
     each with a layer per colour: W, U, B, R, G, Gold, Land, Artifact,
     Colorless): each colour's frame takes that colour's layer from every
     group. Parts only some cards have – *Legendary Crown*, *Nyx*,
     *Companion*, *Color Indicator* – are left out unless the file was saved
     showing them; lands use *Land Pinlines & Textbox* instead of the usual
     one; the art layer under *Art Frame* is left out. Vector masks are drawn.
   - **The text is placed from the file**: its text layers (*Card Name*,
     *Mana Cost* or a *Mana* group, *Typeline*, *Rules Text*, *Power /
     Toughness*, *Expansion Symbol*, *Artist*…) and guides (*Art Frame*,
     *Textbox Reference*, *Expansion Reference*, *PT Reference*) say where
     each text goes, how big, in which colour (a Colour Overlay counts), in
     which font and whether it's centred. Untick *Place the text where … has
     it* to place it yourself. Mana symbols in a tall, narrow box go one
     under the other.
   - **The template's own mana symbols**: a *Mana* group with a picture per
     colour (named White, Blue… or W, U…, else told apart by their colours –
     also groups named by their place, like *Pos 1*, *Pos 2*, each holding a
     layer per colour: each colour is put together from the first one) and a
     tile for the numbers become the frame's own **mana symbols** –
     MSE draws the mana cost with them (numbers and X written on the number
     tile in the template's font and colour; hybrid and other symbols stay
     MSE's usual ones). They're installed for MSE with the frame.
   - **Layer effects** are drawn: colour overlays, strokes, drop shadows and
     outer glows (bevels, inner shadows and gradient overlays aren't). Drop
     shadows on the text layers become **text shadows** in MSE.
   - **Fonts** that come with the frame – a Fonts folder, font files or a
     fonts .zip in what you add, or **Add fonts…** – are listed: pick the one
     for the name and type line (and the rules text, if one is meant for it).
     They're kept with the frame. A template's own fonts are matched to them
     by name; the window says which fonts it uses that didn't come with it.
2. **Where things go** – drag the boxes for the name, mana cost, art, type
   line, set symbol, rules text, P/T and the artist and credit lines onto the
   frame (drag a corner to size one). Most frames have a see-through art
   window: the art goes *under* the frame. For full-art frames, **The art
   fills the whole card**. **Show sample text** draws a name, mana cost, type
   line, rules text and P/T in the boxes with the frame's fonts and sizes, so
   you can check them without trying a card in MSE.
3. **Text** – the colour of each text (guessed: white on dark parts, black on
   light ones), the fonts, the **text sizes** (each box gets a sensible size
   – the cost box's symbols don't grow when the box is taller – or set your
   own), **where each text sits** in its box (left, centre or right), how
   the **mana symbols go** (in a row, or one under the other – from the top,
   or from the bottom with the colours on top), the **numbers on the mana
   symbols** (font and colour) and the **text shadows**. *Fonts that came with this frame* shows which
   are installed; **Install them for MSE** installs them for your Windows
   user (no administrator needed) – MSE only draws installed fonts.
4. **Save and add to MSE** – the frame goes in MSE's frames, as
   `fs-<its name>` (its fonts are offered for installing first). **Try it on a card** shows the card you're editing in it
   (MSE draws it; your card isn't changed). **Use it on my selected cards**
   puts it on the cards selected on the Cards page.

**Frames made with Frame studio 1.0** from a Photoshop file often got
nearly empty pictures (one thin layer each). The Pictures tab says so:
**Pictures from the files again…** makes them again from the same files with
the groups and layers of 1.1 – and, if you leave *Place the text where … has
it* ticked, the text's places, sizes, colours and fonts from the file too
(untick it to keep yours). Add the Photoshop file (and its fonts) again if
it has moved.

**Mana symbols** (Pictures tab): White, Blue, Black, Red, Green, Colourless
and the tile for numbers and X – from the template, or pick pictures of your
own (*Choose…*). Symbols without a picture are MSE's usual ones.

Colours without a picture use the Colourless picture (or the first one there
is). Cards of several colours use Gold, lands the Land picture (else their
colour's). P/T boxes that come as separate pictures can be added too.

## The Frame designer

**Design a frame…** draws a whole frame for you – a frame for every colour,
P/T boxes and mana symbols, with the text boxes exactly where MSE writes the
text. Start from a ready-made look (*Gothic*, *Neon*, *Old parchment*,
*Gilded marble*, *Borderless*, *Full art glass*, *Minimal*…) and change
anything; the preview shows the colour you pick, every colour below it and
the mana symbols.

- **Look**: layout (modern, classic, borderless, full art, minimal),
  material (solid, gradient, brushed metal, stone, parchment, grunge, marble,
  leather, wood, carbon fibre, or a texture picture of your own), how strong
  and how coarse the texture is, and *Shuffle* for another pattern.
- **Colours**: a palette (classic Magic colours, dark, vivid/neon, pastel,
  black and white, gothic – black with colour trim, gilded) or your own
  colour for each of White, Blue, Black, Red, Green, Gold, Artifact,
  Colourless and Land.
- **Border** colour and width; **bars** (rounded, square, cut corners, torn,
  none) and how see-through; **text box** (light, parchment, tinted, dark,
  see-through glass), its shape and how see-through; the **art window**
  (square, rounded, arched); a **P/T box** or not.
- **Edges and effects**: pinlines and their colour, bevel, shadows, glow,
  wear, grain, darker corners.
- **Mana symbols**: circles, square tiles, diamonds or brushed tiles (or
  MSE's usual ones), and the mana cost down the right side.
- **Fonts** for the name and type line and for the rules text.
- **Design it with AI**: describe the look ("dark gothic, blood-red trim, a
  parchment text box, mana down the side") – and show an example card if you
  like – and the AI picks the settings. **Make one with AI** paints a texture
  picture for the material (a picture service: OpenAI or xAI – Claude doesn't
  make pictures). Both use the AI service set up in MSE Studio's Settings
  (MSE Studio 0.20.0; from 0.25.0 under Advanced → Experimental, where AI can
  be switched off – then these buttons aren't shown); the
  window says which service, and each press is one request on your account.

**Make the frame** draws it (about half a minute); then check it on *Where
things go* and **Save and add to MSE** as usual. **Edit the design…** (on the
Pictures tab) opens its settings again and draws it anew.

From **Proxy decks**: right-click a deck → **This deck's frame** → *Make one
with Frame studio* opens its templates (and fonts) here, and the deck uses the
frame once it's made.

Needs MSE Studio 0.17.0 and MSE with the Full Magic Pack (for the Magic game,
its mana symbols and fonts).

## Network and files

None of its own – the AI buttons (*Design it with AI*, *Make one with AI*,
*Ask AI to match them*) go through MSE Studio's AI settings, only when you
press them, and say which service they use. Textures the AI paints are kept
in the add-on's data folder. It reads the pictures and fonts you pick, keeps its frames
(and their fonts) in the add-on's data folder, and adds them to MSE's data
folder with MSE Studio's frame-pack installer – with its mana symbols, as
`magic-fs-<its name>-mana`, when it has its own (an older copy of the same
frame is kept in the add-on's data folder, never deleted). Fonts are installed only
when you say so, with MSE Studio's own font installer (Advanced → Fonts does
the same).

## Licences

Frames (and fonts) you buy are for your own use: make frames from them for
your own printed decks, don't share the pictures or the fonts.
