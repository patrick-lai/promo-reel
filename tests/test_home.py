import os
import subprocess

import pytest

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


GIT_ENV = dict(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env={**os.environ, **GIT_ENV})


def repo_named(tmp_path, name):
    r = tmp_path / name
    (r / "src").mkdir(parents=True)
    git(r, "init", "-q")
    git(r, "commit", "-q", "--allow-empty", "-m", "x")
    return r


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A user with an empty config, their own home folder and no PROMO_PROJECTS."""
    monkeypatch.setenv("PROMO_CONFIG", str(tmp_path / "c.yaml"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PROMO_PROJECTS", raising=False)
    return tmp_path


def test_home_preset_names_the_folder_after_the_repo(box, monkeypatch):
    monkeypatch.chdir(repo_named(box, "shop") / "src")
    assert home.main(["output", "home"]) == 0
    assert home.project_dir("launch") == str(box / "home" / ".promo-reel" / "shop" / "launch")


def test_repo_preset_is_relative_to_the_repo_root_not_the_cwd(box, monkeypatch):
    repo = repo_named(box, "shop")
    monkeypatch.chdir(repo / "src")
    home.main(["output", "repo"])
    assert home.project_dir("launch") == str(repo / "promo-reel" / "launch")


def test_a_worktree_uses_its_main_checkouts_name(box, monkeypatch):
    repo = repo_named(box, "shop")
    git(repo, "worktree", "add", "-q", str(box / "wt-9f3a"))
    monkeypatch.chdir(box / "wt-9f3a")
    home.main(["output", "home"])
    assert home.project_dir("launch") == str(box / "home" / ".promo-reel" / "shop" / "launch")


def test_any_folder_with_tokens_and_slug_added_when_missing(box, monkeypatch):
    monkeypatch.chdir(repo_named(box, "shop"))
    home.main(["output", str(box / "drive" / "{project}")])
    assert home.project_dir("launch") == str(box / "drive" / "shop" / "launch")
    home.main(["output", str(box / "drive" / "{slug}")])
    assert home.project_dir("launch") == str(box / "drive" / "launch")


def test_default_clears_the_choice_and_env_beats_config(box, monkeypatch):
    home.main(["output", "home"])
    assert home.output_template()[1] == "config"
    home.main(["output", "default"])
    assert home.output_template() == (os.path.join(home.REPO, "projects", "{slug}"), "default")
    home.main(["output", "home"])
    monkeypatch.setenv("PROMO_PROJECTS", str(box / "ext"))
    assert home.output_template() == (str(box / "ext" / "{slug}"), "env")


@pytest.mark.parametrize("bad", ["  ","~/x/{slug}/more", "~/x/{who}/{slug}", '~/x"y', "~/x/$HOME", "~/x/{slug}/{slug}"])
def test_a_bad_location_is_refused_and_nothing_is_saved(box, bad, capsys):
    home.main(["output", "home"])
    assert home.main(["output", bad]) == 1
    assert home.load_config()["output"] == "~/.promo-reel/{project}/{slug}"
    assert capsys.readouterr().err.startswith("promo config: ")


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere, so no folder is unreachable")
def test_an_unreachable_drive_is_never_saved_or_written_to(box, capsys):
    ro = box / "volumes"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        assert home.main(["output", str(ro / "Drive" / "promo-reel")]) == 1
        assert "output" not in home.load_config()
        home.save_config({"output": str(ro / "Drive" / "{slug}")})        # the drive was fine when chosen, then unplugged
        with pytest.raises(home.ConfigError, match="plugged in"):
            home.project_dir("launch")
        assert not (ro / "Drive").exists()
    finally:
        ro.chmod(0o700)


def test_bare_names_and_listing_work_across_repos_from_anywhere(box, monkeypatch):
    home.main(["output", "home"])
    for proj, name in (("shop", "launch"), ("blog", "teaser")):
        d = box / "home" / ".promo-reel" / proj / name
        d.mkdir(parents=True)
        (d / "promo.yaml").write_text("x: 1")
    elsewhere = box / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert home.resolve("teaser") == str(box / "home" / ".promo-reel" / "blog" / "teaser")
    assert sorted(p["name"] for p in home.list_projects()) == ["launch", "teaser"]


def test_output_info_for_the_settings_pane(box):
    info = home.output_info("shop", "/work/shop")
    assert (info["mode"], info["locked"], info["available"]) == ("default", False, True)
    assert info["presets"]["home"]["example"] == str(box / "home" / ".promo-reel" / "shop" / "<slug>")
    assert info["presets"]["repo"]["example"] == "/work/shop/promo-reel/<slug>"
    home.main(["output", "repo"])
    assert home.output_info("shop", "/work/shop")["mode"] == "repo"
    home.main(["output", str(box / "drive")])
    assert home.output_info("shop", "/work/shop")["mode"] == "custom"
