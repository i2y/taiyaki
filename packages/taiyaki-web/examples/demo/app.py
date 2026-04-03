"""Taiyaki-web full demo — all features with TSX components.

Run:
    cd packages/taiyaki-web
    uv run python examples/demo/app.py
"""

from datetime import datetime

from taiyaki_web import Taiyaki, Context, Sessions, CSRF, Logger

app = Taiyaki(
    components_dir="examples/demo/components",
    islands_dir="examples/demo/islands",
    layout="Layout",
)
app.use(Sessions("demo-secret"))
app.use(CSRF())
app.use(Logger)


# ── Home ──

@app.get("/", component="Home")
async def index(ctx: Context):
    session = ctx.session()
    session["visits"] = session.get("visits", 0) + 1
    return {
        "title": "Welcome to Taiyaki",
        "visits": session["visits"],
        "features": [
            {"icon": "🏝️", "name": "Islands", "desc": "Interactive components with selective hydration"},
            {"icon": "⚡", "name": "Streaming SSR", "desc": "Chunked HTML delivery for fast TTFB"},
            {"icon": "💾", "name": "LRU Cache", "desc": "ETag + 304 response caching"},
            {"icon": "🔒", "name": "Sessions + CSRF", "desc": "Signed cookies & token protection"},
            {"icon": "📁", "name": "Route Groups", "desc": "Shared prefix, layout, middleware"},
            {"icon": "🔥", "name": "Hot Reload", "desc": "SSE-based live reload in dev mode"},
            {"icon": "⚛️", "name": "React Support", "desc": "Switch renderer with one option"},
            {"icon": "🤖", "name": "MCP Tools", "desc": "Expose routes as AI agent tools"},
            {"icon": "🛠️", "name": "CLI Scaffold", "desc": "taiyaki_web new / generate"},
            {"icon": "📝", "name": "TypeGen", "desc": "Python types → TypeScript interfaces"},
        ],
    }


# ── Islands ──

@app.get("/islands", component="IslandsPage")
async def islands_page(ctx: Context):
    c1 = await app.island("Counter", _ctx=ctx, initial=0, label="Likes")
    c2 = await app.island("Counter", _ctx=ctx, initial=10, label="Score")
    c3 = await app.island("Counter", load="idle", _ctx=ctx, initial=42, label="Lazy")
    return {"counters": c1 + c2 + c3}


# ── Streaming SSR ──

@app.get("/streaming", component="StreamPage", stream=True)
async def streaming_page(ctx: Context):
    return {}


# ── Cached Page ──

_render_count = 0


@app.get("/cached", component="CachedPage", cache=True, cache_ttl=30)
async def cached_page(ctx: Context):
    global _render_count
    _render_count += 1
    return {
        "rendered_at": datetime.now().strftime("%H:%M:%S"),
        "render_count": str(_render_count),
    }


# ── Admin (Route Group) ──

admin = app.group("/admin", layout="AdminLayout")


@admin.get("/dashboard", component="Dashboard")
async def admin_dashboard(ctx: Context):
    return {
        "user": "Admin",
        "stats": [
            {"label": "Users", "value": "1,234"},
            {"label": "Requests/min", "value": "567"},
            {"label": "Uptime", "value": "99.9%"},
        ],
    }


# ── Form with Validation ──

@app.get("/form", component="ContactForm")
async def form_page(ctx: Context):
    return {}


@app.post("/form", component="ContactForm")
async def form_submit(ctx: Context):
    data = await ctx.form_data()
    if not data.get("name"):
        ctx.add_field_error("name", "Name is required")
    if not data.get("email") or "@" not in data.get("email", ""):
        ctx.add_field_error("email", "Valid email is required")
    if not data.get("message"):
        ctx.add_field_error("message", "Message is required")
    if not ctx.has_errors():
        return {"success": True}


# ── User Profile (concurrent data fetching) ──


async def load_user(ctx: Context):
    name = ctx.param("name")
    return {"name": name.capitalize(), "email": f"{name}@example.com", "role": "Developer"}


async def load_posts(ctx: Context):
    return [
        {"title": "Getting started with Taiyaki", "date": "2025-04-01"},
        {"title": "Islands architecture explained", "date": "2025-03-28"},
        {"title": "SSR vs CSR performance", "date": "2025-03-15"},
    ]


async def load_stats(ctx: Context):
    return {"followers": 1234, "following": 567}


@app.get("/user/{name}", component="UserProfile")
async def user_profile(ctx: Context):
    import asyncio
    user, posts, stats = await asyncio.gather(
        load_user(ctx), load_posts(ctx), load_stats(ctx),
    )
    return {"user": user, "posts": posts, "stats": stats}


# ── API ──

@app.api_get("/api/time")
async def api_time(ctx: Context):
    return {"time": datetime.now().isoformat(), "status": "ok"}


if __name__ == "__main__":
    print("  Taiyaki Demo Server: http://127.0.0.1:8000")
    app.run()
