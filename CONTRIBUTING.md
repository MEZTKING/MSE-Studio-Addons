# Checking add-ons before they're listed

MSE Studio warns people before installing an add-on that runs code, and tells
them that add-ons in this store are checked. So before merging a **page** or
**program** add-on:

- [ ] Read all of its code (every `.py` file for pages).
- [ ] It only does what its description says.
- [ ] It doesn't send anything anywhere without saying so on the page (no
      hidden network calls, analytics, or uploads of decks or settings).
- [ ] It doesn't read or change files outside the open deck's folder, the
      add-on's own folder, its data folder (`addons.data_dir("<id>")`) and
      files the user picks. (Reading another add-on's data folder is fine when
      the description says so – Card prices reads the Card database.) MSE's
      own data folder is changed only through MSE Studio's frame-pack
      installer (`mse_packages.install_zip` / `remove_package`), as Frame
      studio does, never by writing files there. Fonts are installed only
      through MSE Studio's font installer
      (`mse_studio.gui.advanced.install_font_files`), after asking.
- [ ] It doesn't run other programs, download code, or use `eval` / `exec`.
- [ ] It doesn't touch MSE Studio's settings (API keys and tokens live there).
- [ ] Programs: the zip is built from the linked source, and the release is
      from the author's repository.
- [ ] It installs and works in the newest MSE Studio (Install from file…), and
      switching it off and uninstalling it leave nothing broken.

**Card lists** are only JSON – check the cards are the author's own wording (no
copied real card text or art) and the check action passes.

**Updates** need the same check as new add-ons: compare the new version with the
last one.
