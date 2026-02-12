#!/usr/bin/env python3
import json
import socket
import threading
import time
import traceback
from urllib.parse import urlparse, parse_qs

HOST = "127.0.0.1"
PORT = 8080

# Simple in-memory store (resets on restart)
STATE = {
    "todos": [],   # list of {"id": int, "text": str, "done": bool, "created_at": float}
    "next_id": 1,
    "started_at": time.time(),
}

# ---------- HTTP helpers ----------

REASONS = {
    200: "OK",
    201: "Created",
    204: "No Content",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
}

def http_response(status: int, body: bytes = b"", headers: dict | None = None) -> bytes:
    headers = headers or {}
    reason = REASONS.get(status, "OK")
    base_headers = {
        "Server": "mini-server",
        "Connection": "close",
        "Content-Length": str(len(body)),
    }
    # Default content-type
    if "Content-Type" not in headers and body:
        base_headers["Content-Type"] = "text/plain; charset=utf-8"
    base_headers.update(headers)

    head = f"HTTP/1.1 {status} {reason}\r\n"
    for k, v in base_headers.items():
        head += f"{k}: {v}\r\n"
    head += "\r\n"
    return head.encode("utf-8") + body

def json_response(status: int, obj) -> bytes:
    body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    return http_response(status, body, {"Content-Type": "application/json; charset=utf-8"})

def parse_request(raw: bytes):
    """
    Very small HTTP/1.1 parser (good enough for learning + portfolio).
    Returns: method, path, query_dict, headers_dict, body_bytes
    """
    try:
        header_blob, body = raw.split(b"\r\n\r\n", 1)
    except ValueError:
        raise ValueError("Malformed HTTP request (missing header/body separator)")

    lines = header_blob.split(b"\r\n")
    if not lines:
        raise ValueError("Empty request")

    request_line = lines[0].decode("utf-8", errors="replace")
    parts = request_line.split()
    if len(parts) != 3:
        raise ValueError(f"Bad request line: {request_line}")

    method, target, version = parts
    if not version.startswith("HTTP/"):
        raise ValueError(f"Bad HTTP version: {version}")

    headers = {}
    for line in lines[1:]:
        s = line.decode("utf-8", errors="replace")
        if ":" not in s:
            continue
        k, v = s.split(":", 1)
        headers[k.strip().lower()] = v.strip()

    parsed = urlparse(target)
    path = parsed.path
    query = {k: v for k, v in parse_qs(parsed.query).items()}  # values are lists
    return method.upper(), path, query, headers, body

def read_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(min(remaining, 4096))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

def recv_http(sock: socket.socket) -> bytes:
    """
    Reads until headers arrive, then reads body according to Content-Length (if present).
    """
    data = b""
    # read until header separator
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
        if len(data) > 2_000_000:
            raise ValueError("Request too large")

    if b"\r\n\r\n" not in data:
        return data  # might be incomplete, but we'll let parser fail

    header_blob, rest = data.split(b"\r\n\r\n", 1)
    headers_lines = header_blob.split(b"\r\n")[1:]
    headers = {}
    for line in headers_lines:
        s = line.decode("utf-8", errors="replace")
        if ":" in s:
            k, v = s.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    cl = headers.get("content-length")
    if cl is None:
        return data  # no body expected

    try:
        length = int(cl)
    except ValueError:
        raise ValueError("Invalid Content-Length")

    missing = length - len(rest)
    if missing > 0:
        rest += read_exact(sock, missing)

    return header_blob + b"\r\n\r\n" + rest

# ---------- Router ----------

def route(method: str, path: str):
    """
    returns handler function or None
    supports:
      GET  /                  -> HTML home
      GET  /health            -> JSON
      GET  /todos             -> JSON list
      POST /todos             -> JSON create {"text": "..."}
      PATCH /todos/<id>       -> JSON update {"text"?, "done"?}
      DELETE /todos/<id>      -> 204
    """
    if path == "/":
        if method != "GET": return "METHOD_NOT_ALLOWED", None
        return "OK", handle_home

    if path == "/health":
        if method != "GET": return "METHOD_NOT_ALLOWED", None
        return "OK", handle_health

    if path == "/todos":
        if method == "GET": return "OK", handle_list_todos
        if method == "POST": return "OK", handle_create_todo
        return "METHOD_NOT_ALLOWED", None

    if path.startswith("/todos/"):
        # dynamic segment
        try:
            todo_id = int(path.split("/", 2)[2])
        except Exception:
            return "NOT_FOUND", None

        if method == "PATCH":
            return "OK", lambda req: handle_patch_todo(req, todo_id)
        if method == "DELETE":
            return "OK", lambda req: handle_delete_todo(req, todo_id)
        return "METHOD_NOT_ALLOWED", None

    return "NOT_FOUND", None

# ---------- Handlers ----------

