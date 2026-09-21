"""Only the private snapshot MCP tools are available to the question responder."""
import json
import sys

ALLOWED = {"mcp__project_reader__" + name for name in
           ("project_overview", "list_files", "read_file", "search_code", "read_changes", "run_python")}


def decision(event):
    if event.get("tool_name") in ALLOWED:
        return {}
    return {"decision": "block", "reason": "Telegram questions may use only the project_reader snapshot tools. Development tools and general shell access are unavailable."}


if __name__ == "__main__":
    try:
        event = json.loads(sys.stdin.read(100000))
        result = decision(event) if isinstance(event, dict) else decision({})
    except (ValueError, OSError):
        result = decision({})
    print(json.dumps(result))
