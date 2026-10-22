"""Write report.html (for people), report.json and cards.csv (for the converter)."""
from __future__ import annotations

import csv
import html
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .mechanics import TIER_LABEL

TITLES = {
    # errors
    "deck-size": "Deck size", "color-identity": "Colour identity", "commander-no-cost": "Commander",
    "commander-type": "Commander", "commander-missing": "Commander", "singleton": "Different cards with one name", "duplicate": "Two copies",
    "text-symbol": "Symbols nobody can read", "cost-symbol": "Mana cost symbols", "cost-syntax": "Mana cost",
    "mana-value": "Mana value", "pt-value": "Power / toughness", "pt-missing": "Power / toughness",
    "loyalty-missing": "Loyalty", "empty-text": "Missing rules text", "truncated": "Cut-off text",
    "no-effect": "Abilities with no effect", "wrong-self-name": "Wrong name in its own text",
    "leftover-name": "Real card names left in the text", "missing-named-card": "Names that match no card",
    "keyword-space": "Deck keyword data", "keyword-template": "Deck keyword data",
    "misspelled-keyword": "Misspelled keywords", "art-mixup": "Art cards that hold the game text", "ids-moved": "Card ids changed between exports",
    # questions
    "keyword-ruling": "Deck keywords: what exactly do they do?", "card-ruling": "Cards: what exactly do they do?",
    "permanent-imperative": "When does this happen?", "spell-etb": "Spells that “enter the battlefield”", "searches-itself": "Cards that search for themselves",
    "no-cost": "Cards with no mana cost", "loyalty-on-nonwalker": "Loyalty abilities on creatures",
    "real-name": "Same name as a real Magic card", "split-subtype": "Multi-word subtypes",
    "unknown-keyword": "Undefined keywords", "keyword-clash": "Keyword names that clash with Magic",
    # info
    "compact-symbol": "Shorthand mana symbols", "custom-type": "New card types", "custom-supertype": "New supertypes",
    "keyword-unused": "Unused deck keywords", "alt-arts": "Alternates worded differently", "art-blank": "Art versions (pictures)",
    "alt-renamed": "Alternates with a name of their own", "alt-alone": "Alternates of nothing", "renamed": "Renamed cards", "ids-renewed": "Steady card ids", "added-removed": "Since the last export", "real-basics": "Basic lands", "keyword-unclassified": "Unclassified keywords",
}
ORDER = list(TITLES)
ORDER.insert(0, ORDER.pop(ORDER.index("ids-moved")))


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in s.lower()).strip("-")


