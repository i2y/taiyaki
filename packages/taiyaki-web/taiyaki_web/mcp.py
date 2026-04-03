"""MCP (Model Context Protocol) integration for Taiyaki apps."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from taiyaki_web.app import Taiyaki


class _TextExtractor(HTMLParser):
    """Strip HTML tags and extract text content."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _path_to_slug(path: str, method: str) -> str:
    """Convert a URL path to a tool-name slug."""
    slug = re.sub(r"[{}]", "", path)
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", slug).strip("_")
    return f"{method.lower()}_{slug}" if slug else method.lower()


class TaiyakiMCPServer:
    """Exposes Taiyaki routes as MCP tools.

    Uses httpx.ASGITransport to make internal requests.
    """

    def __init__(self, app: Taiyaki) -> None:
        self._app = app
        self._tools: list[dict[str, Any]] = []
        self._tools_by_name: dict[str, dict[str, Any]] = {}
        self._client: Any = None
        self._build_tools()

    def _build_tools(self) -> None:
        for meta in self._app._route_meta:
            path = meta["path"]
            method = meta["method"]
            slug = _path_to_slug(path, method)
            doc = meta.get("docstring") or f"{method} {path}"

            if method == "GET" and not meta.get("api"):
                # Page route: render tool + text tool
                self._tools.append(
                    {
                        "name": f"render_{slug}",
                        "description": f"Render HTML: {doc}",
                        "path": path,
                        "method": "GET",
                        "output": "html",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path_params": {
                                    "type": "object",
                                    "description": "URL path parameters",
                                },
                                "query_params": {
                                    "type": "object",
                                    "description": "Query string parameters",
                                },
                            },
                        },
                    }
                )
                self._tools.append(
                    {
                        "name": f"text_{slug}",
                        "description": f"Get text content: {doc}",
                        "path": path,
                        "method": "GET",
                        "output": "text",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path_params": {
                                    "type": "object",
                                    "description": "URL path parameters",
                                },
                            },
                        },
                    }
                )
            elif meta.get("api"):
                # API route
                self._tools.append(
                    {
                        "name": f"api_{slug}",
                        "description": f"API call: {doc}",
                        "path": path,
                        "method": method,
                        "output": "json",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "body": {
                                    "type": "object",
                                    "description": "Request body (for POST/PUT/PATCH)",
                                },
                            },
                        },
                    }
                )
            else:
                # Action route
                self._tools.append(
                    {
                        "name": f"action_{slug}",
                        "description": f"Execute action: {doc}",
                        "path": path,
                        "method": method,
                        "output": "html",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "body": {
                                    "type": "object",
                                    "description": "Form data / request body",
                                },
                            },
                        },
                    }
                )

        self._tools_by_name = {t["name"]: t for t in self._tools}

    def list_tools(self) -> list[dict[str, Any]]:
        """Return MCP tools/list response."""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"],
            }
            for t in self._tools
        ]

    def _get_client(self):
        if self._client is None:
            import httpx

            transport = httpx.ASGITransport(app=self._app.asgi)
            self._client = httpx.AsyncClient(transport=transport, base_url="http://mcp")
        return self._client

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute an MCP tool call."""
        tool = self._tools_by_name.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name}"}

        arguments = arguments or {}
        path = tool["path"]

        path_params = arguments.get("path_params", {})
        for k, v in path_params.items():
            path = path.replace(f"{{{k}}}", str(v))

        client = self._get_client()
        method = tool["method"]
        kwargs: dict[str, Any] = {}

        query_params = arguments.get("query_params")
        if query_params:
            kwargs["params"] = query_params

        body = arguments.get("body")
        if body and method in ("POST", "PUT", "PATCH"):
            kwargs["json"] = body

        response = await client.request(method, path, **kwargs)

        output_type = tool["output"]
        if output_type == "text":
            extractor = _TextExtractor()
            extractor.feed(response.text)
            return {"content": [{"type": "text", "text": extractor.get_text()}]}
        elif output_type == "json":
            try:
                data = response.json()
            except Exception:
                data = response.text
            return {"content": [{"type": "text", "text": json.dumps(data)}]}
        else:
            return {"content": [{"type": "text", "text": response.text}]}

    async def handle_jsonrpc(self, request: dict[str, Any]) -> dict[str, Any]:
        """Handle a JSON-RPC MCP request."""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "tools/list":
            result = {"tools": self.list_tools()}
        elif method == "tools/call":
            result = await self.call_tool(
                params.get("name", ""), params.get("arguments")
            )
        elif method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "dark-mcp", "version": "0.1.0"},
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"},
            }

        return {"jsonrpc": "2.0", "id": req_id, "result": result}
