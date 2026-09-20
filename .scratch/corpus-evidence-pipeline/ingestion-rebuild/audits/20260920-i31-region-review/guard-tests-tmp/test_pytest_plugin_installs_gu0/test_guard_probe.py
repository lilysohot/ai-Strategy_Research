def test_guard_active_before_collection() -> None:
    from plugins.corpus.preparation import guard
    st = guard.state()
    assert st is not None and st.config.phase == 'i0-inventory'
    try:
        import openai  # noqa: F401
    except ImportError as exc:
        assert 'corpus preparation guard' in str(exc)
    else:
        raise AssertionError('openai import must be refused')
