# Frame studio

Make a Magic Set Editor frame from pictures, on a **Frame studio** page under
Create. Use it for the blank frames a proxy maker shares or sells with a deck
(one picture per colour, often in a "templates" folder), or for frames you
drew yourself. Your cards can then use the frame like any other, so a proxy
deck's cards can be edited in their maker's own frame.

1. **New frame…** – add the frame pictures: a folder, picture files or a
   Photoshop file. Frame studio guesses which picture is which colour from
   its name ("White.png", "wcard.png", "Frame_U.png"…): check the guesses and
   give the frame a name. Pictures with MPC's 1/8 in margin ("bleed") are
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
     colour (named White, Blue… or W, U…, else told apart by their colours)
     and a tile for the numbers become the frame's own **mana symbols** –
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

From **Proxy decks**: right-click a deck → **This deck's frame** → *Make one
with Frame studio* opens its templates (and fonts) here, and the deck uses the
frame once it's made.

Needs MSE Studio 0.17.0 and MSE with the Full Magic Pack (for the Magic game,
its mana symbols and fonts).

## Network and files

None of its own. It reads the pictures and fonts you pick, keeps its frames
(and their fonts) in the add-on's data folder, and adds them to MSE's data
folder with MSE Studio's frame-pack installer – with its mana symbols, as
`magic-fs-<its name>-mana`, when it has its own (an older copy of the same
frame is kept in the add-on's data folder, never deleted). Fonts are installed only
when you say so, with MSE Studio's own font installer (Advanced → Fonts does
the same).

## Licences

Frames (and fonts) you buy are for your own use: make frames from them for
your own printed decks, don't share the pictures or the fonts.
