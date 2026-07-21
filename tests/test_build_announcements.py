import json as _json

import pytest


def test_fetch_releases_uses_opener_and_parses(mod):
    calls = []

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload
        def read(self):
            return _json.dumps(self._payload).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    pages = [
        [{"name": "r1", "prerelease": False, "published_at": "2026-07-13T06:47:03Z", "body": ""}],
        [],  # empty page ends pagination
    ]

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return FakeResp(pages[len(calls) - 1])

    out = mod.fetch_releases("ublue-os/bazzite", "tok", urlopen=fake_urlopen)
    assert out[0]["name"] == "r1"
    assert "ublue-os/bazzite" in calls[0]


def test_module_imports(mod):
    assert hasattr(mod, "md_to_bbcode")
    assert hasattr(mod, "md_to_html")


def test_branch_config_stable(mod):
    assert mod.branch_config("stable") == (False, "rel")


def test_branch_config_testing(mod):
    assert mod.branch_config("testing") == (True, "beta")


def test_branch_config_unstable(mod):
    assert mod.branch_config("unstable") == (True, "preview")


def test_branch_config_unknown_raises(mod):
    with pytest.raises(ValueError):
        mod.branch_config("nope")


def test_select_releases_stable_only(mod, releases):
    out = mod.select_releases(releases, prerelease=False)
    assert out, "expected at least one stable release in fixture"
    assert all(r["prerelease"] is False for r in out)


def test_select_releases_prerelease_only(mod, releases):
    out = mod.select_releases(releases, prerelease=True)
    assert out, "expected at least one prerelease in fixture"
    assert all(r["prerelease"] is True for r in out)


def test_select_releases_sorted_desc(mod, releases):
    out = mod.select_releases(releases, prerelease=True)
    dates = [r["published_at"] for r in out]
    assert dates == sorted(dates, reverse=True)


def test_select_releases_drops_drafts(mod):
    data = [
        {"prerelease": False, "draft": True, "published_at": "2026-07-13T06:47:03Z"},
        {"prerelease": False, "draft": False, "published_at": "2026-07-12T06:47:03Z"},
    ]
    out = mod.select_releases(data, prerelease=False)
    assert len(out) == 1
    assert out[0]["published_at"] == "2026-07-12T06:47:03Z"


def test_select_releases_limit(mod, releases):
    out = mod.select_releases(releases, prerelease=True, limit=1)
    assert len(out) == 1


SAMPLE_BODY = """This is an automatically generated changelog for release `44.20260713`.

From previous `stable` version there have been the following changes.

### Major packages
| Name | Version |
| --- | --- |
| **Kernel** | 7.0.9 ➡️ 7.1.3 |

### Commits
| Hash | Subject | Author |
| --- | --- | --- |
| **abc123** | feat: do a thing | Someone |

### All Images
| | Name | Previous | New |
| --- | --- | --- | --- |
| 🔄 | 7zip | 26.01-1 | 26.02-1 |
"""


def test_extract_keeps_major_and_commits(mod):
    out = mod.extract_sections(SAMPLE_BODY)
    assert "### Major packages" in out
    assert "### Commits" in out
    assert "**Kernel**" in out
    assert "feat: do a thing" in out


def test_extract_drops_intro(mod):
    out = mod.extract_sections(SAMPLE_BODY)
    assert "automatically generated changelog" not in out


def test_extract_drops_all_images(mod):
    out = mod.extract_sections(SAMPLE_BODY)
    assert "### All Images" not in out
    assert "7zip" not in out


def test_extract_order_major_before_commits(mod):
    out = mod.extract_sections(SAMPLE_BODY)
    assert out.index("### Major packages") < out.index("### Commits")


def test_extract_missing_sections_returns_empty(mod):
    assert mod.extract_sections("just some text\n\n### All Images\n| a |\n") == ""


def test_extract_real_body(mod, stable_release):
    out = mod.extract_sections(stable_release["body"])
    assert "### All Images" not in out
    assert "### Major packages" in out or "### Commits" in out


def test_normalize_release_date(mod):
    date_str, ts = mod.normalize_release_date("2026-07-13T06:47:03Z")
    assert date_str == "2026-07-13 06:47"
    assert ts == 1783925223


def test_release_to_entry_fields(mod):
    release = {
        "name": "44.20260713: Stable (F44.20260713)",
        "tag_name": "44.20260713",
        "prerelease": False,
        "published_at": "2026-07-13T06:47:03Z",
        "body": SAMPLE_BODY,
    }
    e = mod.release_to_entry(release, "rel")
    assert e["title"] == "44.20260713: Stable (F44.20260713)"
    assert e["channel"] == "rel"
    assert e["lang"] == "english"
    assert e["date"] == "2026-07-13 06:47"
    assert isinstance(e["timestamp"], int)
    assert "### Major packages" in e["body"]
    assert "[b]Kernel[/b]" in e["bbcode_body"]
    assert "<strong>Kernel</strong>" in e["html_body"]
    assert list(e.keys()) == [
        "title", "date", "timestamp", "channel", "lang",
        "body", "bbcode_body", "html_body",
    ]


def test_release_to_entry_null_name_coalesces_to_empty_title(mod):
    release = {
        "name": None,
        "tag_name": "44.20260713",
        "prerelease": False,
        "published_at": "2026-07-13T06:47:03Z",
        "body": SAMPLE_BODY,
    }
    e = mod.release_to_entry(release, "rel")
    assert e["title"] == ""
