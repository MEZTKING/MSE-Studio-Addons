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
   - **Fonts** that come with the frame – a Fonts folder, font files or a
     fonts .zip in what you add, or **Add fonts…** – are listed: pick the one
     for the name and type line (and the rules text, if one is meant for it).
     They're kept with the frame.
2. **Where things go** – drag the boxes for the name, mana cost, art, type
   line, set symbol, rules text, P/T and the artist and credit lines onto the
   frame (drag a corner to size one). Most frames have a see-through art
   window: the art goes *under* the frame. For full-art frames, **The art
   fills the whole card**.
3. **Text** – the colour of each text (guessed: white on dark parts, black on
   light ones) and the fonts. *Fonts that came with this frame* shows which
   are installed; **Install them for MSE** installs them for your Windows
   user (no administrator needed) – MSE only draws installed fonts.
4. **Save and add to MSE** – the frame goes in MSE's frames, as
   `fs-<its name>` (its fonts are offered for installing first). **Try it on a card** shows the card you're editing in it
   (MSE draws it; your card isn't changed). **Use it on my selected cards**
   puts it on the cards selected on the Cards page.

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
folder with MSE Studio's frame-pack installer (an older copy of the same frame
is kept in the add-on's data folder, never deleted). Fonts are installed only
when you say so, with MSE Studio's own font installer (Advanced → Fonts does
the same).

## Licences

Frames (and fonts) you buy are for your own use: make frames from them for
your own printed decks, don't share the pictures or the fonts.
