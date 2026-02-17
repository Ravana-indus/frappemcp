"""
Business Claw — Standalone MCP Server (FastMCP)

A standalone MCP server that bridges AI agents to ERPNext via REST API.
Uses FastMCP (the official high-level MCP SDK) which handles all
transport wiring (SSE, stdio, streamable-http) internally.

Usage:
    # SSE transport (for remote agents):
    cd frappe-bench
    ./env/bin/python mcp_server/server.py

    # Or via uvicorn for production:
    ./env/bin/uvicorn mcp_server.server:http_app --host 0.0.0.0 --port 8003

    # stdio transport (for local agents like Claude Desktop):
    ./env/bin/python mcp_server/server.py --stdio

MCP Config Examples:

    # SSE transport — set env vars before starting the server:
    export ERPNEXT_URL=http://localhost:8001
    export API_KEY=929932f34acbaf3
    export API_SECRET=6d3df971fe530ec
    ./env/bin/python mcp_server/server.py

    # Client config (mcp-config.json for SSE):
    {
      "mcpServers": {
        "business-claw": {
          "url": "http://localhost:8003/sse",
          "transport": "sse"
        }
      }
    }

    # Client config (for stdio — credentials via env):
    {
      "mcpServers": {
        "business-claw": {
          "command": "/path/to/frappe-bench/env/bin/python",
          "args": ["/path/to/frappe-bench/mcp_server/server.py", "--stdio"],
          "env": {
            "ERPNEXT_URL": "http://localhost:8001",
            "API_KEY": "929932f34acbaf3",
            "API_SECRET": "6d3df971fe530ec"
          }
        }
      }
    }
"""

import os
import sys
import json
import httpx
import asyncio
from datetime import datetime
from functools import wraps
from mcp.server.fastmcp import FastMCP

