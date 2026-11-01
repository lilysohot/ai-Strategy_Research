"""Unit tests for the origin-level negative scrape cache (``_ScrapeCache``).

The host-level ban semantics exist so sibling agents stop re-hammering the same
blocked domain (e.g. ``zhihu.com/p/A`` then ``zhihu.com/p/B``) — a 403/429 on
one path must suppress every other path on that host for the ban window.
"""

from plugins.tools._scrape_cache import (
    _BAN_403,
    _ScrapeCache,
    _domain_of,
    format_skip_message,
)


def test_domain_of_extracts_netloc():
    assert _domain_of("https://zhuanlan.zhihu.com/p/2099987320443237060") == "zhuanlan.zhihu.com"
    assert _domain_of("https://raw.githubusercontent.com/a/b/README.md") == "raw.githubusercontent.com"
    assert _domain_of("http://127.0.0.1:8899/v1") == "127.0.0.1:8899"


def test_domain_of_lowercases_and_strips_userinfo():
    assert _domain_of("https://ZHIHU.com/a") == "zhihu.com"
    assert _domain_of("https://user:pass@Example.COM/path") == "example.com"


def test_domain_of_falls_back_for_opaque():
    assert _domain_of("") == ""
    assert _domain_of("not a url") == "not a url"


def test_sibling_paths_share_ban():
    cache = _ScrapeCache()
    t0 = 1_000_000.0
    cache.record_failure("https://zhuanlan.zhihu.com/p/111", 403, now=t0)
    # A *different* path on the same host is now banned too.
    assert cache.check("https://zhuanlan.zhihu.com/p/222", now=t0 + 10) is not None


def test_different_domains_isolated():
    cache = _ScrapeCache()
    t0 = 1_000_000.0
    cache.record_failure("https://zhihu.com/p/1", 403, now=t0)
    assert cache.check("https://example.com/p/1", now=t0 + 10) is None


def test_case_insensitive_domain():
    cache = _ScrapeCache()
    t0 = 1_000_000.0
    cache.record_failure("https://ZHIHU.com/p/1", 403, now=t0)
    assert cache.check("https://zhihu.com/p/2", now=t0 + 10) is not None


def test_ban_expires():
    cache = _ScrapeCache()
    t0 = 1_000_000.0
    cache.record_failure("https://zhihu.com/p/1", 403, now=t0)
    # 403 ban lasts _BAN_403; just past expiry it is clear again.
    assert cache.check("https://zhihu.com/p/1", now=t0 + _BAN_403 + 1) is None


def test_record_success_clears_domain():
    cache = _ScrapeCache()
    t0 = 1_000_000.0
    cache.record_failure("https://zhihu.com/p/1", 403, now=t0)
    cache.record_success("https://zhihu.com/p/other")
    assert cache.check("https://zhihu.com/p/1", now=t0 + 10) is None


def test_429_bans_on_first_failure():
    cache = _ScrapeCache()
    t0 = 1_000_000.0
    cache.record_failure("https://api.example.com/v1", 429, now=t0)
    assert cache.check("https://api.example.com/v2", now=t0 + 10) is not None


def test_format_skip_message_names_domain():
    cache = _ScrapeCache()
    t0 = 1_000_000.0
    entry = cache.record_failure("https://zhuanlan.zhihu.com/p/111", 403, now=t0)
    msg = format_skip_message("https://zhuanlan.zhihu.com/p/222", entry, now=t0 + 10)
    assert "zhuanlan.zhihu.com" in msg
    assert "Domain skipped" in msg
