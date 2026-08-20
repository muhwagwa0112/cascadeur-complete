from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def canonical_local_app_data() -> Path:
    """Return real user Local AppData, avoiding packaged-process redirection."""
    profile = os.environ.get("USERPROFILE")
    if profile:
        candidate = Path(profile) / "AppData" / "Local"
        if candidate.is_dir():
            return candidate.resolve()
    value = os.environ.get("LOCALAPPDATA")
    if not value:
        raise RuntimeError("LOCALAPPDATA and USERPROFILE are unavailable")
    return Path(value).resolve()


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    state: Path
    requests: Path
    responses: Path
    jobs: Path
    tokens: Path
    snapshots: Path
    registry: Path
    evidence_manifest: Path
    policy: Path
    logs: Path

    @classmethod
    def discover(cls, root: Path | None = None) -> RuntimePaths:
        base = (root or canonical_local_app_data() / "CascadeurMCP" / "cascadeur-complete").resolve()
        state = base / "state"
        return cls(
            root=base,
            state=state,
            requests=state / "requests",
            responses=state / "responses",
            jobs=state / "jobs",
            tokens=state / "tokens",
            snapshots=base / "snapshots",
            registry=state / "feature_registry.json",
            evidence_manifest=state / "live_evidence.json",
            policy=base / "policy.json",
            logs=base / "logs",
        )

    def ensure(self) -> None:
        for path in (
            self.root,
            self.state,
            self.requests,
            self.responses,
            self.jobs,
            self.tokens,
            self.snapshots,
            self.logs,
        ):
            path.mkdir(parents=True, exist_ok=True)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSC_SCHEMA_CANDIDATES = (
    canonical_local_app_data() / "CascadeurMCP" / "cascadeur-complete" / "state" / "csc_schema.json",
    PROJECT_ROOT / "inventory" / "csc_schema.json",
)
CASCADEUR_EXE = Path(os.environ.get("CASCADEUR_EXE", r"C:\Program Files\Cascadeur\cascadeur.exe"))
CASCADEUR_SCRIPTS = Path(r"C:\Program Files\Cascadeur\resources\scripts\python")
CASCADEUR_SAMPLES = Path(r"C:\Program Files\Cascadeur\samples")