def handle_home(req):
    body = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>Mini Server</title></head>
<body style="font-family: system-ui; max-width: 720px; margin: 40px auto;">
  <h1>Mini HTTP Server ✅</h1>
  <p>This is a tiny HTTP server built with <code>socket</code> + a small router.</p>

  <h2>Endpoints</h2>
  <ul>
    <li><code>GET /health</code></li>
    <li><code>GET /todos</code></li>
    <li><code>POST /todos</code> JSON: <code>{{"text":"..."}}</code></li>
    <li><code>PATCH /todos/&lt;id&gt;</code> JSON: <code>{{"text"?: "...", "done"?: true}}</code></li>
    <li><code>DELETE /todos/&lt;id&gt;</code></li>
  </ul>

  <h2>Try quickly</h2>
  <pre>
curl http://{HOST}:{PORT}/health
curl http://{HOST}:{PORT}/todos
curl -X POST http://{HOST}:{PORT}/todos -H "Content-Type: application/json" -d '{{"text":"ship it"}}'
curl -X PATCH http://{HOST}:{PORT}/todos/1 -H "Content-Type: application/json" -d '{{"done":true}}'
curl -X DELETE http://{HOST}:{PORT}/todos/1
  </pre>
</body>
</html>"""
    return http_response(200, body.encode("utf-8"), {"Content-Type": "text/html; charset=utf-8"})

def handle_health(req):
    uptime = time.time() - STATE["started_at"]
    return json_response(200, {"status": "ok", "uptime_seconds": round(uptime, 2), "todos": len(STATE["todos"])})

def handle_list_todos(req):
    # Optional query: ?done=true/false
    query = req["query"]
    todos = STATE["todos"]

    if "done" in query:
        val = query["done"][0].lower()
        if val in ("true", "1", "yes"):
            todos = [t for t in todos if t["done"]]
        elif val in ("false", "0", "no"):
            todos = [t for t in todos if not t["done"]]

    return json_response(200, {"todos": todos})

def handle_create_todo(req):
    if req["headers"].get("content-type", "").startswith("application/json") is False:
        return json_response(422, {"error": "Expected Content-Type: application/json"})

    try:
        payload = json.loads(req["body"] or b"{}")
    except json.JSONDecodeError:
        return json_response(400, {"error": "Invalid JSON"})

    text = (payload.get("text") or "").strip()
    if not text:
        return json_response(422, {"error": "Field 'text' is required"})

    todo = {"id": STATE["next_id"], "text": text, "done": False, "created_at": time.time()}
    STATE["next_id"] += 1
    STATE["todos"].append(todo)
    return json_response(201, todo)

def handle_patch_todo(req, todo_id: int):
    if req["headers"].get("content-type", "").startswith("application/json") is False:
        return json_response(422, {"error": "Expected Content-Type: application/json"})

    todo = next((t for t in STATE["todos"] if t["id"] == todo_id), None)
    if not todo:
        return json_response(404, {"error": "Todo not found"})

    try:
        payload = json.loads(req["body"] or b"{}")
    except json.JSONDecodeError:
        return json_response(400, {"error": "Invalid JSON"})

    if "text" in payload:
        new_text = (payload.get("text") or "").strip()
        if not new_text:
            return json_response(422, {"error": "Field 'text' cannot be empty"})
        todo["text"] = new_text

    if "done" in payload:
        if not isinstance(payload["done"], bool):
            return json_response(422, {"error": "Field 'done' must be boolean"})
        todo["done"] = payload["done"]

    return json_response(200, todo)

def handle_delete_todo(req, todo_id: int):
    idx = next((i for i, t in enumerate(STATE["todos"]) if t["id"] == todo_id), None)
    if idx is None:
        return json_response(404, {"error": "Todo not found"})
    STATE["todos"].pop(idx)
    return http_response(204, b"")

# ---------- Server loop ----------

def handle_client(conn: socket.socket, addr):
    try:
        raw = recv_http(conn)
        method, path, query, headers, body = parse_request(raw)

        req = {"method": method, "path": path, "query": query, "headers": headers, "body": body}
        status, handler = route(method, path)

        if status == "NOT_FOUND":
            conn.sendall(json_response(404, {"error": "Not found"}))
            return
        if status == "METHOD_NOT_ALLOWED":
            conn.sendall(json_response(405, {"error": "Method not allowed"}))
            return

        resp = handler(req)
        conn.sendall(resp)

    except Exception as e:
        # Keep error simple for client; print traceback for dev.
        traceback.print_exc()
        conn.sendall(json_response(500, {"error": "Internal server error", "detail": str(e)}))
    finally:
        try:
            conn.close()
        except Exception:
            pass

def serve_forever():
    print(f"Serving on http://{HOST}:{PORT}  (Ctrl+C to stop)")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen(50)

        while True:
            conn, addr = s.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t
