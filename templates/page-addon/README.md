# Page add-on template

1. Copy this folder to `addons/<your-id>/` and change `id` in `addon.json` to the
   folder's name.
2. Rename `my_page.py` / `MyPage` and change `page.module` / `page.class` to match.
   `page.section` picks where it goes in the side rail; add `"order": 60` to
   place it among the other add-on pages of that section (lower = higher up).
3. Test it: zip the folder and use **Add-ons → Install from file…** in MSE Studio
   (it shows up in the side rail straight away; errors show on the Add-ons page).
4. Push (or open a pull request) – see the main README.
