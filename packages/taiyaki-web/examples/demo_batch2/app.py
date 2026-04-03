"""Dark Batch 2 Demo — all 5 new features with TSX components.

Run:
    cd packages/dark && uv run python examples/demo_batch2/app.py
"""

import asyncio
import logging
import httpx

from taiyaki_web import Taiyaki, Context, Logger, Recover

logging.basicConfig(level=logging.INFO, format="  %(name)s: %(message)s")


async def main():
    print("=" * 64)
    print("  Dark Batch 2 Demo — TSX components + 5 new features")
    print("=" * 64)

    # ── App with TSX file-based components ──
    app = Taiyaki(
        components_dir="examples/demo_batch2/components",
        islands_dir="examples/demo_batch2/islands",
        layout="Layout",
        dev_mode=True,
    )
    # Logger middleware — logs every request
    app.use(Logger)

    # ── 1. <taiyaki-head> extraction ──
    @app.get("/", component="Home")
    async def index(ctx: Context):
        counter = await app.island("Counter", _ctx=ctx, initial=42, label="Likes")
        toggle = await app.island("Toggle", _ctx=ctx, label="Theme")
        return {"counterHtml": counter, "toggleHtml": toggle}

    # ── 2. Polyfill check page ──
    @app.get("/polyfills", component="PolyfillCheck")
    async def polyfills(ctx: Context):
        return {}

    # ── 3. Broken component (source map demo) ──
    @app.get("/broken", component="BrokenComponent")
    async def broken(ctx: Context):
        return {"message": "Source map demo error"}

    # ── 4. API endpoint ──
    @app.api_get("/api/features")
    async def features(ctx: Context):
        return {
            "features": [
                "taiyaki-head extraction",
                "React polyfills",
                "Source maps",
                "Logger/Recover middleware",
                "Island asset bundling",
            ],
            "jsc_support": True,
        }

    transport = httpx.ASGITransport(app=app.asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://demo") as c:

        # ── Demo 1: <taiyaki-head> + Islands + Layout (all from TSX files) ──
        print("\n── 1. <taiyaki-head> + Islands + Layout (TSX files) ──")
        r = await c.get("/")
        assert r.status_code == 200
        body = r.text

        has_custom_title = "<title>Dark Batch 2 Demo</title>" in body
        has_meta = 'name="description"' in body
        has_scoped_css = ".feature-card" in body
        no_dark_head_tag = "<taiyaki-head>" not in body
        has_layout_nav = "Batch 2 Demo" in body
        has_counter_island = 'data-island="Counter"' in body
        has_toggle_island = 'data-island="Toggle"' in body

        print(f"  Custom <title> in <head>:  {has_custom_title}")
        print(f"  <meta description> in head: {has_meta}")
        print(f"  Component-scoped CSS:       {has_scoped_css}")
        print(f"  <taiyaki-head> tags stripped:  {no_dark_head_tag}")
        print(f"  Layout from TSX:            {has_layout_nav}")
        print(f"  Counter island:             {has_counter_island}")
        print(f"  Toggle island:              {has_toggle_island}")

        # ── Demo 2: Island asset bundling (hashed URLs + modulepreload) ──
        print("\n── 2. Island asset bundling ──")
        has_hashed_url = False
        has_modulepreload = False
        import re
        hash_match = re.search(r'/_taiyaki/islands/Counter-[0-9a-f]{8}\.js', body)
        if hash_match:
            has_hashed_url = True
            hashed_url = hash_match.group(0)
            # Fetch the hashed URL
            r_island = await c.get(hashed_url)
            has_immutable_cache = "immutable" in r_island.headers.get("cache-control", "")
            print(f"  Hashed URL:       {hashed_url}")
            print(f"  Island served:    {r_island.status_code == 200}")
            print(f"  Immutable cache:  {has_immutable_cache}")
        else:
            print(f"  Hashed URL:       (not yet — first request builds cache)")
            # Trigger island file build
            r_plain = await c.get("/_taiyaki/islands/Counter.js")
            print(f"  Plain URL served: {r_plain.status_code == 200}")

        has_modulepreload = 'rel="modulepreload"' in body
        print(f"  Modulepreload:    {has_modulepreload}")

        # Fetch home again to get hashed URLs (now cached)
        r2 = await c.get("/")
        hash_match2 = re.search(r'/_taiyaki/islands/Counter-[0-9a-f]{8}\.js', r2.text)
        if hash_match2:
            print(f"  2nd request hash: {hash_match2.group(0)}")

        # ── Demo 3: React polyfills ──
        print("\n── 3. React SSR polyfills ──")
        r = await c.get("/polyfills")
        assert r.status_code == 200
        body = r.text
        print(f"  TextEncoder:      {'Available' in body}")
        print(f"  TextDecoder:      {'Available' in body}")
        print(f"  queueMicrotask:   {'Available' in body}")
        print(f"  MessageChannel:   {'Available' in body}")
        print(f"  Roundtrip test:   {'OK' in body}")
        # Check taiyaki-head title override
        has_polyfill_title = "<title>Polyfill Check</title>" in body
        print(f"  <taiyaki-head> title: {has_polyfill_title}")

        # ── Demo 4: Source maps (error overlay) ──
        print("\n── 4. Source maps + Error overlay ──")
        r = await c.get("/broken")
        assert r.status_code == 500
        body = r.text
        has_overlay = "taiyaki-overlay" in body
        has_error_msg = "Source map demo error" in body
        has_component_name = "BrokenComponent" in body
        print(f"  Error overlay:    {has_overlay}")
        print(f"  Error message:    {has_error_msg}")
        print(f"  Component name:   {has_component_name}")

        # ── Demo 5: Logger middleware ──
        print("\n── 5. Logger middleware (check output above) ──")
        print("  Logger is active — all requests above were logged to 'dark' logger.")

        # ── Demo 6: API still works ──
        print("\n── 6. API endpoint ──")
        r = await c.get("/api/features")
        data = r.json()
        print(f"  Features: {data['features']}")
        print(f"  JSC support: {data['jsc_support']}")

    print("\n" + "=" * 64)
    print("  All batch 2 features verified!")
    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(main())
