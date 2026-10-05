import os

from promo import home


def test_projects_dir_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMO_CONFIG", str(tmp_path / "c.yaml"))
    monkeypatch.setenv("PROMO_PROJECTS", str(tmp_path / "ext"))
    assert home.projects_dir() == str(tmp_path / "ext")


def test_config_then_default(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMO_PROJECTS", raising=False)
    monkeypatch.setenv("PROMO_CONFIG", str(tmp_path / "c.yaml"))
    assert home.projects_dir() == os.path.join(home.REPO, "projects")
    home.main(["projects-dir", str(tmp_path / "mine")])
    assert home.projects_dir() == str(tmp_path / "mine")


def test_resolve_name_legacy_and_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMO_PROJECTS", str(tmp_path))
    (tmp_path / "p1").mkdir()
    (tmp_path / "p1" / "promo.yaml").write_text("x: 1")
    monkeypatch.chdir(tmp_path / "p1")
    assert home.resolve("p1") == str(tmp_path / "p1")
    assert home.resolve("projects/p1") == str(tmp_path / "p1")        # legacy doc commands keep working
    assert home.resolve("promo.yaml") == "promo.yaml"                  # existing relative path wins
    assert home.resolve("nope") == "nope"
    assert [p["name"] for p in home.list_projects()] == ["p1"]


def test_heavy_lock_path_env_then_config_then_default(tmp_path, monkeypatch, capsys):
    from promo import lock
    monkeypatch.setenv("PROMO_CONFIG", str(tmp_path / "c.yaml"))
    monkeypatch.delenv("PROMO_HEAVY_LOCK", raising=False)
    assert lock.DEFAULT == "/tmp/promo-reel-heavy.lock" and "cargo" not in lock.DEFAULT
    assert lock.lock_path() == lock.DEFAULT                                  # default
    assert home.main(["heavy-lock", str(tmp_path / "cfg.lock")]) == 0        # `promo config heavy-lock PATH`
    assert lock.lock_path() == str(tmp_path / "cfg.lock")                    # config beats default
    capsys.readouterr()
    home.main(["heavy-lock"])
    assert capsys.readouterr().out.strip() == str(tmp_path / "cfg.lock")     # show form
    monkeypatch.setenv("PROMO_HEAVY_LOCK", str(tmp_path / "env.lock"))
    assert lock.lock_path() == str(tmp_path / "env.lock")                    # env beats config
