# Mini HTTP Server (Python)

A minimal HTTP server built from scratch using Python sockets and threading.
This project demonstrates low-level networking, HTTP parsing, routing, and REST API design without using frameworks.

The server includes a simple in-memory Todo API and a basic HTML homepage.

---

## Features

- HTTP/1.1 request parsing
- Socket-based server implementation
- Multi-threaded client handling
- Simple router
- JSON API responses
- In-memory Todo storage
- Health endpoint
- CRUD operations for todos

---

## Endpoints

### Home
GET /
Returns a simple HTML page.

### Health check
GET /health

Returns server status and uptime.

---

### Todos API

Get all todos:
GET /todos

Create todo:
POST /todos
Content-Type: application/json

Body:
{
  "text": "example todo"
}

Update todo:
PATCH /todos/<id>

Body:
{
  "text": "updated text",
  "done": true
}

Delete todo:
DELETE /todos/<id>

---

## How to run

Make sure you have Python 3.10+ installed.

Run:

```bash
python mini_server.py