def write_reports(analysed, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = []
    with open(out_dir / "cards.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["deck", "card_id", "name", "count", "type_line", "tier", "version_of", "deck_keywords", "reasons",
                    "errors", "questions"])
        for deck, results, findings in analysed:
            per_card = defaultdict(lambda: Counter())
            for f in findings:
                if f.card_id:
                    per_card[f.card_id][f.kind] += 1
            for r in results:
                c = r.card
                w.writerow([deck.name, c.id, c.name, c.count, c.type_line.strip(), r.tier, r.version_of, "; ".join(r.keywords),
                            " | ".join(r.reasons), per_card[c.id]["error"], per_card[c.id]["question"]])
            payload.append({
                "deck": deck.name, "file": deck.path.name,
                "cards": [{"id": r.card.id, "name": r.card.name, "tier": r.tier, "version_of": r.version_of_id,
                           "deck_keywords": r.keywords,
                           "real_keywords": r.real_keywords, "unknown_keywords": r.unknown_keywords,
                           "reasons": r.reasons} for r in results],
                "findings": [vars(f) for f in findings],
            })
    (out_dir / "report.json").write_text(json.dumps({"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                     "decks": payload}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "report.html").write_text(render_html(analysed), encoding="utf-8")


def _finding_li(f, qid=None):
    who = f'<span class="card">{html.escape(f.card)}</span> ' if f.card else ""
    fix = f'<div class="fix">Fix: {html.escape(f.fix)}</div>' if f.fix else ""
    ans = ""
    if qid:
        ans = (f'<textarea class="answer" data-q="{qid}" data-text="{html.escape((f.card + ": " if f.card else "") + f.message)}" '
               f'rows="1" placeholder="Your ruling…"></textarea>')
    return f"<li>{who}{html.escape(f.message)}{fix}{ans}</li>"


def _section(kind, findings, deck_slug, heading, intro):
    items = [f for f in findings if f.kind == kind]
    if not items:
        return ""
    groups = defaultdict(list)
    for f in items:
        groups[f.code].append(f)
    parts = [f'<section class="kind {kind}"><h3>{heading} <span class="n">{len(items)}</span></h3><p class="intro">{intro}</p>']
    for code in sorted(groups, key=lambda c: ORDER.index(c) if c in ORDER else 999):
        fs = groups[code]
        lis = "".join(_finding_li(f, f"{deck_slug}-{code}-{i}" if kind == "question" else None) for i, f in enumerate(fs))
        open_attr = " open" if len(fs) <= 8 else ""
        parts.append(f'<details{open_attr}><summary>{html.escape(TITLES.get(code, code))} <span class="n">{len(fs)}</span></summary><ul>{lis}</ul></details>')
    parts.append("</section>")
    return "".join(parts)


def render_html(analysed) -> str:
    tabs, panels = [], []
    for i, (deck, results, findings) in enumerate(analysed):
        slug = _slug(deck.name)
        main_cards = [r for r in results if not r.version_of]
        alts = defaultdict(list)
        for r in results:
            if r.version_of:
                alts[r.version_of_id].append(r.card.name)
        tiers = Counter(r.tier for r in main_cards)
        kinds = Counter(f.kind for f in findings)
        tiles = "".join(
            f'<div class="tile t-{t}"><div class="v">{tiers.get(t, 0)}</div><div class="k">{TIER_LABEL[t]}</div></div>'
            for t in ("script", "engine", "manual", "reference") if t != "reference" or tiers.get(t))
        tiles += (f'<div class="tile t-err"><div class="v">{kinds.get("error", 0)}</div><div class="k">Data errors</div></div>'
                  f'<div class="tile t-q"><div class="v">{kinds.get("question", 0)}</div><div class="k">Questions</div></div>')
        rows = []
        for r in sorted(main_cards, key=lambda r: (["manual", "engine", "script", "reference"].index(r.tier), r.card.name)):
            c = r.card
            kw = ", ".join(r.keywords)
            more = alts.get(c.id)
            rows.append(
                f'<tr data-tier="{r.tier}"><td class="name">{html.escape(c.name)}<div class="tl">{html.escape(c.type_line.strip())}</div>'
                + (f'<div class="tl">Other versions: {html.escape(", ".join(more))}</div>' if more else "") + '</td>'
                f'<td><span class="pill p-{r.tier}">{TIER_LABEL[r.tier]}</span></td>'
                f'<td class="why">{html.escape("; ".join(r.reasons))}{"<div class=kw>Keywords: " + html.escape(kw) + "</div>" if kw else ""}</td></tr>')
        filt = "".join(f'<button class="f" data-tier="{t}">{TIER_LABEL[t]} ({tiers.get(t, 0)})</button>'
                       for t in ("script", "engine", "manual", "reference") if tiers.get(t))
        tabs.append(f'<button class="tab{" on" if i == 0 else ""}" data-panel="{slug}">{html.escape(deck.name)}</button>')
        panels.append(f'''
<div class="panel{" on" if i == 0 else ""}" id="{slug}">
  <p class="meta">{html.escape(deck.path.name)} · {len(main_cards)} cards{f" (+{len(results) - len(main_cards)} alternate versions)" if len(results) > len(main_cards) else ""} · commander: {html.escape(", ".join(deck.commander) or "none")}</p>
  <div class="tiles">{tiles}</div>
  {_section("error", findings, slug, "Fix in MSE Studio", "The data is wrong or incomplete. Any engine would trip over these.")}
  {_section("question", findings, slug, "Questions for you", "The wording is valid but could mean more than one thing. Type your ruling under each one; your answers stay in this browser until you copy them.")}
  {_section("info", findings, slug, "Good to know", "Nothing to fix.")}
  <section class="cards"><h3>Every card</h3>
    <p class="intro"><b>Forge script</b>: Forge's card language can express it today (the AI translation still has to be checked). <b>Needs engine code</b>: new Java in a Forge fork. <b>Manual</b>: a person resolves it. <b>Rules card</b>: a reference card, not played.</p>
    <div class="filters"><button class="f on" data-tier="">All ({len(main_cards)})</button>{filt}<input class="search" type="search" placeholder="Search cards"></div>
    <div class="tablewrap"><table><thead><tr><th>Card</th><th>Tier</th><th>Why</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
  </section>
</div>''')

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deck Check Report</title>
<style>
:root {{ --bg:#fbfaf7; --fg:#1d1c1a; --muted:#6b6862; --line:#e4e1da; --card:#ffffff;
  --script:#2f7d4f; --engine:#b26a00; --manual:#b3261e; --ref:#5f6b7a; --err:#b3261e; --q:#2d5bb5; --accent:#2d5bb5; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#161614; --fg:#ecebe7; --muted:#a19e97; --line:#33322e; --card:#1f1f1c;
  --script:#6cc28f; --engine:#f0a83a; --manual:#f28b82; --ref:#9aa7b6; --err:#f28b82; --q:#8ab4f8; --accent:#8ab4f8; }} }}
:root[data-theme="dark"] {{ --bg:#161614; --fg:#ecebe7; --muted:#a19e97; --line:#33322e; --card:#1f1f1c;
  --script:#6cc28f; --engine:#f0a83a; --manual:#f28b82; --ref:#9aa7b6; --err:#f28b82; --q:#8ab4f8; --accent:#8ab4f8; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif; }}
main {{ max-width:1080px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ font-size:22px; margin:0 0 4px }} h3 {{ font-size:17px; margin:28px 0 4px }}
.sub, .meta, .intro {{ color:var(--muted); margin:0 0 12px }}
.tabs {{ display:flex; gap:6px; flex-wrap:wrap; margin:16px 0 }}
.tab, .f, .copy {{ border:1px solid var(--line); background:var(--card); color:var(--fg); border-radius:999px; padding:6px 14px; font:inherit; cursor:pointer }}
.tab.on, .f.on {{ background:var(--fg); color:var(--bg); border-color:var(--fg) }}
.panel {{ display:none }} .panel.on {{ display:block }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:10px; margin:12px 0 }}
.tile {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px }}
.tile .v {{ font-size:26px; font-weight:650; font-variant-numeric:tabular-nums }} .tile .k {{ color:var(--muted); font-size:13px }}
.t-script .v {{ color:var(--script) }} .t-engine .v {{ color:var(--engine) }} .t-manual .v {{ color:var(--manual) }}
.t-reference .v {{ color:var(--ref) }} .t-err .v {{ color:var(--err) }} .t-q .v {{ color:var(--q) }}
details {{ background:var(--card); border:1px solid var(--line); border-radius:10px; margin:8px 0; padding:4px 14px }}
summary {{ cursor:pointer; padding:8px 0; font-weight:600 }}
.n {{ color:var(--muted); font-weight:400; font-variant-numeric:tabular-nums }}
ul {{ margin:0 0 10px; padding-left:18px }} li {{ margin:8px 0 }}
.card {{ font-weight:600 }} .fix {{ color:var(--muted); font-size:13.5px }}
.kind.error h3 {{ color:var(--err) }} .kind.question h3 {{ color:var(--q) }}
textarea.answer {{ display:block; width:100%; margin-top:6px; font:inherit; font-size:14px; padding:6px 8px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--fg); resize:vertical }}
.copybar {{ position:sticky; bottom:0; background:var(--bg); padding:10px 0; border-top:1px solid var(--line); display:flex; gap:10px; align-items:center }}
.copy {{ background:var(--accent); color:var(--bg); border-color:var(--accent) }}
.filters {{ display:flex; flex-wrap:wrap; gap:6px; margin:8px 0 }}
.search {{ flex:1 1 180px; min-width:0; font:inherit; padding:6px 12px; border:1px solid var(--line); border-radius:999px; background:var(--card); color:var(--fg) }}
.tablewrap {{ overflow-x:auto }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:10px }}
th, td {{ text-align:left; vertical-align:top; padding:8px 10px; border-bottom:1px solid var(--line) }}
th {{ font-size:13px; color:var(--muted); font-weight:600 }}
td.name {{ font-weight:600; min-width:170px }} .tl, .kw {{ color:var(--muted); font-weight:400; font-size:13px }}
td.why {{ font-size:14px }}
.pill {{ white-space:nowrap; font-size:12.5px; font-weight:600; padding:2px 8px; border-radius:999px; border:1px solid currentColor }}
.p-script {{ color:var(--script) }} .p-engine {{ color:var(--engine) }} .p-manual {{ color:var(--manual) }} .p-reference {{ color:var(--ref) }}
</style></head>
<body><main>
<h1>Deck check</h1>
<p class="sub">MSE Studio decks checked against Forge's rules engine · generated {generated}</p>
<div class="tabs">{"".join(tabs)}</div>
{"".join(panels)}
<div class="copybar"><button class="copy" id="copy">Copy my answers</button><span class="meta" id="copied"></span></div>
</main>
<script>
const store = {{ get(k) {{ try {{ return localStorage.getItem(k) }} catch (e) {{ return null }} }},
                set(k, v) {{ try {{ localStorage.setItem(k, v) }} catch (e) {{}} }} }};
document.querySelectorAll('.tab').forEach(b => b.onclick = () => {{
  document.querySelectorAll('.tab,.panel').forEach(e => e.classList.remove('on'));
  b.classList.add('on'); document.getElementById(b.dataset.panel).classList.add('on');
}});
document.querySelectorAll('.panel').forEach(p => {{
  const rows = [...p.querySelectorAll('tbody tr')], search = p.querySelector('.search');
  let tier = '';
  const apply = () => {{ const q = search.value.toLowerCase();
    rows.forEach(r => r.style.display = (!tier || r.dataset.tier === tier) && r.textContent.toLowerCase().includes(q) ? '' : 'none'); }};
  p.querySelectorAll('.f').forEach(b => b.onclick = () => {{
    p.querySelectorAll('.f').forEach(x => x.classList.remove('on')); b.classList.add('on'); tier = b.dataset.tier; apply(); }});
  search.oninput = apply;
}});
document.querySelectorAll('textarea.answer').forEach(t => {{
  t.value = store.get('deckcheck:' + t.dataset.q) || '';
  t.oninput = () => store.set('deckcheck:' + t.dataset.q, t.value);
}});
document.getElementById('copy').onclick = async () => {{
  const out = [];
  document.querySelectorAll('.panel').forEach(p => {{
    const qs = [...p.querySelectorAll('textarea.answer')].filter(t => t.value.trim());
    if (!qs.length) return;
    out.push('## ' + document.querySelector('[data-panel="' + p.id + '"]').textContent);
    qs.forEach(t => out.push('- Q: ' + t.dataset.text + '\\n  A: ' + t.value.trim()));
  }});
  const text = out.join('\\n') || '(no answers yet)';
  try {{ await navigator.clipboard.writeText(text); document.getElementById('copied').textContent = 'Copied — paste it into the chat.'; }}
  catch (e) {{ prompt('Copy your answers:', text); }}
}};
</script>
</body></html>'''
