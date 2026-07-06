"""Attribute mixin activity to mods from captured boot output.

Two zero-dependency signals, both already present because every boot runs with
``-Dmixin.debug.verbose=true`` (PROJECT.md §7):

- the verbose mixin log prints one line per application
  (``Mixing common.FooMixin from mod.mixins.json into net.minecraft.class_310``)
  and Fabric-family loaders annotate config references with the owning mod
  (``mod.mixins.json:FooMixin from mod modid``) — together they attribute each
  transformed class to a config, and each config to a mod;
- the loader gives injected handlers synthetic names embedding the owning mod id
  (``handler$zzn000$modid$tick``), so raw stack frames blame a mod with no
  runtime helper installed.

Pure functions over captured text, like :mod:`app.runner.classify`.
"""

import re

from app.models import MixinApplication

_MIXING_RE = re.compile(r"Mixing\s+([\w.$]+)\s+from\s+([\w./-]+\.json)\s+into\s+([\w.$]+)")
# Fabric-family annotation tying a config to its mod: "<config>:<Class> from mod <id>".
_CONFIG_MOD_RE = re.compile(r"([\w./-]+\.json):[\w.$]+(?:\s+\{[^}]*\})?\s+from mod\s+([\w-]+)")
# Stack-trace frames; mod ids only ever appear in $-separated synthetic segments.
_FRAME_RE = re.compile(r"^\s+at\s+(\S+)", re.MULTILINE)


def parse_mixin_applications(log_text: str) -> list[MixinApplication]:
    """Deduplicated per-application records from the verbose mixin log."""
    config_mods: dict[str, str] = {}
    for match in _CONFIG_MOD_RE.finditer(log_text or ""):
        config_mods.setdefault(match.group(1), match.group(2))

    seen: set[tuple[str, str, str]] = set()
    applications: list[MixinApplication] = []
    for match in _MIXING_RE.finditer(log_text or ""):
        mixin_class, config, target_class = match.groups()
        key = (mixin_class, config, target_class)
        if key in seen:
            continue
        seen.add(key)
        applications.append(
            MixinApplication(
                mixin_class=mixin_class,
                config=config,
                target_class=target_class,
                mod=config_mods.get(config),
            )
        )
    return applications


def mods_in_stack_frames(text: str, known_ids: set[str]) -> list[str]:
    """Mod ids named by synthetic mixin-handler frames in a stack trace.

    Only ``$``-separated segments of frame names are considered (synthetic
    handler names, not package segments), and every candidate is cross-checked
    against ``known_ids`` — the booted jars' ids — so an unlucky token cannot
    produce a false blame.
    """
    if not known_ids:
        return []
    hits: set[str] = set()
    for frame in _FRAME_RE.finditer(text or ""):
        segments = frame.group(1).split("$")
        if len(segments) < 2:
            continue  # no synthetic name in this frame
        for segment in segments:
            candidate = segment.strip("();")
            if candidate in known_ids:
                hits.add(candidate)
    return sorted(hits)
