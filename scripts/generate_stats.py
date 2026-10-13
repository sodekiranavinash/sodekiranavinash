#!/usr/bin/env python3
"""Generate self-hosted GitHub stat cards for the profile README.

Runs in GitHub Actions (and locally) with only the Python standard library.
Data comes from the public GitHub REST API, so no personal access token is
required — a token is used only to raise the rate limit when one is present.

Outputs (written to ./assets):
    stats-dark.svg    stats-light.svg

The README embeds these with a <picture> element so the correct variant is
picked automatically from the viewer's colour scheme.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USER = os.environ.get("GH_USER", "sodekiranavinash")
API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": f"{USER}-profile-card",
    "X-GitHub-Api-Version": "2022-11-28",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

W = 495

THEMES = {
    "dark": {
        "bg": "#0D1117",
        "border": "#30363D",
        "title": "#E6EDF3",
        "muted": "#8B949E",
        "accent": "#22D3EE",
        "track": "#21262D",
        "palette": ["#22D3EE", "#A78BFA", "#7C3AED", "#0EA5E9", "#34D399", "#F472B6"],
    },
    "light": {
        "bg": "#FFFFFF",
        "border": "#D0D7DE",
        "title": "#1F2328",
        "muted": "#59636E",
        "accent": "#7C3AED",
        "track": "#EAEEF2",
        "palette": ["#0891B2", "#7C3AED", "#6D28D9", "#0284C7", "#059669", "#DB2777"],
    },
}


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def _request(url: str, accept: str | None = None) -> tuple[bytes, str]:
    headers = dict(HEADERS)
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def get_json(url: str, accept: str | None = None):
    body, _ = _request(url, accept)
    return json.loads(body.decode("utf-8"))


def get_binary(url: str) -> tuple[bytes, str]:
    return _request(url)


def safe(fn, default=None):
    try:
        return fn()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"  ! {exc}", file=sys.stderr)
        return default


# --------------------------------------------------------------------------- #
# Data collection
# --------------------------------------------------------------------------- #
def collect():
    print(f"→ fetching profile for {USER}")
    user = safe(lambda: get_json(f"{API}/users/{USER}"), {}) or {}

    print("→ fetching repositories")
    repos = safe(lambda: get_json(f"{API}/users/{USER}/repos?per_page=100&sort=pushed"), []) or []

    stars = sum(r.get("stargazers_count", 0) for r in repos)
    public_repos = user.get("public_repos", len(repos))

    print("→ fetching language byte counts")
    languages: dict[str, int] = {}
    for repo in repos:
        if repo.get("fork") or repo.get("language") is None:
            continue
        data = safe(
            lambda r=repo: get_json(f"{API}/repos/{USER}/{r['name']}/languages"),
            {},
        ) or {}
        for lang, count in data.items():
            languages[lang] = languages.get(lang, 0) + count

    print("→ fetching commit and pull-request totals")
    search_accept = "application/vnd.github.cloak-preview+json"
    commits = safe(
        lambda: get_json(f"{API}/search/commits?q=author:{USER}&per_page=1", search_accept),
        {},
    )
    commits = (commits or {}).get("total_count")

    prs = safe(
        lambda: get_json(f"{API}/search/issues?q=author:{USER}+type:pr&per_page=1"),
        {},
    )
    prs = (prs or {}).get("total_count")

    print("→ fetching avatar")
    avatar = safe(lambda: get_binary(f"{user.get('avatar_url', '')}&s=120"), None)

    return {
        "user": user,
        "stars": stars,
        "public_repos": public_repos,
        "commits": commits,
        "prs": prs,
        "languages": languages,
        "avatar": avatar,
    }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def fmt(value) -> str:
    return "—" if value is None else f"{value:,}"


def est_width(text: str, size: float = 11) -> float:
    return len(text) * size * 0.56


def render(theme_name: str, data: dict) -> str:
    t = THEMES[theme_name]
    user = data["user"]

    subtitle = "Applied AI Engineer · Agentic AI · MCP · RAG · AWS"

    metrics = [
        ("Repositories", fmt(data["public_repos"])),
        ("Commits", fmt(data["commits"])),
        ("Pull Requests", fmt(data["prs"])),
        ("Stars Earned", fmt(data["stars"])),
    ]

    # ----- language bar ----------------------------------------------------- #
    langs = sorted(data["languages"].items(), key=lambda kv: kv[1], reverse=True)
    total = sum(v for _, v in langs) or 1
    top = langs[:3]
    rest = sum(v for _, v in langs[3:])
    segments = [
        (name, count / total, t["palette"][i % len(t["palette"])])
        for i, (name, count) in enumerate(top)
    ]
    if rest:
        segments.append(("Other", rest / total, t["palette"][3 % len(t["palette"])]))

    bar_x, bar_y, bar_w, bar_h = 24, 206, W - 48, 10
    x_cursor = bar_x
    bars = []
    for i, (_name, frac, colour) in enumerate(segments):
        seg_w = bar_w * frac
        if i == len(segments) - 1:
            seg_w = bar_x + bar_w - x_cursor
        bars.append(
            f'<rect x="{x_cursor:.2f}" y="{bar_y}" width="{max(seg_w, 0):.2f}" '
            f'height="{bar_h}" fill="{colour}"/>'
        )
        x_cursor += seg_w

    # ----- legend (wraps if needed) ----------------------------------------- #
    legend = []
    lx = bar_x
    ly = 236
    for name, frac, colour in segments:
        label = f"{name} {frac * 100:.1f}%"
        chip_w = 14 + est_width(label) + 16
        if lx > bar_x and lx + chip_w - 16 > bar_x + bar_w:
            lx = bar_x
            ly += 18
        legend.append(f'<circle cx="{lx + 4}" cy="{ly - 4}" r="4" fill="{colour}"/>')
        legend.append(
            f'<text x="{lx + 14}" y="{ly}" font-size="11" fill="{t["muted"]}">{esc(label)}</text>'
        )
        lx += chip_w

    height = ly + 14

    # ----- avatar ----------------------------------------------------------- #
    avatar_defs = ""
    avatar_markup = ""
    if data["avatar"]:
        raw, ctype = data["avatar"]
        b64 = base64.b64encode(raw).decode("ascii")
        mime = (ctype or "image/jpeg").split(";")[0].strip() or "image/jpeg"
        avatar_defs = '<clipPath id="av"><circle cx="56" cy="56" r="28"/></clipPath>'
        avatar_markup = (
            f'<image x="28" y="28" width="56" height="56" clip-path="url(#av)" '
            f'preserveAspectRatio="xMidYMid slice" href="data:{mime};base64,{b64}" '
            f'xlink:href="data:{mime};base64,{b64}"/>'
            f'<circle cx="56" cy="56" r="28" fill="none" stroke="{t["border"]}" stroke-width="1.5"/>'
        )
    else:
        avatar_markup = (
            f'<circle cx="56" cy="56" r="28" fill="{t["track"]}"/>'
            f'<text x="56" y="63" font-size="20" font-weight="700" fill="{t["accent"]}" '
            f'text-anchor="middle">K</text>'
        )

    # ----- metric columns --------------------------------------------------- #
    col_w = (W - 48) / 4
    stats_markup = []
    for i, (label, value) in enumerate(metrics):
        cx = 24 + i * col_w
        stats_markup.append(
            f'<text x="{cx:.0f}" y="140" font-size="23" font-weight="700" '
            f'fill="{t["accent"]}">{esc(value)}</text>'
        )
        stats_markup.append(
            f'<text x="{cx:.0f}" y="160" font-size="11" fill="{t["muted"]}" '
            f'letter-spacing="0.4">{esc(label.upper())}</text>'
        )

    updated = datetime.now(timezone.utc).strftime("%d %b %Y")

    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{height}" viewBox="0 0 {W} {height}" role="img" aria-label="GitHub statistics for {esc(USER)}">
<title>GitHub statistics for {esc(USER)}</title>
<defs>
  <clipPath id="bar"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="5"/></clipPath>
  {avatar_defs}
</defs>
<rect x="0.5" y="0.5" width="{W - 1}" height="{height - 1}" rx="12" fill="{t['bg']}" stroke="{t['border']}"/>
{avatar_markup}
<text x="98" y="49" font-size="18" font-weight="700" fill="{t['title']}">{esc(user.get('name') or USER)}</text>
<text x="98" y="70" font-size="12" fill="{t['muted']}">{esc(subtitle)}</text>
<text x="{W - 24}" y="49" font-size="12" fill="{t['accent']}" text-anchor="end">@{esc(USER)}</text>
<line x1="24" y1="98" x2="{W - 24}" y2="98" stroke="{t['border']}"/>
{''.join(stats_markup)}
<line x1="24" y1="180" x2="{W - 24}" y2="180" stroke="{t['border']}"/>
<text x="24" y="199" font-size="11" font-weight="700" fill="{t['muted']}" letter-spacing="1">TOP LANGUAGES</text>
<g clip-path="url(#bar)">
  <rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" fill="{t['track']}"/>
  {''.join(bars)}
</g>
{''.join(legend)}
<text x="{W - 24}" y="{height - 8}" font-size="9" fill="{t['muted']}" text-anchor="end" opacity="0.75">updated {updated} · generated in GitHub Actions</text>
</svg>
'''


# --------------------------------------------------------------------------- #
def main() -> int:
    data = collect()
    OUT.mkdir(parents=True, exist_ok=True)

    changed = []
    for theme in THEMES:
        path = OUT / f"stats-{theme}.svg"
        svg = render(theme, data)
        # Pretty, stable output so the commit diff is readable.
        if not path.exists() or path.read_text(encoding="utf-8") != svg:
            path.write_text(svg, encoding="utf-8")
            changed.append(path.name)
            print(f"✓ wrote {path.relative_to(ROOT)}")
        else:
            print(f"= unchanged {path.relative_to(ROOT)}")

    print("changed:", ", ".join(changed) or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
