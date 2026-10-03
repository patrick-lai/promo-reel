"""Shot-type registry. A shot type is a class registered with @shot_type("name") that provides:

    render(ctx, shot) -> dict            write ctx.seg_dir/<id>.mp4 and return an EDL entry
    src_to_out(shot, t_src) -> float|None  map a source-footage time to shot-local output seconds (None = not on screen)
    captions(ctx, shot) -> list[dict]    QA records: {text, role, box|None, t0, t1}  (box in 1920x1080 canvas units)

Project plugins (spec `plugins: [shots.py]`) register extra types with the same decorator.
"""
REGISTRY = {}


def shot_type(name):
    def deco(cls):
        REGISTRY[name] = cls()
        return cls
    return deco


def get_type(name):
    if name not in REGISTRY:
        raise KeyError(f"unknown shot type {name!r}; registered: {sorted(REGISTRY)}")
    return REGISTRY[name]


class ShotType:
    """Base class with the default (no-op) event/QA hooks."""

    def render(self, ctx, shot):
        raise NotImplementedError

    def src_to_out(self, shot, t_src):
        return None

    def captions(self, ctx, shot):
        from ..overlays import caption_boxes
        return caption_boxes(ctx, shot)


from . import clip, card, livestream  # noqa: E402,F401  (register built-in types)
