# FrappeMCP

Model Context Protocol (MCP) server for ERPNext/Frappe - enables AI assistants to interact with ERPNext via 66+ tools.

## Features

- **66+ MCP Tools** for full ERPNext CRUD operations
- **FastMCP** implementation with async HTTP
- **SSE Server** support for real-time communication
- **Smart Mode** for auto-filling required fields
- **Exponential Backoff** retry with error enrichment
- **Skills System** for high-level business workflows
- **Agent-Ready** - integrate with OpenAI, Claude, OpenClaw, and other AI agents

## Installation

```bash
pip install frappe-mcp
```

Or install from source:
```bash
git clone https://github.com/Ravana-indus/frappemcp.git
cd frappemcp
pip install -r requirements.txt
```

## Configuration

Set these environment variables:
```bash
export FRAPPE_URL="https://your-erpnext-site.com"
export FRAPPE_API_KEY="your-api-key"
export FRAPPE_API_SECRET="your-api-secret"
```

## Usage with AI Agents

### 1. Claude Desktop

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "frappemcp": {
      "command": "python",
      "args": ["/path/to/frappemcp/server.py"]
    }
  }
}
```

### 2. OpenAI Agents SDK

```python
from openai import OpenAI
from mcp import ClientSession

# Connect to FrappeMCP
client = ClientSession("python", ["server.py"])

# Use tools
result = client.call_tool("get_document", {
    "doctype": "Customer",
    "name": "CUST-001"
})
```

### 3. OpenClaw

```python
from openclaw import Agent

agent = Agent(
    name="erpnext_assistant",
    mcp_servers=["python server.py"]
)

# Natural language requests
result = agent.execute("Create a sales order for ACME Corp with 10 units of Item-001")
```

### 4. Cursor / WindSurf

Add to your `.cursor/mcp.json` or `.windsurf/mcp.json`:

```json
{
  "mcpServers": {
    "frappe": {
      "command": "python",
      "args": ["/path/to/server.py"]
    }
  }
}
```

### 5. Custom MCP Client

```python
import httpx

# Using SSE mode
async with httpx.AsyncClient() as client:
    async with client.stream(
        "POST",
        "http://localhost:8000/sse",
        json={
            "jsonrpc": "2.0",
            "method": "tools/list"
        }
    ) as response:
        async for line in response.aiter_lines():
            print(line)
```

## Available Tools

### Document Operations
| Tool | Description |
|------|-------------|
| `get_document` | Fetch a document by name |
| `create_document` | Create a new document |
| `update_document` | Update existing document |
| `delete_document` | Delete a document |
| `submit_document` | Submit a document |
| `cancel_document` | Cancel a document |
| `amend_document` | Amend a cancelled document |

### Bulk Operations
| Tool | Description |
|------|-------------|
| `bulk_create_documents` | Create multiple documents |
| `bulk_update_documents` | Update multiple documents |
| `bulk_delete_documents` | Delete multiple documents |
| `smart_import_documents` | Import with validation |
| `bulk_smart_create_documents` | Bulk create with progress |

### Query & Search
| Tool | Description |
|------|-------------|
| `list_doctypes` | List available DocTypes |
| `list_documents` | List documents with filters |
| `search_documents` | Search documents by query |
| `get_count` | Count documents matching filters |

### Meta Operations
| Tool | Description |
|------|-------------|
| `get_doctype_meta` | Get DocType metadata |
| `get_doctype_fields` | Get field definitions |
| `get_doctype_schema` | Get field schema |
| `generate_doctype_docs` | Generate documentation |

### Workflow Operations
| Tool | Description |
|------|-------------|
| `create_workflow` | Create a workflow |
| `generate_workflow_docs` | Generate workflow docs |
| `validate_workflow` | Validate workflow |

### Scripting
| Tool | Description |
|------|-------------|
| `create_client_script` | Create client script |
| `create_server_script` | Create server script |
| `create_scheduled_job` | Create scheduled job |
| `validate_script` | Validate script |
| `lint_script` | Lint script |

### Customization
| Tool | Description |
|------|-------------|
| `create_child_table` | Create child table DocType |
| `add_child_table_to_doctype` | Add child table field |
| `create_report` | Create custom report |
| `create_dashboard` | Create dashboard |
| `create_chart` | Create chart |

### App Development
| Tool | Description |
|------|-------------|
| `scaffold_app` | Scaffold a new app |
| `scaffold_module` | Scaffold a module |
| `create_module` | Create a module |
| `create_webpage` | Create webpage |
| `create_hook` | Create hook |

### Integration
| Tool | Description |
|------|-------------|
| `create_webhook` | Create webhook |
| `register_integration` | Register integration |
| `manage_integration` | Manage integration |

## Starting the Server

### Standard Mode
```bash
python -m frappe_mcp.server
```

### SSE Mode (for agents)
```bash
python -m frappe_mcp.sse_server
```

### With custom port
```bash
FRAPPE_PORT=9000 python -m frappe_mcp.server
```

## Example Agent Conversations

### Example 1: Create Customer
```
User: "Create a new customer called ACME Corp"
Agent: Calls create_customer with {customer_name: "ACME Corp", customer_type: "Company"}
```

### Example 2: Sales Workflow
```
User: "Process an order for Customer ABC with 5 units of Product X"
Agent: 1. Creates Sales Order
       2. Creates Sales Invoice
       3. Records Payment
```

### Example 3: Query Data
```
User: "Show me all open sales orders"
Agent: Calls list_documents with filters {status: "Open"}
```

## License

MIT
