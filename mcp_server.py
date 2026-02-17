"""
Business Claw MCP Server using official MCP library
"""

import os
import asyncio
import json
from datetime import datetime
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from mcp.server import InitializationOptions

# Configuration
ERPNEXT_URL = os.getenv("ERPNEXT_URL", "http://localhost:8001")
API_KEY = os.getenv("API_KEY", "929932f34acbaf3")
API_SECRET = os.getenv("API_SECRET", "6d3df971fe530ec")

# Create MCP Server
app = Server("business-claw")

# Define tools
@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="system.ping",
            description="Check if the MCP server is running",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="erpnext.get_current_user",
            description="Get current user info from ERPNext",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="erpnext.list_doctypes",
            description="List available DocTypes in ERPNext",
            inputSchema={
                "type": "object",
                "properties": {
                    "module": {"type": "string", "description": "Filter by module"}
                }
            }
        ),
        Tool(
            name="erpnext.get_doc",
            description="Get a document by name",
            inputSchema={
                "type": "object",
                "properties": {
                    "doctype": {"type": "string", "description": "DocType"},
                    "name": {"type": "string", "description": "Document name"}
                },
                "required": ["doctype", "name"]
            }
        ),
        Tool(
            name="erpnext.list_docs",
            description="List documents with filters",
            inputSchema={
                "type": "object",
                "properties": {
                    "doctype": {"type": "string", "description": "DocType"},
                    "limit": {"type": "integer", "description": "Max results"}
                },
                "required": ["doctype"]
            }
        ),
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    import httpx
    
    headers = {
        "Authorization": f"token {API_KEY}:{API_SECRET}",
        "Content-Type": "application/json"
    }
    
    if name == "system.ping":
        return [TextContent(
            type="text",
            text=json.dumps({
                "ok": True,
                "server_time": datetime.utcnow().isoformat(),
                "version": "1.0.0"
            })
        )]
    
    elif name == "erpnext.get_current_user":
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{ERPNEXT_URL}/api/method/frappe.auth.get_logged_user",
                    headers=headers,
                    timeout=10.0
                )
                if resp.status_code == 200:
                    user = resp.json().get("message", "Guest")
                else:
                    user = "Error"
            except:
                user = "Connection failed"
            
            return [TextContent(
                type="text",
                text=json.dumps({"user": user})
            )]
    
    elif name == "erpnext.list_doctypes":
        return [TextContent(
            type="text",
            text=json.dumps({
                "doctypes": [
                    "Item", "Customer", "Supplier", "Sales Order",
                    "Purchase Order", "Invoice", "Payment Entry"
                ]
            })
        )]
    
    elif name == "erpnext.get_doc":
        doctype = arguments.get("doctype")
        docname = arguments.get("name")
        
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{ERPNEXT_URL}/api/resource/{doctype}/{docname}",
                    headers=headers,
                    timeout=10.0
                )
                if resp.status_code == 200:
                    data = resp.json()
                else:
                    data = {"error": f"Document not found: {docname}"}
            except Exception as e:
                data = {"error": str(e)}
            
            return [TextContent(type="text", text=json.dumps(data))]
    
    elif name == "erpnext.list_docs":
        doctype = arguments.get("doctype")
        limit = arguments.get("limit", 20)
        
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{ERPNEXT_URL}/api/method/frappe.client.get_list",
                    headers=headers,
                    json={
                        "doctype": doctype,
                        "fields": ["name"],
                        "limit": limit
                    },
                    timeout=10.0
                )
                if resp.status_code == 200:
                    data = resp.json().get("message", [])
                else:
                    data = {"error": f"Failed to list {doctype}"}
            except Exception as e:
                data = {"error": str(e)}
            
            return [TextContent(type="text", text=json.dumps(data))]
    
    else:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


async def main():
    """Run the server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="business-claw",
                server_version="1.0.0",
                capabilities={}
            )
        )

if __name__ == "__main__":
    asyncio.run(main())
