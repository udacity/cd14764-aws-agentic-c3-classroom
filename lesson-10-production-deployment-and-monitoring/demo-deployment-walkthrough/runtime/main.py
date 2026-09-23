"""Deployment smoke-test endpoint, not an implementation of the planned agents.

Only this directory is packaged. No credentials, student solutions or deployment
scripts are included. Model calls, retrieval and monitoring remain separate work.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/ping":
            self.reply(200, {"status": "Healthy"})
        else:
            self.reply(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/invocations":
            self.reply(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1048576:
                raise ValueError("Request must contain at most 1 MiB of JSON.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object.")
        except (ValueError, UnicodeError):
            self.reply(400, {"error": "Expected a JSON object of at most 1 MiB."})
            return
        self.reply(200, {"status": "ok", "message": "Lesson 10 deployment smoke test passed.",
                         "scope": "No model invocation, retrieval or business workflow was executed."})

    def log_message(self, fmt, *args):
        # Never log request bodies or credentials.
        print(f"HTTP {self.command} completed", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
