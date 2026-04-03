"""Dark Batch 2 Demo Server — open http://localhost:8000 in your browser.

Pages:
  /           Home — <taiyaki-head>, islands, layout, CSS injection
  /polyfills  Polyfill status table (TextEncoder, MessageChannel, etc.)
  /broken     Error overlay with source map demo
  /api/features  JSON API endpoint
"""

import logging
from taiyaki_web import Taiyaki, Context, Logger

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

app = Taiyaki(
    components_dir="examples/demo_batch2/components",
    islands_dir="examples/demo_batch2/islands",
    layout="Layout",
    dev_mode=True,
)
app.use(Logger)


@app.get("/", component="Home")
async def index(ctx: Context):
    counter = await app.island("Counter", _ctx=ctx, initial=42, label="Likes")
    toggle = await app.island("Toggle", _ctx=ctx, label="Theme")
    return {"counterHtml": counter, "toggleHtml": toggle}


@app.get("/polyfills", component="PolyfillCheck")
async def polyfills(ctx: Context):
    return {}


@app.get("/broken", component="BrokenComponent")
async def broken(ctx: Context):
    return {"message": "Source map demo error"}


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


if __name__ == "__main__":
    print("\n  Dark Batch 2 Demo Server")
    print("  http://localhost:8000        Home (taiyaki-head + islands + layout)")
    print("  http://localhost:8000/polyfills  Polyfill status")
    print("  http://localhost:8000/broken     Error overlay + source maps")
    print("  http://localhost:8000/api/features  JSON API\n")
    app.run(port=8000)
