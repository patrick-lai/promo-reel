"""A failure whose cause is a missing local example project (see tests/localproj.py) is a skip, not a failure."""
import os

import pytest

import localproj


@pytest.fixture(autouse=True)
def _private_config(tmp_path, monkeypatch):
    """`promo flow init` remembers every flow in the config dir; tests must not add their throwaway projects to the person's real list, and flow
    commands must not publish test projects to the Stage of the CommissionAI thread the tests happen to run in."""
    monkeypatch.setenv("PROMO_CONFIG", str(tmp_path / "promo-config" / "config.yaml"))
    monkeypatch.setenv("PROMO_FLOW_PUBLISH", "0")


@pytest.fixture
def sheets(monkeypatch):
    """Blind comparison sheets without ffmpeg: one PNG per order."""
    from PIL import Image
    from promo import compare_ref as CR

    def sheet(a, b, out, *args, **kw):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        Image.new("RGB", (320, 180), (40, 40, 40)).save(out)
        return out
    monkeypatch.setattr(CR, "sheet", sheet)


def _mentions_missing(exc, seen=None):
    seen = seen or set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if localproj.MISSING in " ".join(str(a) for a in exc.args) or localproj.MISSING in str(getattr(exc, "filename", "") or ""):
            return True
        if _mentions_missing(exc.__cause__, seen) or _mentions_missing(exc.__context__, seen):
            return True
        return False
    return False


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    out = yield
    rep = out.get_result()
    if rep.failed and call.excinfo is not None and _mentions_missing(call.excinfo.value):
        rep.outcome = "skipped"
        rep.longrepr = (str(item.fspath), item.location[1] or 0, "Skipped: needs a local example project (see tests/localproj.py)")
