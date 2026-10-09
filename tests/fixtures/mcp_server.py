"""A local, credential-free MCP fixture with one read-only echo tool."""
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": request["params"]["protocolVersion"], "capabilities": {"tools": {}},
                  "serverInfo": {"name": "agent-sync-fixture", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "fixture_echo", "description": "Echo a test message without changing files.",
                  "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
                  "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": request["params"]["arguments"]["message"]}]}
    elif method == "ping":
        result = {}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": "Unknown method"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
