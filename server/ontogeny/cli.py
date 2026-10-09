# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""ontogeny -- the operator's door. Everything it does goes through
ServiceContext (same governance as HTTP/MCP) or ontogeny.core (pure validation)."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import typer

from .config import load_settings

app = typer.Typer(no_args_is_help=True, help="ontogeny control plane CLI")
evolve_app = typer.Typer(no_args_is_help=True, help="RSI evolution loop")
projection_app = typer.Typer(no_args_is_help=True, help="graph projection")
app.add_typer(evolve_app, name="evolve")
app.add_typer(projection_app, name="projection")


# ----------------------------------------------------------------- pure cmds


@app.command()
def validate(path: str) -> None:
    """Validate a package (structure + semantics). Exit 1 on errors."""
    from .core import load_package, validate
    from .errors import DSLValidationError

    try:
        pkg = load_package(path)
    except DSLValidationError as exc:
        typer.secho(f"FAIL load: {exc.message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    rep = validate(pkg)
    for i in rep.issues:
        color = typer.colors.RED if i.severity == "error" else typer.colors.YELLOW
        typer.secho(f"{i.severity.upper():7} {i.code:22} {i.resource}: {i.message}", fg=color)
    if rep.ok:
        typer.secho(f"OK ({rep.summary()})", fg=typer.colors.GREEN)
    else:
        raise typer.Exit(1)


@app.command()
def lint(path: str) -> None:
    from .core import load_package
    from .core.linter import lint as run_lint

    rep = run_lint(load_package(path))
    for i in rep.issues:
        typer.secho(f"WARN {i.code:8} {i.resource}: {i.message}", fg=typer.colors.YELLOW)
    typer.secho(f"lint done ({rep.summary()})", fg=typer.colors.GREEN)


@app.command()
def migrate(db: str = None, apply: bool = False) -> None:
    """Diff the DSL (compiled snapshot) against the live object tables.

    Additive changes are applied automatically by ``ensure_tables`` on every
    start; this command surfaces everything BEYOND that: type changes, dropped
    or renamed properties, and orphaned tables a rename or delete left behind.
    ``--apply`` runs only the safe additive class -- destructive steps are
    printed for a human, never executed, because the object tables are the
    authoritative data (docs/data-layer.md: "真源（数据）").
    """
    from .service import ServiceContext
    from .stores.migrate import apply_safe, plan_migration

    settings = load_settings(db_dsn=db) if db else load_settings()
    sc = ServiceContext(settings, os.environ.get("ONTOGENY_PACKAGE_ROOT"))

    async def run() -> int:
        await sc.initialize()
        async with sc.sessionmaker() as s:
            conn = await s.connection()
            plan = await conn.run_sync(lambda c: plan_migration(c, sc.compiled))
            if apply:
                n = await conn.run_sync(lambda c: apply_safe(c, plan))
                await s.commit()
                return n
            typer.echo(plan.render())
            if plan.destructive:
                typer.secho(
                    f"\n{len(plan.destructive)} destructive step(s) require manual review "
                    "(the object tables are authoritative data)",
                    fg=typer.colors.YELLOW,
                )
            return len(plan.safe)

    n = asyncio.run(run())
    typer.secho(f"migration: {n} safe step(s){' applied' if apply else ' pending'}",
                fg=typer.colors.GREEN)



@app.command()
def docs(path: str, out: str = "docs-generated") -> None:
    """Generate a human-readable markdown view of the package."""
    from .core import load_package

    pkg = load_package(path)
    outdir = Path(out)
    outdir.mkdir(parents=True, exist_ok=True)
    lines = [f"# Ontology: {pkg.manifest.metadata.name}", ""]
    for r in pkg.resources:
        if r.kind == "Ontology":
            continue
        meta = r.metadata
        lines.append(f"## {r.kind}: {meta.name}")
        lines.append(f"- display: {meta.display or '-'}")
        if meta.description:
            lines.append(f"- description: {meta.description}")
        lines.append("")
    (outdir / "ontology.md").write_text("\n".join(lines), encoding="utf-8")
    typer.secho(f"docs written to {outdir/'ontology.md'}", fg=typer.colors.GREEN)


@app.command()
def diff(a: str, b: str) -> None:
    """Two-package semantic diff (names added/removed/changed)."""
    from .core import load_package

    pa, pb = load_package(a), load_package(b)
    sa = {(r.kind, r.metadata.name): r.model_dump_json() for r in pa.resources}
    sb = {(r.kind, r.metadata.name): r.model_dump_json() for r in pb.resources}
    for key in sorted(set(sa) | set(sb)):
        if key not in sb:
            typer.secho(f"- {key[0]}/{key[1]}", fg=typer.colors.RED)
        elif key not in sa:
            typer.secho(f"+ {key[0]}/{key[1]}", fg=typer.colors.GREEN)
        elif sa[key] != sb[key]:
            typer.secho(f"~ {key[0]}/{key[1]}", fg=typer.colors.YELLOW)


# ------------------------------------------------------------ service cmds


@app.command()
def publish(path: str = None, db: str = None) -> None:
    """Validate + publish a package into the registry."""
    path = path or os.environ.get("ONTOGENY_PACKAGE_ROOT")
    if not path:
        typer.secho("path or ONTOGENY_PACKAGE_ROOT required", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    from .service import ServiceContext

    settings = load_settings(db_dsn=db) if db else load_settings()
    sc = ServiceContext(settings, None)

    async def run():
        await sc.initialize()
        compiled = await sc.publish(path)
        return compiled.content_hash

    h = asyncio.run(run())
    typer.secho(f"published content_hash={h[:12]}", fg=typer.colors.GREEN)


@app.command()
def sync(object_type: str, db: str = None) -> None:
    from .service import ServiceContext

    settings = load_settings(db_dsn=db) if db else load_settings()
    sc = ServiceContext(settings, os.environ.get("ONTOGENY_PACKAGE_ROOT"))

    async def run():
        await sc.initialize()
        return await sc.sync(object_type)

    typer.echo(json.dumps(asyncio.run(run())))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ensure_ui(build: bool, ui_dir: str | None) -> Path | None:
    """Locate the built SPA, optionally building it (npm) when missing."""
    from .api.app import resolve_ui_dir

    resolved = resolve_ui_dir(ui_dir)
    if resolved is not None or not build:
        return resolved

    web = _repo_root() / "web"
    dist = web / "dist"
    if not (web / "package.json").is_file():
        typer.secho(f"no web/ directory at {web}; serving API only", fg=typer.colors.YELLOW)
        return None
    if not (web / "node_modules").is_dir():
        typer.secho(
            "frontend dependencies missing -- run `npm install` in web/ first, or use --no-build-ui",
            fg=typer.colors.YELLOW,
        )
        return None

    typer.secho("building frontend (web/dist)…", fg=typer.colors.CYAN)
    result = subprocess.run(["npm", "run", "build"], cwd=web, capture_output=True, text=True)
    if result.returncode != 0:
        typer.secho(f"frontend build failed:\n{result.stderr[-1500:]}", fg=typer.colors.RED)
        return None
    typer.secho("frontend built", fg=typer.colors.GREEN)
    return resolve_ui_dir(dist)


@app.command()
def serve(
    db: str = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    demo: bool = typer.Option(False, "--demo", help="self-contained demo: seed source data, copy the example package, serve the UI"),
    data_dir: str = typer.Option(".ontogeny-demo", "--data-dir", help="demo state directory (metadata + source db + package copy)"),
    package: str = typer.Option(None, "--package", help="ontology package to install into the demo (default: domains/product-manufacturing)"),
    reseed: bool = typer.Option(False, "--reseed", help="rebuild the demo source db and package copy from scratch"),
    build_ui: bool = typer.Option(True, "--build-ui/--no-build-ui", help="build web/dist when missing"),
    ui_dir: str = typer.Option(None, "--ui-dir", help="serve an already-built SPA from this directory"),
    open_browser: bool = typer.Option(False, "--open", help="open the UI in a browser once ready"),
) -> None:
    """Run the HTTP API (and the built UI on the same port when available)."""
    import uvicorn

    if demo:
        from .demo import DEFAULT_PACKAGE, prepare_demo

        # A first-class domain (a package directly inside a domains/ root) is
        # served IN PLACE: console saves — model edits and the canvas
        # layout.yaml — land in domains/<name>/ instead of a throwaway copy
        # that the demo's runtime reset would later wipe. Anything else (an
        # ad-hoc directory, tests) keeps the copy + pristine behavior.
        pkg_arg = Path(package or DEFAULT_PACKAGE)
        if not pkg_arg.is_absolute():
            pkg_arg = Path.cwd() / pkg_arg
        direct = pkg_arg.resolve().parent.name == "domains"

        paths = prepare_demo(data_dir, package=package or DEFAULT_PACKAGE,
                             reseed=reseed, direct=direct)
        for k, v in paths.as_env().items():
            os.environ[k] = v
        typer.secho(f"demo data dir: {paths.root.resolve()}", fg=typer.colors.CYAN)
        if direct:
            typer.secho(f"  serving the domain IN PLACE: {paths.package_root}\n"
                        "  saves (model + layout) write into domains/; --reseed keeps model edits",
                        fg=typer.colors.CYAN)
        else:
            typer.secho("  (metadata + seeded source db + package copy; `--reseed` rebuilds)", fg=typer.colors.CYAN)
        if paths.fresh:
            typer.secho("  fresh demo -> syncing source objects on boot",
                        fg=typer.colors.CYAN)
            os.environ["ONTOGENY_DEMO_POPULATE"] = "1"

    if db:
        os.environ["ONTOGENY_DB_DSN"] = db

    ui = _ensure_ui(build_ui, ui_dir)
    if ui is not None:
        os.environ["ONTOGENY_UI_DIR"] = str(ui)
        typer.secho(f"UI:  http://{host}:{port}/   (serving {ui})", fg=typer.colors.GREEN)
    else:
        typer.secho("UI:  not served (API only) -- build with `cd web && npm run build`", fg=typer.colors.YELLOW)
    typer.secho(f"API: http://{host}:{port}/api/v1  ·  docs /docs", fg=typer.colors.GREEN)

    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open(f"http://{host}:{port}/")).start()

    uvicorn.run("ontogeny.api_factory:create_app_factory", factory=True, host=host, port=port)


# evolve -------------------------------------------------------------------


@evolve_app.command("signals")
def evolve_signals(db: str = None) -> None:
    from .service import ServiceContext

    settings = load_settings(db_dsn=db) if db else load_settings()
    sc = ServiceContext(settings, os.environ.get("ONTOGENY_PACKAGE_ROOT"))

    async def run():
        await sc.initialize()
        async with sc.sessionmaker() as s:
            # aggregate_signals runs every detector (telemetry + quarantine),
            # deduped within the window
            created = await sc.telemetry.aggregate_signals(s)
            await s.commit()
        return created

    typer.echo(json.dumps(asyncio.run(run()), ensure_ascii=False))


@evolve_app.command("promote")
def evolve_promote(proposal_id: int, db: str = None) -> None:
    from .service import ServiceContext

    settings = load_settings(db_dsn=db) if db else load_settings()
    sc = ServiceContext(settings, os.environ.get("ONTOGENY_PACKAGE_ROOT"))

    async def run():
        await sc.initialize()
        # the SAME promote the REST route runs (sc.evolve_promote): hot-swap,
        # post-merge re-eval and auto-rollback included. The CLI's former bare
        # promoter.promote() call was a second, safety-net-less implementation.
        return await sc.evolve_promote(proposal_id)

    typer.echo(json.dumps(asyncio.run(run()), ensure_ascii=False, default=str))


# projection ----------------------------------------------------------------


@projection_app.command("rebuild")
def projection_rebuild(db: str = None) -> None:
    from .service import ServiceContext

    settings = load_settings(db_dsn=db) if db else load_settings()
    sc = ServiceContext(settings, os.environ.get("ONTOGENY_PACKAGE_ROOT"))

    async def run():
        await sc.initialize()
        return await sc.projection_rebuild()

    typer.echo(json.dumps(asyncio.run(run())))


if __name__ == "__main__":
    app()
