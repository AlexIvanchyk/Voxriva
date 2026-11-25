"""Check module boundaries without importing application or starting its resources."""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend/app"
LEGACY = {
    "access",
    "catalog",
    "members",
    "templates",
    "template_authoring",
    "locales",
    "rendering",
    "compatibility",
    "lifecycle",
    "deployments",
    "provider_api",
    "provider_events",
    "notifications",
    "delivery_runtime",
    "recovery",
    "operations",
    "monitoring",
    "readiness",
}


def python_imports(path: Path, root: Path = ROOT) -> list[tuple[int, str]]:
    module = ".".join(path.relative_to(root).with_suffix("").parts)
    package = module.split(".")[:-1]
    result = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            result.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = package[: len(package) - node.level + 1] if node.level else []
            target = (
                ".".join([*prefix, *node.module.split(".")])
                if node.module
                else ".".join(prefix)
            )
            result.append((node.lineno, target))
            result.extend(
                (node.lineno, f"{target}.{alias.name}") for alias in node.names
            )
    return result


def violations(root: Path = ROOT) -> list[str]:
    errors = []
    for path in (root / "backend/app").glob("*.py"):
        if path.name not in {"__init__.py", "main.py"}:
            errors.append(
                f"{path.relative_to(root)}: flat application modules are forbidden; choose a feature or infrastructure owner"
            )
    for path in (root / "backend/app/features").rglob("*.py"):
        relative = path.relative_to(root)
        is_router = path.stem == "router" or path.stem.endswith("_router")
        for line, target in python_imports(path, root):
            if path.stem.endswith("service") and target.startswith("fastapi"):
                errors.append(
                    f"{relative}:{line}: business services cannot depend on HTTP framework {target}"
                )
            parts = target.split(".")
            if (
                target.startswith("backend.app.")
                and len(parts) > 2
                and parts[2] in LEGACY
            ):
                errors.append(
                    f"{relative}:{line}: canonical feature imports legacy module {target}"
                )
            if not is_router and any(
                part == "router" or part.endswith("_router") for part in parts
            ):
                errors.append(
                    f"{relative}:{line}: application logic imports HTTP router {target}"
                )
    for path in (root / "tests").rglob("*.py"):
        for line, target in python_imports(path, root):
            if any(
                part.startswith("test_")
                for part in target.split(".")
                if target.startswith("tests.")
            ):
                errors.append(
                    f"{path.relative_to(root)}:{line}: tests must import support, not another test: {target}"
                )
    for path in (root / "backend/app/infrastructure").rglob("*.py"):
        if path.name == "model_registry.py":
            continue  # Explicit composition point registers every feature's models.
        for line, target in python_imports(path, root):
            if target.startswith("backend.app.features."):
                errors.append(
                    f"{path.relative_to(root)}:{line}: infrastructure cannot depend on feature {target}"
                )
    source = root / "frontend/src"
    for path in source.rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        owner = path.relative_to(source).parts[0]
        for match in re.finditer(
            r"(?:from\s*|import\s*)[\'\"]([^\'\"]+)[\'\"]", path.read_text()
        ):
            imported = match.group(1)
            if not imported.startswith("."):
                continue
            target = (path.parent / imported).resolve()
            try:
                destination = target.relative_to(source).parts[0]
            except ValueError:
                continue
            if (
                owner == "shared"
                and destination in {"features", "app"}
                or owner == "features"
                and destination == "app"
            ):
                line = path.read_text()[: match.start()].count("\n") + 1
                errors.append(
                    f"{path.relative_to(root)}:{line}: {owner} cannot depend on {destination}"
                )
    return sorted(set(errors))


if __name__ == "__main__":
    failures = violations()
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)
    print(
        "Architecture boundaries passed (feature imports, HTTP isolation, test support, frontend layers)."
    )
