# FrappeMCP

Model Context Protocol (MCP) server for ERPNext/Frappe - enables AI assistants to interact with ERPNext via 66+ tools.

## Features

- **66+ MCP Tools** for full ERPNext CRUD operations
- **FastMCP** implementation with async HTTP
- **SSE Server** support for real-time communication
- **Smart Mode** for auto-filling required fields
- **Exponential Backoff** retry with error enrichment
- **Skills System** for high-level business workflows

## Installation

```bash
pip install frappe-mcp
```

## Usage

### Start MCP Server

```bash
python -m frappe_mcp.server
```

### SSE Mode

```bash
python -m frappe_mcp.sse_server
```

## Available Tools

### Document Operations
- `get_document` - Fetch a document
- `create_document` - Create a new document
- `update_document` - Update existing document
- `delete_document` - Delete a document
- `submit_document` - Submit a document
- `cancel_document` - Cancel a document

### Bulk Operations
- `bulk_create_documents` - Create multiple documents
- `bulk_update_documents` - Update multiple documents
- `bulk_delete_documents` - Delete multiple documents

### Meta Operations
- `list_doctypes` - List available DocTypes
- `get_doctype_meta` - Get DocType metadata
- `get_doctype_fields` - Get field definitions
- `list_documents` - List documents with filters
- `search_documents` - Search documents

### System Operations
- `get_current_user` - Get authenticated user
- `system_ping` - Ping the server

## Configuration

Set these environment variables:
- `FRAPPE_URL` - ERPNext site URL
- `FRAPPE_API_KEY` - API Key
- `FRAPPE_API_SECRET` - API Secret

## License

MIT
