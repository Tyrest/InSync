from app.version import get_app_version


def test_app_version_is_non_empty() -> None:
    v = get_app_version()
    assert isinstance(v, str)
    assert len(v) > 0
