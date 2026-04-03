# Show available recipes
default:
    @just --list

# ─── Rust Core ───────────────────────────────

# Build (QuickJS backend)
build:
    cargo build

build-release:
    cargo build --release

# Run all Rust tests
test:
    cargo test

# Lint (clippy + fmt check)
lint:
    cargo clippy -- -D warnings
    cargo fmt -- --check

# Format Rust code
fmt:
    cargo fmt

clean:
    cargo clean

# ─── JSC Backend (macOS only) ────────────────

build-jsc:
    cargo build -p taiyaki-core --features jsc --no-default-features

test-jsc:
    cargo test -p taiyaki-core --features jsc --no-default-features

# ─── SQLite Feature ─────────────────────────

build-sqlite:
    cargo build -p taiyaki-cli --features sqlite

test-sqlite:
    cargo test -p taiyaki-cli --features sqlite

# ─── Python Bindings ────────────────────────

build-python:
    cd crates/taiyaki-python && maturin build --out target/wheels
    cd crates/taiyaki-python && uv pip install --force-reinstall --no-cache target/wheels/*.whl

build-python-dev:
    cd crates/taiyaki-python && maturin develop

# ─── taiyaki-web ─────────────────────────────

install-web:
    cd packages/taiyaki-web && uv pip install -e ".[test]"

test-web:
    cd packages/taiyaki-web && uv run python -m pytest tests/ -v

run-web *ARGS:
    cd packages/taiyaki-web && uv run python -m taiyaki_web run {{ARGS}}

# Lint Python code (ruff)
lint-web:
    cd packages/taiyaki-web && uv run ruff check taiyaki_web/

# Format Python code (ruff)
fmt-web:
    cd packages/taiyaki-web && uv run ruff format taiyaki_web/

# Check Python formatting without modifying
fmt-web-check:
    cd packages/taiyaki-web && uv run ruff format --check taiyaki_web/

# ─── All ─────────────────────────────────────

# Format all (Rust + Python)
fmt-all: fmt fmt-web

# Lint all (Rust + Python)
lint-all: lint lint-web

# ─── Composite ──────────────────────────────

dev: build test

ci: lint test test-sqlite build-python install-web test-web
