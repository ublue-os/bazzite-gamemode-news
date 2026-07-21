#!/usr/bin/env python3

import html
import json
import os
import re
import urllib.request
from datetime import datetime, timezone

MAX_ENTRIES = 20
ROOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUTPUT_FILE = os.path.join(ROOT_DIR, "announcements.json")
DOCS_DIR = os.path.join(ROOT_DIR, "docs")
HTML_FILE = os.path.join(DOCS_DIR, "index.html")

SOURCE_REPO = os.environ.get("SOURCE_REPO", "ublue-os/bazzite")

# branch -> (prerelease_filter, channel)
BRANCH_CONFIG = {
    "stable": (False, "rel"),
    "testing": (True, "beta"),
    "unstable": (True, "preview"),
}


def branch_config(branch):
    """Return (prerelease, channel) for a git branch, or raise ValueError."""
    if branch not in BRANCH_CONFIG:
        raise ValueError(f"unknown branch: {branch!r} (expected one of {sorted(BRANCH_CONFIG)})")
    return BRANCH_CONFIG[branch]


def select_releases(releases, prerelease, limit=MAX_ENTRIES):
    """Filter releases by prerelease flag, drop drafts, sort newest-first, cap at limit."""
    kept = [
        r for r in releases
        if bool(r.get("prerelease")) == prerelease and not r.get("draft")
    ]
    kept.sort(key=lambda r: r.get("published_at") or "", reverse=True)
    return kept[:limit]


KEEP_SECTIONS = {"Major packages", "Commits"}


def extract_sections(body):
    """Keep only allowlisted '### <heading>' sections from a release body."""
    lines = (body or "").split("\n")
    result = []
    keeping = False
    for line in lines:
        m = re.match(r"^#{1,6}\s+(.*)", line.strip())
        if m:
            keeping = m.group(1).strip() in KEEP_SECTIONS
        if keeping:
            result.append(line)
    return "\n".join(result).strip()


def normalize_release_date(published_at):
    """Parse GitHub ISO-8601 UTC timestamp into (display_str, unix_ts)."""
    dt = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M"), int(dt.timestamp())


def release_to_entry(release, channel):
    """Convert a GitHub release dict into an announcement entry."""
    body = extract_sections(release.get("body", ""))
    date_str, timestamp = normalize_release_date(release["published_at"])
    return {
        "title": release.get("name") or "",
        "date": date_str,
        "timestamp": timestamp,
        "channel": channel,
        "lang": "english",
        "body": body,
        "bbcode_body": md_to_bbcode(body),
        "html_body": md_to_html(body),
    }


def fetch_releases(repo, token, urlopen=None):
    """Fetch all releases for a repo (paginated), newest first. stdlib only."""
    opener = urlopen or urllib.request.urlopen
    results = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}"
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "bazzite-gamemode-news")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with opener(req, timeout=30) as resp:
            batch = json.loads(resp.read().decode("utf-8"))
        if not batch:
            break
        results.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return results


def _is_table_row(line):
    """Check if a line is a Markdown table row (| ... | ... |)."""
    return bool(re.match(r"^\|.*\|$", line.strip()))


def _is_table_separator(line):
    """Check if a line is a Markdown table separator (|---|---|)."""
    return bool(re.match(r"^\|[-:\s|]+\|$", line.strip()))


