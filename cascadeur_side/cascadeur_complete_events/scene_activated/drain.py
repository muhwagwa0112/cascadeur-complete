"""Drain pending Cascadeur Complete requests when a scene tab is activated."""

import csc  # noqa: F401 - required by Cascadeur's event loader convention


def run(scene: "csc.domain.Scene") -> None:
    try:
        from cascadeur_complete.runtime import process_pending

        count = process_pending(scene, matching_scene_only=True)
        if count:
            scene.success(f"Cascadeur Complete event processed {count} request(s)")
    except Exception as exc:
        print("[cascadeur-complete-events] scene_activated drain failed:", exc)
