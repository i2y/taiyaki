"""Minimal taiyaki-web example — TSX components + Islands + htmx.

Run:
    cd packages/taiyaki-web
    uv run python examples/hello/app.py
"""

import datetime

from taiyaki_web import Taiyaki, Context

app = Taiyaki(
    components_dir="examples/hello/components",
    islands_dir="examples/hello/islands",
)


@app.get("/", component="Index")
async def index(ctx: Context):
    counter = await app.island("Counter", _ctx=ctx, initial=0)
    greeting = await app.render("Greeting", name="Taiyaki")
    return {"counter": counter, "greeting": greeting}


@app.api_get("/api/time")
async def get_time(ctx: Context):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    return {"time": now}


if __name__ == "__main__":
    app.run()