def _parse_table_cells(line):
    """Extract cell contents from a Markdown table row."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def md_to_bbcode(text):
    """Convert Markdown to Steam BBCode."""
    lines = text.split("\n")
    result = []
    in_ul = False
    in_ol = False
    in_quote = False
    in_code_block = False
    in_table = False
    table_header_done = False

    for line in lines:
        stripped = line.strip()

        # Fenced code block
        if stripped.startswith("```"):
            if in_code_block:
                result.append("[/code]")
                in_code_block = False
            else:
                in_code_block = True
                result.append("[code]")
            continue
        if in_code_block:
            result.append(line.rstrip())
            continue

        # Table
        if _is_table_row(stripped):
            if _is_table_separator(stripped):
                continue
            cells = _parse_table_cells(stripped)
            if not in_table:
                result.append("[table]")
                in_table = True
                table_header_done = False
            tag = "th" if not table_header_done else "td"
            row = "[tr]" + "".join(f"[{tag}]{c}[/{tag}]" for c in cells) + "[/tr]"
            result.append(row)
            if not table_header_done:
                table_header_done = True
            continue
        elif in_table:
            result.append("[/table]")
            in_table = False

        # Unordered list
        if re.match(r"^[-*]\s+", stripped):
            if in_ol:
                result.append("[/olist]")
                in_ol = False
            item = re.sub(r"^[-*]\s+", "", stripped)
            if not in_ul:
                result.append("[list]")
                in_ul = True
            result.append(f"[*] {item}")
            continue
        elif in_ul:
            result.append("[/list]")
            in_ul = False

        # Ordered list
        if re.match(r"^\d+\.\s+", stripped):
            if in_ul:
                result.append("[/list]")
                in_ul = False
            item = re.sub(r"^\d+\.\s+", "", stripped)
            if not in_ol:
                result.append("[olist]")
                in_ol = True
            result.append(f"[*] {item}")
            continue
        elif in_ol:
            result.append("[/olist]")
            in_ol = False

        # Blockquote
        if stripped.startswith("> "):
            content = stripped[2:]
            if not in_quote:
                result.append("[quote]")
                in_quote = True
            result.append(content)
            continue
        elif in_quote:
            result.append("[/quote]")
            in_quote = False

        # Horizontal rule
        if re.match(r"^[-*_]{3,}$", stripped):
            result.append("[hr][/hr]")
            continue

        # Heading
        m = re.match(r"^(#{1,3})\s+(.*)", stripped)
        if m:
            level = len(m.group(1))
            tag = f"h{level}"
            result.append(f"[{tag}]{m.group(2)}[/{tag}]")
            continue

        result.append(stripped)

    if in_table:
        result.append("[/table]")
    if in_ul:
        result.append("[/list]")
    if in_ol:
        result.append("[/olist]")
    if in_quote:
        result.append("[/quote]")
    if in_code_block:
        result.append("[/code]")

    text = "\n".join(result)
    # Protect [*] list markers from being caught by italic regex
    text = text.replace("[*]", "\x00LI\x00")
    # Images before links (![alt](url) vs [text](url))
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"[img]\2[/img]", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"[url=\2]\1[/url]", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"[b]\1[/b]", text)
    text = re.sub(r"__(.+?)__", r"[u]\1[/u]", text)
    text = re.sub(r"\*(.+?)\*", r"[i]\1[/i]", text)
    text = re.sub(r"~~(.+?)~~", r"[strike]\1[/strike]", text)
    text = re.sub(r"(?<!`)`([^`]+)`(?!`)", r"[code]\1[/code]", text)
    text = text.replace("\x00LI\x00", "[*]")
    return text


def md_to_html(text):
    """Convert Markdown to HTML."""
    lines = text.split("\n")
    result = []
    in_ul = False
    in_ol = False
    in_quote = False
    in_code_block = False
    in_table = False
    table_header_done = False

    for line in lines:
        stripped = line.strip()

        # Fenced code block
        if stripped.startswith("```"):
            if in_code_block:
                result.append("</code></pre>")
                in_code_block = False
            else:
                in_code_block = True
                result.append("<pre><code>")
            continue
        if in_code_block:
            result.append(html.escape(line.rstrip()))
            continue

        # Table
        if _is_table_row(stripped):
            if _is_table_separator(stripped):
                continue
            cells = _parse_table_cells(stripped)
            if not in_table:
                result.append("<table>")
                in_table = True
                table_header_done = False
            tag = "th" if not table_header_done else "td"
            row = "<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells) + "</tr>"
            result.append(row)
            if not table_header_done:
                table_header_done = True
            continue
        elif in_table:
            result.append("</table>")
            in_table = False

        # Unordered list
        if re.match(r"^[-*]\s+", stripped):
            if in_ol:
                result.append("</ol>")
                in_ol = False
            item = re.sub(r"^[-*]\s+", "", stripped)
            if not in_ul:
                result.append("<ul>")
                in_ul = True
            result.append(f"<li>{html.escape(item)}</li>")
            continue
        elif in_ul:
            result.append("</ul>")
            in_ul = False

        # Ordered list
        if re.match(r"^\d+\.\s+", stripped):
            if in_ul:
                result.append("</ul>")
                in_ul = False
            item = re.sub(r"^\d+\.\s+", "", stripped)
            if not in_ol:
                result.append("<ol>")
                in_ol = True
            result.append(f"<li>{html.escape(item)}</li>")
            continue
        elif in_ol:
            result.append("</ol>")
            in_ol = False

        # Blockquote
        if stripped.startswith("> "):
            content = stripped[2:]
            if not in_quote:
                result.append("<blockquote>")
                in_quote = True
            result.append(html.escape(content))
            continue
        elif in_quote:
            result.append("</blockquote>")
            in_quote = False

        # Horizontal rule
        if re.match(r"^[-*_]{3,}$", stripped):
            result.append("<hr>")
            continue

        # Heading
        m = re.match(r"^(#{1,3})\s+(.*)", stripped)
        if m:
            level = len(m.group(1))
            result.append(f"<h{level}>{html.escape(m.group(2))}</h{level}>")
            continue

        if stripped:
            result.append(f"<p>{html.escape(stripped)}</p>")
        else:
            result.append("")

    if in_table:
        result.append("</table>")
    if in_ul:
        result.append("</ul>")
    if in_ol:
        result.append("</ol>")
    if in_quote:
        result.append("</blockquote>")
    if in_code_block:
        result.append("</code></pre>")

    text = "\n".join(result)
    # Images before links
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)",
        r'<img src="\2" alt="\1" style="max-width:100%">',
        text,
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        text,
    )
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<u>\1</u>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"~~(.+?)~~", r"<del>\1</del>", text)
    text = re.sub(r"(?<!`)`([^`]+)`(?!`)", r"<code>\1</code>", text)
    # unescape HTML tags generated by inline formatting inside escaped <p>/<li>/<td>/<th>
    text = re.sub(
        r"&lt;(/?(?:strong|em|del|u|a|code|img|ul|ol|li|blockquote|pre|h[1-3]|hr|table|tr|td|th)(?:\s[^>]*)?)&gt;",
        r"<\1>",
        text,
    )
    return text


def main():
    branch = os.environ.get("RELEASE_BRANCH", "").strip()
    prerelease, channel = branch_config(branch)
    token = os.environ.get("GITHUB_TOKEN") or None

    releases = fetch_releases(SOURCE_REPO, token)
    selected = select_releases(releases, prerelease, MAX_ENTRIES)
    entries = [release_to_entry(r, channel) for r in selected]

    out_file = os.path.normpath(OUTPUT_FILE)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Generated {out_file}: {len(entries)} entries "
          f"from {len(releases)} releases (branch={branch}, channel={channel})")

    generate_html(entries)
    print(f"Generated {HTML_FILE}")


def generate_html(entries):
    """Build a static HTML page from announcement entries."""
    os.makedirs(DOCS_DIR, exist_ok=True)

    # Collect available languages and channels from data
    langs = sorted({e["lang"] for e in entries if e["lang"]})
    data_channels = {e["channel"] for e in entries if e["channel"]}
    channels = [ch for ch in CHANNEL_LABELS if ch in data_channels]

    data_json = json.dumps(entries, ensure_ascii=False)

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(_html_template(data_json, langs, channels))


CHANNEL_LABELS = {
    "rel": {"en": "Stable", "zh": "稳定版"},
    "beta": {"en": "Beta", "zh": "测试版"},
    "preview": {"en": "Preview", "zh": "预览版"},
    "main": {"en": "Super Preview", "zh": "超级前瞻版"},
}

CHANNEL_COLORS = {
    "rel": "#4caf50",
    "beta": "#ff9800",
    "preview": "#f44336",
    "main": "#e40336",
}

LANG_LABELS = {
    "schinese": "简体中文",
    "tchinese": "繁體中文",
    "english": "English",
    "japanese": "日本語",
    "koreana": "한국어",
}


def _html_template(data_json, langs, channels):
    # Build channel tab HTML
    channel_tabs = ""
    for ch in channels:
        label_en = CHANNEL_LABELS.get(ch, {}).get("en", ch)
        label_zh = CHANNEL_LABELS.get(ch, {}).get("zh", ch)
        color = CHANNEL_COLORS.get(ch, "#9e9e9e")
        channel_tabs += (
            f'<button class="tab" data-channel="{ch}" '
            f'data-label-en="{label_en}" data-label-zh="{label_zh}" '
            f'style="--ch-color:{color}">{label_zh}</button>\n'
        )

    # Build language option HTML
    lang_options = ""
    for lang in langs:
        label = LANG_LABELS.get(lang, lang)
        lang_options += (
            f'<option value="{lang}" data-label-en="{label}" '
            f'data-label-zh="{label}">{label}</option>\n'
        )

    return f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SkorionOS Updates</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f1923;color:#c7d5e0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;line-height:1.6;min-height:100vh}}
.container{{max-width:720px;margin:0 auto;padding:24px 16px}}
header{{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:24px}}
h1{{font-size:1.5rem;color:#fff;font-weight:700;letter-spacing:.5px}}
.lang-wrap{{display:flex;align-items:center;gap:6px;background:#1b2838;border:1px solid #2a475e;border-radius:6px;padding:4px 8px}}
.lang-wrap:focus-within{{border-color:#66c0f4}}
.lang-icon{{color:#8f98a0;flex-shrink:0}}
.lang-select{{background:transparent;color:#c7d5e0;border:none;font-size:.85rem;cursor:pointer;outline:none}}
.tabs{{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}}
.tab{{background:transparent;color:#8f98a0;border:1px solid #2a475e;border-radius:20px;padding:6px 16px;font-size:.85rem;cursor:pointer;transition:all .2s}}
.tab:hover{{border-color:#66c0f4;color:#c7d5e0}}
.tab.active{{background:var(--ch-color,#66c0f4);color:#fff;border-color:var(--ch-color,#66c0f4)}}
.tab[data-channel="all"]{{--ch-color:#66c0f4}}
.cards{{display:flex;flex-direction:column;gap:16px}}
.card{{background:#1b2838;border:1px solid #2a475e;border-radius:10px;padding:20px;transition:border-color .2s}}
.card:hover{{border-color:#66c0f4}}
.card-header{{display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap}}
.card-title{{font-size:1.1rem;color:#fff;font-weight:600}}
.badge{{font-size:.75rem;padding:2px 10px;border-radius:10px;color:#fff;font-weight:500;white-space:nowrap}}
.card-date{{font-size:.8rem;color:#8f98a0;margin-left:auto}}
.card-body{{color:#acb2b8;font-size:.9rem}}
.card-body strong{{color:#c7d5e0}}
.card-body ul,.card-body ol{{padding-left:20px;margin:6px 0}}
.card-body li{{margin:3px 0}}
.card-body p{{margin:6px 0}}
.card-body a{{color:#66c0f4;text-decoration:none}}
.card-body a:hover{{text-decoration:underline}}
.card-body table{{border-collapse:collapse;margin:8px 0;width:100%}}
.card-body th,.card-body td{{border:1px solid #2a475e;padding:6px 12px;text-align:left}}
.card-body th{{background:#1e2a3a;color:#c7d5e0;font-weight:600}}
.empty{{text-align:center;color:#8f98a0;padding:40px 0;font-size:.95rem}}
footer{{text-align:center;color:#4a5568;font-size:.75rem;margin-top:40px;padding:20px 0;border-top:1px solid #1b2838}}
</style>
</head>
<body>
<div class="container">
<header>
  <h1>SkorionOS Updates</h1>
  <div class="lang-wrap"><svg class="lang-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10A15.3 15.3 0 0 1 12 2z"/></svg><select class="lang-select" id="langSelect">
    <option value="all" data-label-en="All Languages" data-label-zh="所有语言">所有语言</option>
    {lang_options}
  </select></div>
</header>
<div class="tabs" id="tabs">
  <button class="tab active" data-channel="all" data-label-en="All" data-label-zh="全部" style="--ch-color:#66c0f4">全部</button>
  {channel_tabs}
</div>
<div class="cards" id="cards"></div>
<div class="empty" id="empty" style="display:none">No announcements / 暂无公告</div>
<footer>SkorionOS &copy; 2026</footer>
</div>
<script>
var DATA={data_json};
var CHANNEL_LABELS={json.dumps(CHANNEL_LABELS, ensure_ascii=False)};
var LANG_LABELS={json.dumps(LANG_LABELS, ensure_ascii=False)};
var BROWSER_LANG_MAP={{
  "zh":"schinese","zh-cn":"schinese","zh-hans":"schinese",
  "zh-tw":"tchinese","zh-hk":"tchinese","zh-hant":"tchinese",
  "en":"english","ja":"japanese","ko":"koreana",
  "de":"german","fr":"french","es":"spanish","pt":"portuguese",
  "pt-br":"brazilian","ru":"russian","it":"italian","nl":"dutch",
  "pl":"polish","tr":"turkish","vi":"vietnamese","th":"thai",
  "sv":"swedish","fi":"finnish","da":"danish","nb":"norwegian","no":"norwegian",
  "hu":"hungarian","cs":"czech","ro":"romanian","bg":"bulgarian",
  "el":"greek","uk":"ukrainian","id":"indonesian","ms":"indonesian"
}};
var AVAILABLE_LANGS={{}};
for(var i=0;i<DATA.length;i++) if(DATA[i].lang) AVAILABLE_LANGS[DATA[i].lang]=1;

function detectBrowserLang(){{
  var langs=navigator.languages||[navigator.language||""];
  for(var i=0;i<langs.length;i++){{
    var tag=langs[i].toLowerCase();
    if(tag.startsWith("zh")) return "zh";
  }}
  return "en";
}}

function detectContentLang(){{
  var langs=navigator.languages||[navigator.language||""];
  for(var i=0;i<langs.length;i++){{
    var tag=langs[i].toLowerCase();
    var match=BROWSER_LANG_MAP[tag]||BROWSER_LANG_MAP[tag.split("-")[0]];
    if(match&&AVAILABLE_LANGS[match]) return match;
  }}
  return "all";
}}

var curChannel="all",curLang=detectContentLang();
document.getElementById("langSelect").value=curLang;

var ZH_LANGS={{"schinese":1,"tchinese":1}};
function getUILang(){{
  if(curLang==="all") return detectBrowserLang();
  return ZH_LANGS[curLang]?"zh":"en";
}}

function chLabel(labels){{var ui=getUILang();return ui==="zh"?(labels.zh||labels.en||""):(labels.en||labels.zh||"");}}

function updateUILang(){{
  var ui=getUILang();
  document.querySelectorAll(".tab").forEach(function(t){{
    var en=t.dataset.labelEn,zh=t.dataset.labelZh;
    t.textContent=ui==="zh"?(zh||en):(en||zh);
  }});
  var sel=document.getElementById("langSelect");
  for(var i=0;i<sel.options.length;i++){{
    var o=sel.options[i];
    if(o.dataset.labelEn) o.textContent=ui==="zh"?(o.dataset.labelZh||o.dataset.labelEn):(o.dataset.labelEn||o.dataset.labelZh);
  }}
}}
updateUILang();

function render(){{
  var cards=document.getElementById("cards");
  cards.innerHTML="";
  var count=0;
  for(var i=0;i<DATA.length;i++){{
    var e=DATA[i];
    if(curChannel!=="all"&&e.channel!==curChannel) continue;
    if(curLang!=="all"&&e.lang&&e.lang!==curLang) continue;
    count++;
    var ch=e.channel||"";
    var labels=CHANNEL_LABELS[ch]||{{}};
    var labelText=chLabel(labels)||ch;
    var color={json.dumps(CHANNEL_COLORS)};
    var c=document.createElement("div");
    c.className="card";
    c.innerHTML='<div class="card-header">'
      +'<span class="card-title">'+esc(e.title)+'</span>'
      +(ch?'<span class="badge" style="background:'+(color[ch]||"#9e9e9e")+'">'+esc(labelText)+'</span>':'')
      +'<span class="card-date">'+esc(e.date.split(" ")[0])+'</span>'
      +'</div>'
      +'<div class="card-body">'+e.html_body+'</div>';
    cards.appendChild(c);
  }}
  document.getElementById("empty").style.display=count?"none":"block";
}}

function esc(s){{var d=document.createElement("span");d.textContent=s;return d.innerHTML;}}

document.getElementById("tabs").addEventListener("click",function(ev){{
  var btn=ev.target.closest(".tab");
  if(!btn) return;
  curChannel=btn.dataset.channel;
  document.querySelectorAll(".tab").forEach(function(t){{t.classList.remove("active")}});
  btn.classList.add("active");
  render();
}});

document.getElementById("langSelect").addEventListener("change",function(){{
  curLang=this.value;
  updateUILang();
  render();
}});

render();
</script>
</body>
</html>'''


if __name__ == "__main__":
    main()