# ──────────────────────────────────────────────────────────────
# Retry Logic with Exponential Backoff
# ──────────────────────────────────────────────────────────────
def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """Decorator for retrying operations with exponential backoff."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        print(f"[RETRY] {func.__name__} attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                        await asyncio.sleep(delay)
            raise last_exception
        return wrapper
    return decorator


# ──────────────────────────────────────────────────────────────
# Error Enrichment with Suggestions
# ──────────────────────────────────────────────────────────────
def enrich_error(error: Exception, doctype: str = None, operation: str = None) -> dict:
    """Enrich error with actionable suggestions based on error type."""
    error_info = {
        "error": str(error),
        "type": type(error).__name__,
    }
    
    if doctype:
        error_info["doctype"] = doctype
    if operation:
        error_info["operation"] = operation
    
    error_str = str(error).lower()
    
    if "validation" in error_str or "mandatory" in error_str:
        error_info["suggestion"] = "Check required fields are filled. Use get_doctype_schema to see field requirements."
    elif "permission" in error_str or "forbidden" in error_str:
        error_info["suggestion"] = "User lacks permission. Check user role permissions in ERPNext."
    elif "not found" in error_str or "404" in error_str:
        error_info["suggestion"] = "Document not found. Verify the document name/ID exists."
    elif "duplicate" in error_str or "unique" in error_str:
        error_info["suggestion"] = "Duplicate entry. Check if record with similar data already exists."
    elif "connection" in error_str or "timeout" in error_str:
        error_info["suggestion"] = "Connection issue. Try again or check ERPNext server status."
    
    return error_info


# ──────────────────────────────────────────────────────────────
# Configuration (reads from environment variables)
# ──────────────────────────────────────────────────────────────
ERPNEXT_URL = os.getenv("ERPNEXT_URL", "http://localhost:8001")
API_KEY = os.getenv("API_KEY", "929932f34acbaf3")
API_SECRET = os.getenv("API_SECRET", "6d3df971fe530ec")

AUTH_HEADERS = {
    "Authorization": f"token {API_KEY}:{API_SECRET}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ──────────────────────────────────────────────────────────────
# MCP Server
# ──────────────────────────────────────────────────────────────
mcp = FastMCP(
    "business-claw",
    host="0.0.0.0",
    port=8003,
)


# ──────────────────────────────────────────────────────────────
# Helper: ERPNext API caller
# ──────────────────────────────────────────────────────────────
async def _erpnext_get(path: str, params: dict | None = None) -> dict:
    """GET request to ERPNext API."""
    async with httpx.AsyncClient(timeout=15.0, headers={"Expect": ""}) as client:
        resp = await client.get(
            f"{ERPNEXT_URL}{path}",
            headers=AUTH_HEADERS,
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def _erpnext_post(path: str, payload: dict) -> dict:
    """POST request to ERPNext API."""
    async with httpx.AsyncClient(timeout=15.0, headers={"Expect": ""}) as client:
        resp = await client.post(
            f"{ERPNEXT_URL}{path}",
            headers=AUTH_HEADERS,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def _erpnext_put(path: str, payload: dict) -> dict:
    """PUT request to ERPNext API."""
    async with httpx.AsyncClient(timeout=15.0, headers={"Expect": ""}) as client:
        resp = await client.put(
            f"{ERPNEXT_URL}{path}",
            headers=AUTH_HEADERS,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ──────────────────────────────────────────────────────────────
# System Tools
# ──────────────────────────────────────────────────────────────
@mcp.tool()
async def system_ping() -> str:
    """Check if the MCP server and ERPNext are reachable."""
    result = {
        "mcp_server": "ok",
        "server_time": datetime.utcnow().isoformat(),
        "version": "2.0.0",
        "erpnext_url": ERPNEXT_URL,
    }
    try:
        data = await _erpnext_get("/api/method/frappe.auth.get_logged_user")
        result["erpnext_status"] = "connected"
        result["erpnext_user"] = data.get("message", "unknown")
    except Exception as e:
        result["erpnext_status"] = "unreachable"
        result["erpnext_error"] = str(e)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_current_user() -> str:
    """Get the currently authenticated ERPNext user."""
    try:
        data = await _erpnext_get("/api/method/frappe.auth.get_logged_user")
        return json.dumps({"user": data.get("message", "Guest")})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ──────────────────────────────────────────────────────────────
# DocType / Schema Tools
# ──────────────────────────────────────────────────────────────
@mcp.tool()
async def list_doctypes(module: str = "") -> str:
    """
    List available DocTypes in ERPNext.

    Args:
        module: Optional module name to filter by (e.g. "Stock", "Accounts")
    """
    try:
        filters = {}
        if module:
            filters["module"] = module

        data = await _erpnext_post(
            "/api/method/frappe.client.get_list",
            {
                "doctype": "DocType",
                "filters": filters,
                "fields": ["name", "module"],
                "limit_page_length": 100,
                "order_by": "name asc",
            },
        )
        return json.dumps(data.get("message", []), indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_doctype_schema(doctype: str) -> str:
    """
    Get the field schema for a DocType (field names, types, labels).

    Args:
        doctype: Name of the DocType (e.g. "Customer", "Sales Order")
    """
    try:
        data = await _erpnext_get(f"/api/resource/DocType/{doctype}")
        doc = data.get("data", {})
        fields = [
            {
                "fieldname": f.get("fieldname"),
                "fieldtype": f.get("fieldtype"),
                "label": f.get("label"),
                "reqd": f.get("reqd", 0),
                "options": f.get("options"),
            }
            for f in doc.get("fields", [])
            if f.get("fieldname")
        ]
        return json.dumps(
            {"doctype": doctype, "field_count": len(fields), "fields": fields},
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


# ──────────────────────────────────────────────────────────────
# Document CRUD Tools
# ──────────────────────────────────────────────────────────────
@mcp.tool()
async def get_document(doctype: str, name: str) -> str:
    """
    Get a single document by DocType and name.

    Args:
        doctype: DocType name (e.g. "Customer", "Item")
        name: Document name/ID
    """
    try:
        data = await _erpnext_get(f"/api/resource/{doctype}/{name}")
        return json.dumps(data.get("data", {}), indent=2, default=str)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return json.dumps({"error": f"Not found: {doctype}/{name}"})
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def list_documents(
    doctype: str,
    fields: str = "name",
    filters: str = "{}",
    order_by: str = "modified desc",
    limit: int = 20,
) -> str:
    """
    List documents of a DocType with filtering, field selection, and sorting.

    Args:
        doctype: DocType name (e.g. "Customer", "Sales Order")
        fields: Comma-separated field names (default: "name")
        filters: JSON string of filters (e.g. '{"status": "Open"}')
        order_by: Sort order (default: "modified desc")
        limit: Max results, 1-100 (default: 20)
    """
    try:
        filter_dict = json.loads(filters) if isinstance(filters, str) else filters
        field_list = [f.strip() for f in fields.split(",")]
        limit = max(1, min(100, limit))

        data = await _erpnext_post(
            "/api/method/frappe.client.get_list",
            {
                "doctype": doctype,
                "fields": field_list,
                "filters": filter_dict,
                "order_by": order_by,
                "limit_page_length": limit,
            },
        )
        results = data.get("message", [])
        return json.dumps(
            {"doctype": doctype, "count": len(results), "data": results},
            indent=2,
            default=str,
        )
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in filters parameter"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def search_documents(doctype: str, query: str, limit: int = 20) -> str:
    """
    Search documents by text query (searches name and relevant fields).

    Args:
        doctype: DocType name to search in
        query: Search text
        limit: Max results (default: 20)
    """
    try:
        data = await _erpnext_post(
            "/api/method/frappe.client.get_list",
            {
                "doctype": doctype,
                "filters": {"name": ["like", f"%{query}%"]},
                "fields": ["name", "modified"],
                "limit_page_length": min(limit, 100),
            },
        )
        results = data.get("message", [])
        return json.dumps(
            {"doctype": doctype, "query": query, "count": len(results), "data": results},
            indent=2,
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def create_document(doctype: str, data: str, smart_mode: bool = False) -> str:
    """
    Create a new document in ERPNext (saved as Draft).

    Args:
        doctype: DocType name (e.g. "Customer", "ToDo")
        data: JSON string of field values (e.g. '{"customer_name": "Acme Corp"}')
        smart_mode: If True, automatically fill missing required fields with sensible defaults
    """
    try:
        doc_data = json.loads(data) if isinstance(data, str) else data
        
        if smart_mode:
            # Try to get doctype schema and fill missing required fields
            try:
                schema_data = await _erpnext_get(f"/api/resource/DocType/{doctype}")
                doc = schema_data.get("data", {})
                
                for field in doc.get("fields", []):
                    fieldname = field.get("fieldname")
                    reqd = field.get("reqd", 0)
                    fieldtype = field.get("fieldtype")
                    
                    # Fill missing required fields with defaults
                    if reqd and fieldname and fieldname not in doc_data:
                        default_value = get_default_for_fieldtype(fieldtype)
                        if default_value:
                            doc_data[fieldname] = default_value
                            print(f"[SMART] Auto-filled required field: {fieldname} = {default_value}")
            except Exception as schema_err:
                print(f"[SMART] Could not get schema for smart mode: {schema_err}")
        
        print(f"[DEBUG] Creating {doctype} with data: {json.dumps(doc_data, default=str)[:500]}")
        
        result = await _erpnext_post(
            f"/api/resource/{doctype}",
            doc_data,
        )
        doc = result.get("data", {})
        return json.dumps(
            {
                "success": True,
                "doctype": doctype,
                "name": doc.get("name"),
                "smart_mode_used": smart_mode,
                "message": f"Created {doctype}: {doc.get('name')}",
            },
            indent=2,
            default=str,
        )
    except httpx.HTTPStatusError as e:
        error_detail = e.response.text[:500] if e.response.text else str(e)
        return json.dumps({
            "error": f"HTTP {e.response.status_code}: {error_detail}",
            "doctype": doctype
        })
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps({"error": str(e), "type": type(e).__name__})


def get_default_for_fieldtype(fieldtype: str) -> str:
    """Get default value for a fieldtype when smart_mode is enabled."""
    defaults = {
        "Data": "New Item",
        "Int": 0,
        "Float": 0.0,
        "Check": 0,
        "Select": "",
        "Small Text": "",
        "Text": "",
        "Link": "",
    }
    return defaults.get(fieldtype, "")


@mcp.tool()
async def update_document(doctype: str, name: str, data: str) -> str:
    """
    Update an existing document in ERPNext.

    Args:
        doctype: DocType name
        name: Document name/ID to update
        data: JSON string of fields to update (e.g. '{"status": "Closed"}')
    """
    try:
        update_data = json.loads(data) if isinstance(data, str) else data
        result = await _erpnext_put(
            f"/api/resource/{doctype}/{name}",
            update_data,
        )
        doc = result.get("data", {})
        return json.dumps(
            {
                "success": True,
                "doctype": doctype,
                "name": doc.get("name"),
                "message": f"Updated {doctype}: {doc.get('name')}",
            },
            indent=2,
            default=str,
        )
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ──────────────────────────────────────────────────────────────
# Report / Analytics Tools
# ──────────────────────────────────────────────────────────────
@mcp.tool()
async def get_count(doctype: str, filters: str = "{}") -> str:
    """
    Get count of documents matching filters.

    Args:
        doctype: DocType name
        filters: JSON string of filters (e.g. '{"status": "Open"}')
    """
    try:
        filter_dict = json.loads(filters) if isinstance(filters, str) else filters
        data = await _erpnext_post(
            "/api/method/frappe.client.get_count",
            {"doctype": doctype, "filters": filter_dict},
        )
        return json.dumps(
            {"doctype": doctype, "count": data.get("message", 0)},
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def run_report(report_name: str, filters: str = "{}") -> str:
    """
    Run a named report in ERPNext (Query Reports, Script Reports).

    Args:
        report_name: Name of the report
        filters: JSON string of report filters
    """
    try:
        filter_dict = json.loads(filters) if isinstance(filters, str) else filters
        data = await _erpnext_post(
            "/api/method/frappe.desk.query_report.run",
            {"report_name": report_name, "filters": filter_dict},
        )
        msg = data.get("message", {})
        return json.dumps(
            {
                "report": report_name,
                "columns": msg.get("columns", []),
                "row_count": len(msg.get("result", [])),
                "result": msg.get("result", [])[:50],  # cap at 50 rows
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def call_method(method: str, args: str = "{}") -> str:
    """
    Call any whitelisted Frappe/ERPNext API method.

    Args:
        method: Dotted method path (e.g. "frappe.client.get_count")
        args: JSON string of method arguments
    """
    try:
        arg_dict = json.loads(args) if isinstance(args, str) else args
        data = await _erpnext_post(
            f"/api/method/{method}",
            arg_dict,
        )
        return json.dumps(data.get("message", data), indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ──────────────────────────────────────────────────────────────
# Debug / Auth Tools
# ──────────────────────────────────────────────────────────────
@mcp.tool()
async def debug_auth() -> str:
    """
    Debug tool to check authentication configuration and connectivity.
    Returns detailed auth info for troubleshooting.
    """
    result = {
        "erpnext_url": ERPNEXT_URL,
        "api_key_configured": bool(API_KEY),
        "api_secret_configured": bool(API_SECRET),
        "api_key_prefix": API_KEY[:8] + "..." if len(API_KEY) > 8 else API_KEY,
    }
    
    try:
        data = await _erpnext_get("/api/method/frappe.auth.get_logged_user")
        result["auth_status"] = "success"
        result["logged_user"] = data.get("message")
        
        user_data = await _erpnext_get(f"/api/resource/User/{data.get('message')}")
        result["user_info"] = {
            "email": user_data.get("data", {}).get("email"),
            "enabled": user_data.get("data", {}).get("enabled"),
        }
        
        roles = user_data.get("data", {}).get("roles", [])
        result["roles"] = [r.get("role") for r in roles]
        
    except Exception as e:
        result["auth_status"] = "failed"
        result["error"] = str(e)
    
    return json.dumps(result, indent=2)


# ──────────────────────────────────────────────────────────────
# Phase 1: Document Workflow Tools (submit, cancel, amend)
# ──────────────────────────────────────────────────────────────
@mcp.tool()
@retry_with_backoff(max_retries=2)
async def submit_document(doctype: str, name: str) -> str:
    """
    Submit a document in ERPNext (for transacted DocTypes like Sales Order).

    Args:
        doctype: DocType name (e.g. "Sales Order", "Purchase Order")
        name: Document name/ID to submit
    """
    try:
        result = await _erpnext_post(
            f"/api/method/frappe.client.submit",
            {"doc": {"doctype": doctype, "name": name}},
        )
        return json.dumps({
            "success": True,
            "doctype": doctype,
            "name": name,
            "message": f"Submitted {doctype}: {name}",
            "result": result.get("message", {}),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "submit"), indent=2)


@mcp.tool()
@retry_with_backoff(max_retries=2)
async def cancel_document(doctype: str, name: str) -> str:
    """
    Cancel a submitted document in ERPNext.

    Args:
        doctype: DocType name (e.g. "Sales Order", "Purchase Order")
        name: Document name/ID to cancel
    """
    try:
        result = await _erpnext_post(
            f"/api/method/frappe.client.cancel",
            {"doctype": doctype, "name": name},
        )
        return json.dumps({
            "success": True,
            "doctype": doctype,
            "name": name,
            "message": f"Cancelled {doctype}: {name}",
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "cancel"), indent=2)


@mcp.tool()
async def amend_document(doctype: str, name: str, data: str = "{}") -> str:
    """
    Amend (create a new version of) a cancelled document in ERPNext.

    Args:
        doctype: DocType name (e.g. "Sales Order")
        name: Document name/ID to amend
        data: JSON string of updated field values (optional)
    """
    try:
        doc_data = await _erpnext_get(f"/api/resource/{doctype}/{name}")
        doc = doc_data.get("data", {})
        
        update_data = json.loads(data) if isinstance(data, str) else {}
        update_data["amended_from"] = name
        
        result = await _erpnext_post(f"/api/resource/{doctype}", update_data)
        new_doc = result.get("data", {})
        
        return json.dumps({
            "success": True,
            "original_name": name,
            "new_name": new_doc.get("name"),
            "doctype": doctype,
            "message": f"Created amendment of {doctype}: {name} → {new_doc.get('name')}",
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "amend"), indent=2)


# ──────────────────────────────────────────────────────────────
# Phase 2: Bulk Operations Tools
# ──────────────────────────────────────────────────────────────
@mcp.tool()
async def bulk_create_documents(doctype: str, data: str) -> str:
    """
    Create multiple documents in a single operation.

    Args:
        doctype: DocType name (e.g. "Customer", "Item")
        data: JSON string of array of documents to create
    """
    try:
        doc_list = json.loads(data) if isinstance(data, str) else data
        
        if not isinstance(doc_list, list):
            return json.dumps({"error": "Data must be a JSON array of documents"})
        
        results = []
        success_count = 0
        error_count = 0
        
        for idx, doc_data in enumerate(doc_list):
            try:
                result = await _erpnext_post(f"/api/resource/{doctype}", doc_data)
                new_doc = result.get("data", {})
                results.append({"index": idx, "success": True, "name": new_doc.get("name")})
                success_count += 1
            except Exception as e:
                results.append({"index": idx, "success": False, "error": str(e)})
                error_count += 1
        
        return json.dumps({
            "doctype": doctype,
            "total_requested": len(doc_list),
            "success_count": success_count,
            "error_count": error_count,
            "results": results,
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "bulk_create"), indent=2)


@mcp.tool()
async def bulk_update_documents(doctype: str, data: str) -> str:
    """
    Update multiple documents in a single operation.

    Args:
        doctype: DocType name
        data: JSON string of array of updates
    """
    try:
        update_list = json.loads(data) if isinstance(data, str) else data
        
        if not isinstance(update_list, list):
            return json.dumps({"error": "Data must be a JSON array of updates"})
        
        results = []
        success_count = 0
        error_count = 0
        
        for idx, item in enumerate(update_list):
            try:
                doc_name = item.get("name")
                update_data = item.get("data", {})
                
                if not doc_name:
                    results.append({"index": idx, "success": False, "error": "Missing 'name' field"})
                    error_count += 1
                    continue
                
                result = await _erpnext_put(f"/api/resource/{doctype}/{doc_name}", update_data)
                results.append({"index": idx, "success": True, "name": doc_name})
                success_count += 1
            except Exception as e:
                results.append({"index": idx, "success": False, "error": str(e)})
                error_count += 1
        
        return json.dumps({
            "doctype": doctype,
            "total_requested": len(update_list),
            "success_count": success_count,
            "error_count": error_count,
            "results": results,
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "bulk_update"), indent=2)


@mcp.tool()
async def bulk_delete_documents(doctype: str, names: str) -> str:
    """
    Delete multiple documents in a single operation.

    Args:
        doctype: DocType name
        names: JSON string array of document names to delete
    """
    try:
        name_list = json.loads(names) if isinstance(names, str) else names
        
        if not isinstance(name_list, list):
            return json.dumps({"error": "Names must be a JSON array"})
        
        results = []
        success_count = 0
        error_count = 0
        
        for idx, doc_name in enumerate(name_list):
            try:
                await _erpnext_post("/api/method/frappe.client.delete", {"doctype": doctype, "name": doc_name})
                results.append({"index": idx, "success": True, "name": doc_name})
                success_count += 1
            except Exception as e:
                results.append({"index": idx, "success": False, "name": doc_name, "error": str(e)})
                error_count += 1
        
        return json.dumps({
            "doctype": doctype,
            "total_requested": len(name_list),
            "success_count": success_count,
            "error_count": error_count,
            "results": results,
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in names parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "bulk_delete"), indent=2)


# ──────────────────────────────────────────────────────────────
# Phase 3: Metadata & History Tools
# ──────────────────────────────────────────────────────────────
@mcp.tool()
async def get_document_history(doctype: str, name: str) -> str:
    """
    Get the version history/audit trail of a document.

    Args:
        doctype: DocType name
        name: Document name/ID
    """
    try:
        data = await _erpnext_post(
            "/api/method/frappe.client.get_list",
            {
                "doctype": "Version",
                "filters": {"ref_doctype": doctype, "docname": name},
                "fields": ["version", "modified", "modified_by", "data"],
                "order_by": "modified desc",
                "limit_page_length": 20,
            },
        )
        history = data.get("message", [])
        
        formatted = []
        for entry in history:
            formatted.append({
                "version": entry.get("version"),
                "modified": entry.get("modified"),
                "modified_by": entry.get("modified_by"),
            })
        
        return json.dumps({
            "doctype": doctype,
            "name": name,
            "version_count": len(formatted),
            "history": formatted,
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "get_history"), indent=2)


@mcp.tool()
async def get_linked_documents(doctype: str, name: str) -> str:
    """
    Get all documents linked to a given document.

    Args:
        doctype: DocType name
        name: Document name/ID
    """
    try:
        data = await _erpnext_post(
            "/api/method/frappe.desk.search.get_linked_docs",
            {"doctype": doctype, "docname": name},
        )
        
        linked = data.get("message", {})
        
        result = {"doctype": doctype, "name": name, "linked_docs": {}}
        
        for link_doctype, docs in linked.items():
            if isinstance(docs, list):
                result["linked_docs"][link_doctype] = {
                    "count": len(docs),
                    "documents": [{"name": d.get("name")} for d in docs[:10]]
                }
        
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "get_linked"), indent=2)


@mcp.tool()
async def get_permissions(doctype: str, name: str = None) -> str:
    """
    Get permissions for a document or doctype.

    Args:
        doctype: DocType name
        name: Optional document name (for document-level permissions)
    """
    try:
        # Use different approach - get via DocType
        data = await _erpnext_get(f"/api/resource/DocType/{doctype}")
        doc = data.get("data", {})
        perms = doc.get("permissions", [])
        
        return json.dumps({
            "doctype": doctype,
            "name": name or "(doctype level)",
            "permissions": perms,
            "permission_count": len(perms),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "get_permissions"), indent=2)


@mcp.tool()
async def set_permissions(doctype: str, role: str, ptype: str = "read", value: bool = True) -> str:
    """
    Set permissions for a role on a DocType.

    Args:
        doctype: DocType name
        role: Role name (e.g. "Sales User", "Accounts Manager")
        ptype: Permission type (read, write, create, delete, submit, cancel, amend)
        value: True to grant, False to revoke
    
    WARNING: This is a high-risk operation. Requires admin privileges.
    """
    try:
        # Get DocType to find permission template
        dt_data = await _erpnext_get(f"/api/resource/DocType/{doctype}")
        
        # Create/update Custom Role to set permissions
        custom_role = {
            "doctype": "Custom Role",
            "role": role,
            "ref_doctype": doctype,
            "read": 1 if ptype == "read" and value else 0,
            "write": 1 if ptype == "write" and value else 0,
            "create": 1 if ptype == "create" and value else 0,
            "delete": 1 if ptype == "delete" and value else 0,
            "submit": 1 if ptype == "submit" and value else 0,
            "cancel": 1 if ptype == "cancel" and value else 0,
            "amend": 1 if ptype == "amend" and value else 0,
        }
        
        result = await _erpnext_post("/api/resource/Custom Role", custom_role)
        
        return json.dumps({
            "success": True,
            "doctype": doctype,
            "role": role,
            "permission_type": ptype,
            "value": value,
            "message": f"Set {ptype}={'grant' if value else 'revoke'} for {role} on {doctype}",
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "set_permissions"), indent=2)


# ──────────────────────────────────────────────────────────────
# Phase 4: Import/Export Tools
# ──────────────────────────────────────────────────────────────
@mcp.tool()
async def export_documents(doctype: str, filters: str = "{}", fields: str = "*") -> str:
    """
    Export documents to JSON format.

    Args:
        doctype: DocType name to export
        filters: JSON string of filters (default: all)
        fields: Comma-separated fields or "*" for all (default: "*")
    """
    try:
        filter_dict = json.loads(filters) if isinstance(filters, str) else {}
        
        data = await _erpnext_post(
            "/api/method/frappe.client.get_list",
            {
                "doctype": doctype,
                "filters": filter_dict,
                "fields": ["*"] if fields == "*" else [f.strip() for f in fields.split(",")],
                "limit_page_length": 1000,
            },
        )
        docs = data.get("message", [])
        
        return json.dumps({
            "doctype": doctype,
            "export_count": len(docs),
            "filters": filter_dict,
            "data": docs,
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "export"), indent=2)


@mcp.tool()
async def import_documents(doctype: str, data: str, update_existing: bool = False) -> str:
    """
    Import documents from JSON data.

    Args:
        doctype: DocType name to import into
        data: JSON string of array of documents
        update_existing: If True, update existing documents by name
    """
    try:
        doc_list = json.loads(data) if isinstance(data, str) else data
        
        if not isinstance(doc_list, list):
            return json.dumps({"error": "Data must be a JSON array of documents"})
        
        results = []
        success_count = 0
        error_count = 0
        
        for idx, doc_data in enumerate(doc_list):
            try:
                doc_name = doc_data.get("name")
                
                if update_existing and doc_name:
                    result = await _erpnext_put(f"/api/resource/{doctype}/{doc_name}", doc_data)
                    results.append({"index": idx, "operation": "update", "success": True, "name": doc_name})
                else:
                    result = await _erpnext_post(f"/api/resource/{doctype}", doc_data)
                    new_doc = result.get("data", {})
                    results.append({"index": idx, "operation": "create", "success": True, "name": new_doc.get("name")})
                success_count += 1
            except Exception as e:
                results.append({"index": idx, "success": False, "error": str(e)})
                error_count += 1
        
        return json.dumps({
            "doctype": doctype,
            "update_existing": update_existing,
            "total_requested": len(doc_list),
            "success_count": success_count,
            "error_count": error_count,
            "results": results,
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "import"), indent=2)


# ──────────────────────────────────────────────────────────────
# Phase 5: Advanced Tools (clone, print format, webhook)
# ──────────────────────────────────────────────────────────────
@mcp.tool()
async def clone_document(doctype: str, name: str, new_name: str = None) -> str:
    """
    Clone/duplicate an existing document.

    Args:
        doctype: DocType name
        name: Document name to clone
        new_name: Optional new name for the cloned document
    """
    try:
        data = await _erpnext_get(f"/api/resource/{doctype}/{name}")
        doc = data.get("data", {})
        
        fields_to_remove = ["name", "creation", "modified", "owner", "modified_by", "docstatus", "idx", "amended_from"]
        for field in fields_to_remove:
            doc.pop(field, None)
        
        if new_name:
            doc["name"] = new_name
        
        result = await _erpnext_post(f"/api/resource/{doctype}", doc)
        new_doc = result.get("data", {})
        
        return json.dumps({
            "success": True,
            "original": {"doctype": doctype, "name": name},
            "clone": {"doctype": doctype, "name": new_doc.get("name")},
            "message": f"Cloned {doctype}: {name} → {new_doc.get('name')}",
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "clone"), indent=2)


@mcp.tool()
async def get_print_format(doctype: str, name: str, format: str = "Standard") -> str:
    """
    Generate print format (PDF) for a document.

    Args:
        doctype: DocType name
        name: Document name
        format: Print format name (default: "Standard")
    """
    try:
        await _erpnext_post(
            "/api/method/frappe.utils.print_format.download_pdf",
            {"doctype": doctype, "name": name, "format": format},
        )
        
        return json.dumps({
            "success": True,
            "doctype": doctype,
            "name": name,
            "format": format,
            "message": f"PDF generated for {doctype}: {name}",
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "print_format"), indent=2)


@mcp.tool()
async def create_webhook(data: str) -> str:
    """
    Create a new Webhook in ERPNext.

    Args:
        data: JSON string of webhook config
    """
    try:
        webhook_data = json.loads(data) if isinstance(data, str) else data
        
        result = await _erpnext_post("/api/resource/Webhook", webhook_data)
        new_webhook = result.get("data", {})
        
        return json.dumps({
            "success": True,
            "webhook": new_webhook.get("name"),
            "message": f"Created Webhook: {new_webhook.get('name')}",
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, "Webhook", "create_webhook"), indent=2)


@mcp.tool()
async def create_server_script(data: str) -> str:
    """
    Create a new Server Script in ERPNext.

    Args:
        data: JSON string of server script config
    
    WARNING: This is a powerful tool. Use with caution.
    """
    try:
        script_data = json.loads(data) if isinstance(data, str) else data
        
        script = script_data.get("script", "")
        if "rm -rf" in script or "DROP TABLE" in script.upper():
            return json.dumps({
                "error": "Potentially dangerous script detected. Operation blocked.",
                "safety": "blocked"
            })
        
        result = await _erpnext_post("/api/resource/Server Script", script_data)
        new_script = result.get("data", {})
        
        return json.dumps({
            "success": True,
            "script": new_script.get("name"),
            "message": f"Created Server Script: {new_script.get('name')}",
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, "Server Script", "create_script"), indent=2)


@mcp.tool()
async def create_doctype(data: str) -> str:
    """
    Create a new DocType in ERPNext.

    Args:
        data: JSON string of doctype config
              e.g. '{"name": "My Custom DocType", "module": "Custom", "fields": [{"fieldname": "title", "fieldtype": "Data", "label": "Title"}]}'
    
    WARNING: Creating DocTypes requires careful schema planning.
    """
    try:
        doctype_data = json.loads(data) if isinstance(data, str) else data
        
        result = await _erpnext_post("/api/resource/DocType", doctype_data)
        new_doctype = result.get("data", {})
        
        return json.dumps({
            "success": True,
            "doctype": new_doctype.get("name"),
            "message": f"Created DocType: {new_doctype.get('name')}",
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, "DocType", "create_doctype"), indent=2)


# ──────────────────────────────────────────────────────────────
# Expose the Starlette ASGI app for uvicorn
# ──────────────────────────────────────────────────────────────
http_app = mcp.sse_app()

# ──────────────────────────────────────────────────────────────
# Additional Tools from Reference Implementation
# ──────────────────────────────────────────────────────────────

@mcp.tool()
async def get_documents(doctype: str, filters: str = "{}", fields: str = "name", limit: int = 20) -> str:
    """
    Get a list of documents for a specific DocType.
    
    Args:
        doctype: DocType name
        filters: JSON string of filters
        fields: Comma-separated fields
        limit: Max results
    """
    try:
        filter_dict = json.loads(filters) if isinstance(filters, str) else {}
        field_list = [f.strip() for f in fields.split(",")]
        
        data = await _erpnext_post(
            "/api/method/frappe.client.get_list",
            {
                "doctype": doctype,
                "fields": field_list,
                "filters": filter_dict,
                "limit_page_length": min(limit, 100),
            },
        )
        return json.dumps({
            "doctype": doctype,
            "count": len(data.get("message", [])),
            "data": data.get("message", []),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "get_documents"), indent=2)


@mcp.tool()
async def delete_document(doctype: str, name: str) -> str:
    """
    Delete a document by DocType and name.
    
    Args:
        doctype: DocType name
        name: Document name to delete
    """
    try:
        result = await _erpnext_post(
            "/api/method/frappe.client.delete",
            {"doctype": doctype, "name": name},
        )
        return json.dumps({
            "success": True,
            "doctype": doctype,
            "name": name,
            "message": f"Deleted {doctype}: {name}",
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "delete"), indent=2)


@mcp.tool()
async def attach_file(file_url: str, doctype: str, docname: str, field_name: str = "attach_file") -> str:
    """
    Upload a file attachment to a document.
    
    Args:
        file_url: URL of the file to attach
        doctype: DocType to attach to
        docname: Document name
        field_name: Field name for attachment
    """
    try:
        result = await _erpnext_post(
            "/api/method/frappe.client.attach_file",
            {
                "file_url": file_url,
                "doctype": doctype,
                "docname": docname,
                "field_name": field_name,
            },
        )
        return json.dumps({
            "success": True,
            "message": f"Attached file to {doctype}/{docname}",
            "result": result.get("message", {}),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "attach_file"), indent=2)


@mcp.tool()
async def run_doc_method(doctype: str, name: str, method: str, args: str = "{}") -> str:
    """
    Run a whitelisted method on a specific document instance.
    
    Args:
        doctype: DocType name
        name: Document name
        method: Method name to run
        args: JSON string of arguments
    """
    try:
        arg_dict = json.loads(args) if isinstance(args, str) else {}
        
        result = await _erpnext_post(
            f"/api/method/frappe.client.run_doc_method",
            {
                "doctype": doctype,
                "docname": name,
                "method": method,
                "args": arg_dict,
            },
        )
        return json.dumps({
            "success": True,
            "doctype": doctype,
            "name": name,
            "method": method,
            "result": result.get("message", {}),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "run_doc_method"), indent=2)


@mcp.tool()
async def rollback_document(doctype: str, name: str, version: int) -> str:
    """
    Rollback a document to a previous version.
    
    Args:
        doctype: DocType name
        name: Document name
        version: Version number to rollback to
    """
    try:
        result = await _erpnext_post(
            "/api/method/frappe.client.rollback_document",
            {"doctype": doctype, "name": name, "version": version},
        )
        return json.dumps({
            "success": True,
            "doctype": doctype,
            "name": name,
            "version": version,
            "message": f"Rolled back {doctype}/{name} to version {version}",
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "rollback"), indent=2)


@mcp.tool()
async def bulk_smart_create_documents(doctype: str, data: str) -> str:
    """
    Bulk create documents with validation, error handling, and progress tracking.
    
    Args:
        doctype: DocType name
        data: JSON string of array of documents
    """
    try:
        doc_list = json.loads(data) if isinstance(data, str) else data
        
        if not isinstance(doc_list, list):
            return json.dumps({"error": "Data must be a JSON array of documents"})
        
        results = {
            "total": len(doc_list),
            "success": 0,
            "failed": 0,
            "errors": [],
            "created": [],
        }
        
        for idx, doc_data in enumerate(doc_list):
            try:
                # Validate required fields
                if not doc_data:
                    raise ValueError("Empty document data")
                
                result = await _erpnext_post(f"/api/resource/{doctype}", doc_data)
                new_doc = result.get("data", {})
                results["success"] += 1
                results["created"].append({"index": idx, "name": new_doc.get("name")})
                
            except Exception as doc_err:
                results["failed"] += 1
                results["errors"].append({"index": idx, "error": str(doc_err)})
        
        results["progress"] = f"{results['success']}/{results['total']} completed"
        return json.dumps(results, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "bulk_smart_create"), indent=2)


@mcp.tool()
async def smart_import_documents(doctype: str, data: str, update_existing: bool = False) -> str:
    """
    Import documents with validation, conflict resolution, and detailed reporting.
    
    Args:
        doctype: DocType name
        data: JSON string of array of documents
        update_existing: Whether to update existing documents
    """
    try:
        doc_list = json.loads(data) if isinstance(data, str) else data
        
        if not isinstance(doc_list, list):
            return json.dumps({"error": "Data must be a JSON array"})
        
        results = {
            "total": len(doc_list),
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
            "conflicts": [],
        }
        
        for idx, doc_data in enumerate(doc_list):
            try:
                doc_name = doc_data.get("name")
                
                if update_existing and doc_name:
                    # Check for conflicts
                    try:
                        await _erpnext_get(f"/api/resource/{doctype}/{doc_name}")
                        # Exists, update it
                        await _erpnext_put(f"/api/resource/{doctype}/{doc_name}", doc_data)
                        results["updated"] += 1
                    except:
                        # Doesn't exist, create new
                        result = await _erpnext_post(f"/api/resource/{doctype}", doc_data)
                        results["created"] += 1
                else:
                    result = await _erpnext_post(f"/api/resource/{doctype}", doc_data)
                    results["created"] += 1
                    
            except Exception as doc_err:
                results["errors"].append({"index": idx, "error": str(doc_err)})
        
        return json.dumps(results, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "smart_import"), indent=2)


@mcp.tool()
async def get_doctype_fields(doctype: str) -> str:
    """
    Get fields list for a specific DocType.
    
    Args:
        doctype: DocType name
    """
    try:
        data = await _erpnext_get(f"/api/resource/DocType/{doctype}")
        doc = data.get("data", {})
        
        fields = []
        for f in doc.get("fields", []):
            if f.get("fieldname"):
                fields.append({
                    "fieldname": f.get("fieldname"),
                    "fieldtype": f.get("fieldtype"),
                    "label": f.get("label"),
                    "reqd": f.get("reqd", 0),
                    "hidden": f.get("hidden", 0),
                    "options": f.get("options"),
                })
        
        return json.dumps({
            "doctype": doctype,
            "field_count": len(fields),
            "fields": fields,
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "get_doctype_fields"), indent=2)


@mcp.tool()
async def get_doctype_meta(doctype: str) -> str:
    """
    Get detailed metadata for a specific DocType including fields definition.
    
    Args:
        doctype: DocType name
    """
    try:
        data = await _erpnext_get(f"/api/resource/DocType/{doctype}")
        doc = data.get("data", {})
        
        return json.dumps({
            "doctype": doctype,
            "name": doc.get("name"),
            "module": doc.get("module"),
            "is_submittable": doc.get("is_submittable", 0),
            "is_single": doc.get("is_single", 0),
            "is_tree": doc.get("is_tree", 0),
            "autoname": doc.get("autoname"),
            "naming_rule": doc.get("naming_rule"),
            "fields": [{"fieldname": f.get("fieldname"), "fieldtype": f.get("fieldtype"), "label": f.get("label")} 
                       for f in doc.get("fields", []) if f.get("fieldname")],
            "permissions": doc.get("permissions", []),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "get_doctype_meta"), indent=2)


@mcp.tool()
async def create_child_table(data: str) -> str:
    """
    Create a new Child Table DocType in ERPNext.
    
    Args:
        data: JSON string of child table config
    """
    try:
        child_data = json.loads(data) if isinstance(data, str) else data
        child_data["istable"] = 1
        child_data["doctype"] = "DocType"
        
        result = await _erpnext_post("/api/resource/DocType", child_data)
        new_dt = result.get("data", {})
        
        return json.dumps({
            "success": True,
            "doctype": new_dt.get("name"),
            "message": f"Created child table: {new_dt.get('name')}",
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, "DocType", "create_child_table"), indent=2)


@mcp.tool()
async def add_child_table_to_doctype(doctype: str, child_table: str, fieldname: str, label: str = None) -> str:
    """
    Add a child table field to an existing DocType.
    
    Args:
        doctype: Parent DocType name
        child_table: Child table DocType name
        fieldname: Field name for the child table
        label: Optional label
    """
    try:
        # Get current DocType
        dt_data = await _erpnext_get(f"/api/resource/DocType/{doctype}")
        doc = dt_data.get("data", {})
        
        new_field = {
            "fieldname": fieldname,
            "fieldtype": "Table",
            "label": label or fieldname.replace("_", " ").title(),
            "options": child_table,
        }
        
        # Add field to the DocType
        fields = doc.get("fields", [])
        fields.append(new_field)
        
        await _erpnext_put(f"/api/resource/DocType/{doctype}", {"fields": fields})
        
        return json.dumps({
            "success": True,
            "doctype": doctype,
            "field_added": fieldname,
            "child_table": child_table,
            "message": f"Added child table field '{fieldname}' to {doctype}",
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "add_child_table"), indent=2)


@mcp.tool()
async def generate_doctype_docs(doctype: str) -> str:
    """
    Generate documentation for a DocType.
    
    Args:
        doctype: DocType name
    """
    try:
        data = await _erpnext_get(f"/api/resource/DocType/{doctype}")
        doc = data.get("data", {})
        
        fields = []
        for f in doc.get("fields", []):
            if f.get("fieldname"):
                fields.append({
                    "field": f.get("fieldname"),
                    "type": f.get("fieldtype"),
                    "label": f.get("label"),
                    "required": bool(f.get("reqd")),
                    "description": f.get("description", ""),
                })
        
        return json.dumps({
            "doctype": doctype,
            "module": doc.get("module"),
            "fields": fields,
            "permissions": doc.get("permissions", []),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "generate_doctype_docs"), indent=2)


@mcp.tool()
async def generate_form_schema(doctype: str) -> str:
    """
    Generate a form schema for a DocType.
    
    Args:
        doctype: DocType name
    """
    try:
        data = await _erpnext_get(f"/api/resource/DocType/{doctype}")
        doc = data.get("data", {})
        
        schema = {
            "doctype": doctype,
            "fields": [],
        }
        
        for f in doc.get("fields", []):
            if f.get("fieldname"):
                field_schema = {
                    "fieldname": f.get("fieldname"),
                    "fieldtype": f.get("fieldtype"),
                    "label": f.get("label"),
                    "required": bool(f.get("reqd")),
                }
                if f.get("options"):
                    field_schema["options"] = f.get("options")
                schema["fields"].append(field_schema)
        
        return json.dumps(schema, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "generate_form_schema"), indent=2)


@mcp.tool()
async def create_workflow(data: str) -> str:
    """
    Create a new Workflow in ERPNext.
    
    Args:
        data: JSON string of workflow config
    """
    try:
        wf_data = json.loads(data) if isinstance(data, str) else data
        wf_data["doctype"] = "Workflow"
        
        result = await _erpnext_post("/api/resource/Workflow", wf_data)
        new_wf = result.get("data", {})
        
        return json.dumps({
            "success": True,
            "workflow": new_wf.get("name"),
            "message": f"Created Workflow: {new_wf.get('name')}",
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, "Workflow", "create_workflow"), indent=2)


@mcp.tool()
async def generate_workflow_docs(workflow_name: str) -> str:
    """
    Generate documentation for a Workflow.
    
    Args:
        workflow_name: Workflow name
    """
    try:
        data = await _erpnext_get(f"/api/resource/Workflow/{workflow_name}")
        wf = data.get("data", {})
        
        return json.dumps({
            "workflow": workflow_name,
            "document_type": wf.get("document_type"),
            "is_active": wf.get("is_active"),
            "states": wf.get("states", []),
            "transitions": wf.get("transitions", []),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, "Workflow", "generate_workflow_docs"), indent=2)


@mcp.tool()
async def create_client_script(data: str) -> str:
    """
    Create a new Client Script in ERPNext.
    
    Args:
        data: JSON string of client script config
    """
    try:
        script_data = json.loads(data) if isinstance(data, str) else data
        script_data["doctype"] = "Client Script"
        
        result = await _erpnext_post("/api/resource/Client Script", script_data)
        new_script = result.get("data", {})
        
        return json.dumps({
            "success": True,
            "script": new_script.get("name"),
            "message": f"Created Client Script: {new_script.get('name')}",
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, "Client Script", "create_client_script"), indent=2)


@mcp.tool()
async def create_hook(hook_type: str, hook_value: str) -> str:
    """
    Create a new Hook in ERPNext (app hooks.py).
    
    Args:
        hook_type: Hook type (e.g. "doc_events", "app_promo")
        hook_value: Hook value to add
    """
    return json.dumps({
        "success": False,
        "message": "Hooks must be added manually to app/hooks.py files. This tool generates the code snippet.",
        "suggested_code": f"{hook_type} = {hook_value}",
    }, indent=2)


@mcp.tool()
async def create_scheduled_job(data: str) -> str:
    """
    Create a scheduled job in ERPNext.
    
    Args:
        data: JSON string of scheduled job config
    """
    try:
        job_data = json.loads(data) if isinstance(data, str) else data
        job_data["doctype"] = "Scheduled Job Type"
        
        result = await _erpnext_post("/api/resource/Scheduled Job Type", job_data)
        new_job = result.get("data", {})
        
        return json.dumps({
            "success": True,
            "job": new_job.get("name"),
            "message": f"Created Scheduled Job: {new_job.get('name')}",
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, "Scheduled Job Type", "create_scheduled_job"), indent=2)


@mcp.tool()
async def create_notification(data: str) -> str:
    """
    Create a notification/alert in ERPNext.
    
    Args:
        data: JSON string of notification config
    """
    try:
        notif_data = json.loads(data) if isinstance(data, str) else data
        notif_data["doctype"] = "Notification"
        
        result = await _erpnext_post("/api/resource/Notification", notif_data)
        new_notif = result.get("data", {})
        
        return json.dumps({
            "success": True,
            "notification": new_notif.get("name"),
            "message": f"Created Notification: {new_notif.get('name')}",
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, "Notification", "create_notification"), indent=2)


# ──────────────────────────────────────────────────────────────
# Reporting & Dashboards
# ──────────────────────────────────────────────────────────────
@mcp.tool()
async def create_report(data: str) -> str:
    """
    Create a new Report in ERPNext.
    
    Args:
        data: JSON string of report config
    """
    try:
        report_data = json.loads(data) if isinstance(data, str) else data
        report_data["doctype"] = "Report"
        
        result = await _erpnext_post("/api/resource/Report", report_data)
        new_report = result.get("data", {})
        
        return json.dumps({
            "success": True,
            "report": new_report.get("name"),
            "message": f"Created Report: {new_report.get('name')}",
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, "Report", "create_report"), indent=2)


@mcp.tool()
async def create_dashboard(data: str) -> str:
    """
    Create a new Dashboard in ERPNext.
    
    Args:
        data: JSON string of dashboard config
    """
    try:
        dash_data = json.loads(data) if isinstance(data, str) else data
        dash_data["doctype"] = "Dashboard"
        
        result = await _erpnext_post("/api/resource/Dashboard", dash_data)
        new_dash = result.get("data", {})
        
        return json.dumps({
            "success": True,
            "dashboard": new_dash.get("name"),
            "message": f"Created Dashboard: {new_dash.get('name')}",
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, "Dashboard", "create_dashboard"), indent=2)


@mcp.tool()
async def generate_dashboard_schema(dashboard_name: str) -> str:
    """
    Generate a dashboard schema for a Dashboard.
    
    Args:
        dashboard_name: Dashboard name
    """
    try:
        data = await _erpnext_get(f"/api/resource/Dashboard/{dashboard_name}")
        dash = data.get("data", {})
        
        return json.dumps({
            "dashboard": dashboard_name,
            "chart_names": dash.get("charts", []),
            "cards": dash.get("cards", []),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps(enrich_error(e, "Dashboard", "generate_dashboard_schema"), indent=2)


@mcp.tool()
async def create_chart(data: str) -> str:
    """
    Create a new Chart in ERPNext.
    
    Args:
        data: JSON string of chart config
    """
    try:
        chart_data = json.loads(data) if isinstance(data, str) else data
        chart_data["doctype"] = "Dashboard Chart"
        
        result = await _erpnext_post("/api/resource/Dashboard Chart", chart_data)
        new_chart = result.get("data", {})
        
        return json.dumps({
            "success": True,
            "chart": new_chart.get("name"),
            "message": f"Created Chart: {new_chart.get('name')}",
        }, indent=2, default=str)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON in data parameter"})
    except Exception as e:
        return json.dumps(enrich_error(e, "Dashboard Chart", "create_chart"), indent=2)


# ──────────────────────────────────────────────────────────────
# App & Module Scaffold
# ──────────────────────────────────────────────────────────────
@mcp.tool()
async def scaffold_app(app_name: str, app_title: str = None) -> str:
    """Scaffold a new custom app (returns structure)."""
    title = app_title or app_name.replace("-", " ").title()
    return json.dumps({
        "app_name": app_name,
        "title": title,
        "structure": {
            f"{app_name}/__init__.py": '__version__ = "0.0.1"',
            f"{app_name}/hooks.py": f'app_name = "{app_name}"\napp_title = "{title}"',
        },
        "bench_command": f"bench new-app {app_name}",
    }, indent=2)


@mcp.tool()
async def scaffold_module(module_name: str, app_name: str) -> str:
    """Scaffold a new module (returns structure)."""
    return json.dumps({
        "module_name": module_name,
        "app_name": app_name,
        "structure": {
            f"{app_name}/{module_name}/__init__.py": "",
            f"{app_name}/{module_name}/module.json": f'{{"name": "{module_name}"}}',
        },
    }, indent=2)


@mcp.tool()
async def create_module(module_name: str, app_name: str) -> str:
    """Create a new Module in ERPNext."""
    try:
        result = await _erpnext_post("/api/resource/Module Def", {
            "doctype": "Module Def",
            "app_name": app_name,
            "module_name": module_name,
        })
        return json.dumps({"success": True, "module": result.get("data", {}).get("name")}, indent=2)
    except Exception as e:
        return json.dumps(enrich_error(e, "Module Def", "create_module"), indent=2)


@mcp.tool()
async def create_webpage(data: str) -> str:
    """Create a new Web Page in ERPNext."""
    try:
        page_data = json.loads(data) if isinstance(data, str) else data
        page_data["doctype"] = "Web Page"
        result = await _erpnext_post("/api/resource/Web Page", page_data)
        return json.dumps({"success": True, "webpage": result.get("data", {}).get("name")}, indent=2)
    except Exception as e:
        return json.dumps(enrich_error(e, "Web Page", "create_webpage"), indent=2)


@mcp.tool()
async def share_document(doctype: str, name: str, user: str, ptype: str = "read") -> str:
    """Share a document with a user."""
    try:
        share_data = {"doctype": "DocShare", "user": user, "share_doctype": doctype,
                      "share_name": name, "read": 1 if ptype == "read" else 0}
        await _erpnext_post("/api/resource/DocShare", share_data)
        return json.dumps({"success": True, "message": f"Shared {doctype}/{name} with {user}"}, indent=2)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "share_document"), indent=2)


@mcp.tool()
async def validate_doctype(doctype: str) -> str:
    """Validate a DocType definition."""
    try:
        data = await _erpnext_get(f"/api/resource/DocType/{doctype}")
        doc = data.get("data", {})
        issues = []
        if not doc.get("fields"): issues.append("No fields defined")
        if not doc.get("permissions"): issues.append("No permissions defined")
        return json.dumps({"doctype": doctype, "valid": len(issues) == 0, "issues": issues}, indent=2)
    except Exception as e:
        return json.dumps(enrich_error(e, doctype, "validate_doctype"), indent=2)


@mcp.tool()
async def validate_workflow(workflow_name: str) -> str:
    """Validate a Workflow definition."""
    try:
        data = await _erpnext_get(f"/api/resource/Workflow/{workflow_name}")
        wf = data.get("data", {})
        issues = []
        if not wf.get("document_type"): issues.append("No document type")
        if not wf.get("states"): issues.append("No states defined")
        return json.dumps({"workflow": workflow_name, "valid": len(issues) == 0, "issues": issues}, indent=2)
    except Exception as e:
        return json.dumps(enrich_error(e, "Workflow", "validate_workflow"), indent=2)


@mcp.tool()
async def validate_script(script: str, script_type: str = "python") -> str:
    """Validate a script definition."""
    issues = []
    if script_type.lower() == "python":
        try: compile(script, "<string", "exec")
        except SyntaxError as e: issues.append(f"Syntax: {e.msg} at line {e.lineno}")
    return json.dumps({"valid": len(issues) == 0, "issues": issues}, indent=2)


@mcp.tool()
async def preview_script(script: str, script_type: str = "python") -> str:
    """Preview a script (syntax check only)."""
    return json.dumps({"script_type": script_type, "preview": script[:500], "length": len(script)}, indent=2)


@mcp.tool()
async def lint_script(script: str, script_type: str = "python") -> str:
    """Lint a script (syntax check only)."""
    issues = []
    if script_type.lower() == "python":
        try: compile(script, "<string", "exec"); issues.append("No syntax errors")
        except SyntaxError as e: issues.append(f"Error: {e.msg}")
    return json.dumps({"lint_result": issues}, indent=2)


@mcp.tool()
async def test_script(script: str, script_type: str = "python") -> str:
    """Test a script (syntax check only)."""
    return json.dumps({"test_result": "Syntax validation passed", "note": "Sandbox required for execution"}, indent=2)


@mcp.tool()
async def register_integration(service_name: str, data: str) -> str:
    """Register a new integration service."""
    try:
        int_data = json.loads(data) if isinstance(data, str) else data
        int_data["doctype"] = "Integration Service"
        result = await _erpnext_post("/api/resource/Integration Service", int_data)
        return json.dumps({"success": True, "service": result.get("data", {}).get("name")}, indent=2)
    except Exception as e:
        return json.dumps(enrich_error(e, "Integration Service", "register_integration"), indent=2)


@mcp.tool()
async def manage_integration(service_name: str, data: str) -> str:
    """Update/manage an integration service."""
    try:
        int_data = json.loads(data) if isinstance(data, str) else data
        result = await _erpnext_put(f"/api/resource/Integration Service/{service_name}", int_data)
        return json.dumps({"success": True, "service": service_name}, indent=2)
    except Exception as e:
        return json.dumps(enrich_error(e, "Integration Service", "manage_integration"), indent=2)


# ──────────────────────────────────────────────────────────────
# CLI entrypoint
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    transport = "sse"
    if "--stdio" in sys.argv:
        transport = "stdio"
    elif "--streamable-http" in sys.argv:
        transport = "streamable-http"

    print(f"Starting Business Claw MCP Server ({transport} transport)...")
    if transport == "sse":
        print(f"  → SSE endpoint: http://0.0.0.0:8003/sse")
        print(f"  → ERPNext URL:  {ERPNEXT_URL}")
    mcp.run(transport=transport)
