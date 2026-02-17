"""
Business Claw MCP Server with SSE transport using official MCP library (v1.26.0)

Run with:
    cd frappe-bench
    ./env/bin/uvicorn mcp_server.sse_server:app --host 0.0.0.0 --port 8003
"""

import os
import json
from datetime import datetime

from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent

# Configuration
ERPNEXT_URL = os.getenv("ERPNEXT_URL", "http://localhost:8001")
API_KEY = os.getenv("API_KEY", "929932f34acbaf3")
API_SECRET = os.getenv("API_SECRET", "6d3df971fe530ec")

# Create MCP Server
mcp_server = Server("business-claw")


@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="system_ping",
            description="Check if the MCP server is running and healthy",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="erpnext_get_current_user",
            description="Get current authenticated user info from ERPNext",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="erpnext_list_doctypes",
            description="List available DocTypes in ERPNext",
            inputSchema={
                "type": "object",
                "properties": {
                    "module": {"type": "string", "description": "Filter by module name"}
                }
            }
        ),
        Tool(
            name="erpnext_get_doc",
            description="Get a specific document by doctype and name",
            inputSchema={
                "type": "object",
                "properties": {
                    "doctype": {"type": "string", "description": "DocType name"},
                    "name": {"type": "string", "description": "Document name/ID"}
                },
                "required": ["doctype", "name"]
            }
        ),
        Tool(
            name="erpnext_list_docs",
            description="List documents of a given DocType with optional limit",
            inputSchema={
                "type": "object",
                "properties": {
                    "doctype": {"type": "string", "description": "DocType name"},
                    "limit": {"type": "integer", "description": "Max results (default 20)"}
                },
                "required": ["doctype"]
            }
        ),
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    import httpx

    headers = {
        "Authorization": f"token {API_KEY}:{API_SECRET}",
        "Content-Type": "application/json"
    }

    if name == "system_ping":
        return [TextContent(
            type="text",
            text=json.dumps({
                "ok": True,
                "server_time": datetime.utcnow().isoformat(),
                "version": "1.0.0"
            })
        )]

    elif name == "erpnext_get_current_user":
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{ERPNEXT_URL}/api/method/frappe.auth.get_logged_user",
                    headers=headers, timeout=10.0
                )
                user = resp.json().get("message", "Guest") if resp.status_code == 200 else "Error"
            except Exception:
                user = "Connection failed"
            return [TextContent(type="text", text=json.dumps({"user": user}))]

    elif name == "erpnext_list_doctypes":
        return [TextContent(type="text", text=json.dumps({
            "doctypes": [
                "Item", "Customer", "Supplier", "Sales Order",
                "Purchase Order", "Invoice", "Payment Entry"
            ]
        }))]

    elif name == "erpnext_get_doc":
        doctype = arguments.get("doctype")
        docname = arguments.get("name")
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{ERPNEXT_URL}/api/resource/{doctype}/{docname}",
                    headers=headers, timeout=10.0
                )
                data = resp.json() if resp.status_code == 200 else {"error": f"Document not found: {docname}"}
            except Exception as e:
                data = {"error": str(e)}
            return [TextContent(type="text", text=json.dumps(data))]

    elif name == "erpnext_list_docs":
        doctype = arguments.get("doctype")
        limit = arguments.get("limit", 20)
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{ERPNEXT_URL}/api/method/frappe.client.get_list",
                    headers=headers,
                    json={"doctype": doctype, "fields": ["name"], "limit": limit},
                    timeout=10.0
                )
                data = resp.json().get("message", []) if resp.status_code == 200 else {"error": f"Failed to list {doctype}"}
            except Exception as e:
                data = {"error": str(e)}
            return [TextContent(type="text", text=json.dumps(data))]

    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


# ──────────────────────────────────────────────────────────────
# SSE Transport Setup
# ──────────────────────────────────────────────────────────────

# Create SSE transport — endpoint MUST match the Mount path below
sse_transport = SseServerTransport("/messages/")


async def _handle_sse_asgi(scope, receive, send):
    """Raw ASGI handler for SSE connections."""
    async with sse_transport.connect_sse(scope, receive, send) as streams:
        await mcp_server.run(
            streams[0], streams[1],
            mcp_server.create_initialization_options()
        )


async def handle_sse(request: Request) -> Response:
    """
    Starlette Route endpoint for SSE.

    Starlette's Route gives us a Request object, but MCP's connect_sse
    needs raw ASGI (scope, receive, send). We extract them from the
    Request — this is the canonical pattern used by MCP's own FastMCP.
    """
    await _handle_sse_asgi(
        request.scope,
        request.receive,
        request._send,  # type: ignore[reportPrivateUsage]
    )
    return Response()


async def health(request: Request) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse({
        "status": "ok",
        "server": "business-claw",
        "transport": "sse",
        "version": "1.0.0"
    })


# Create Starlette app
app = Starlette(
    routes=[
        Route("/health", endpoint=health, methods=["GET"]),
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ]
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
