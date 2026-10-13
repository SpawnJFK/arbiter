"""Static check (ast) that product module packages do not import each other's internals.

Modules talk through the shared seams only: contracts, models, platform, errors, config, db,
domain and pipeline.hooks. Core packages that are not modules (fileproc, linguistic, billing,
storage, i18n, webhooks) may be imported; another MODULE package may not.

Importing each package with another one removed is not practical in one interpreter, so this
test reads every import statement (top level and inside functions) instead.

KNOWN_DEBT lists cross-module imports that existed when the check was introduced. The test
fails on any new one; when debt is paid, delete its line (a stale line is reported).
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

ARBITER = Path(__file__).resolve().parents[2] / "arbiter"

# package directory under arbiter/ -> module key in arbiter.platform.modules.MODULES
MODULE_PACKAGES: dict[str, str] = {
    "agency": "pm",
    "vendors": "pm",
    "engines": "engine",
    "quality": "ai",
    "community": "community",
    "auditor": "auditor",
    "strings": "strings",
}

ALLOWED_SHARED = ("contracts", "models", "platform", "errors", "config", "db", "domain", "pipeline.hooks")

# (importing file relative to arbiter/, imported module)
KNOWN_DEBT: set[tuple[str, str]] = {
    ("quality/senate.py", "arbiter.engines.tags"),
    ("quality/judge.py", "arbiter.engines.tags"),
    ("quality/editor.py", "arbiter.engines.tags"),
    ("quality/checks.py", "arbiter.engines.tags"),
    ("engines/llm_mt.py", "arbiter.quality.prompts"),
    ("agency/assistant.py", "arbiter.engines.registry"),
}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            # "from arbiter.engines import tags" may import the submodule arbiter.engines.tags
            if node.module.count(".") <= 1:
                out += [f"{node.module}.{a.name}" for a in node.names]
            else:
                out.append(node.module)
    return [m for m in out if m.startswith("arbiter.")]


def _violations(base: Path = ARBITER) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for pkg, module in MODULE_PACKAGES.items():
        root = base / pkg
        if not root.is_dir():
            continue
        for f in root.rglob("*.py"):
            rel = f.relative_to(base).as_posix()
            for imp in _imports(f):
                parts = imp.split(".")
                target_pkg = parts[1]
                if target_pkg not in MODULE_PACKAGES or target_pkg == pkg:
                    continue
                if MODULE_PACKAGES[target_pkg] == module:
                    continue  # two packages of the same module (agency + vendors = pm)
                if any(imp == f"arbiter.{s}" or imp.startswith(f"arbiter.{s}.") for s in ALLOWED_SHARED):
                    continue
                found.add((rel, imp))
    return found


def test_no_new_cross_module_imports():
    found = _violations()
    new = sorted(found - KNOWN_DEBT)
    assert not new, (
        "module packages import another module's internals (use contracts.py or pipeline hooks):\n"
        + "\n".join(f"  {f} -> {m}" for f, m in new)
    )


def test_known_debt_list_is_current():
    stale = sorted(KNOWN_DEBT - _violations())
    if stale:  # debt paid (maybe on another branch): drop the lines, never fail for it
        warnings.warn(f"stale KNOWN_DEBT entries, delete them: {stale}", stacklevel=1)


def test_checker_catches_a_planted_violation(tmp_path):
    (tmp_path / "agency").mkdir()
    (tmp_path / "agency" / "x.py").write_text(
        "from arbiter.quality import judge\n"
        "from arbiter.contracts import TermHit\n"
        "from arbiter.pipeline import hooks\n"
        "def f():\n    import arbiter.community.pay\n"
    )
    (tmp_path / "vendors").mkdir()
    (tmp_path / "vendors" / "y.py").write_text("from arbiter.agency import crm\n")  # same module (pm)
    assert _violations(tmp_path) == {
        ("agency/x.py", "arbiter.quality.judge"),
        ("agency/x.py", "arbiter.community.pay"),
    }


def test_shared_seams_exist():
    for s in (
        "contracts.py",
        "errors.py",
        "config.py",
        "db.py",
        "platform",
        "models",
        "domain",
        "pipeline/hooks.py",
    ):
        assert (ARBITER / s).exists(), s
