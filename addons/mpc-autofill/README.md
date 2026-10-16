# mpc-autofill

The desktop tool of [mpc-autofill](https://github.com/chilli-axe/mpc-autofill)
by chilli-axe and contributors: it fills a MakePlayingCards order for you,
uploading every card front and back into the right slots in your browser, and
stops before checkout so you can check the order and pay.

The **Order** add-on's **Send to MPC** writes the order file and starts it
(and offers to install this add-on the first time). It opens in its own window
and asks its own questions there (site, browser…).

This is the unmodified `autofill-windows.exe` from mpc-autofill's
[v4.7 release](https://github.com/chilli-axe/mpc-autofill/releases/tag/v4.7)
(the store downloads it from there and checks its sha256). Until MSE Studio
0.25 the same file came with the app.

Windows only.

## Licence

mpc-autofill is copyright chilli-axe and contributors, licensed under the GNU
General Public License v3.0. Source code:
https://github.com/chilli-axe/mpc-autofill (tag v4.7).

## Network

It talks to MakePlayingCards (and whatever its own settings say) through the
browser it drives. MSE Studio itself sends nothing.
