"""Faux serveur compatible OpenAI pour les tests de bout en bout : réponse en streaming avec sources."""
import os
import json, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ANSWER = ("Sept participants arrivent depuis le **simulateur de tarif** en ligne [[parcours.txt | L4]], "
          "les cinq autres par un conseiller en agence [[parcours.txt | L4]].\n\n"
          "- Le dépôt des justificatifs fait abandonner deux participants [[parcours.txt | L16]]\n"
          "- Un repère qui n'existe pas [[parcours.txt | L999]]")
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
        self.wfile.write(json.dumps({"data":[{"id":"fake-model"}]}).encode())
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if not body.get("stream"):
            out = {"choices":[{"message":{"content":'{"keywords":["origine","provenance"]}'},"finish_reason":"stop"}]}
            self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
            self.wfile.write(json.dumps(out).encode()); return
        self.send_response(200); self.send_header("Content-Type","text/event-stream"); self.end_headers()
        for i in range(0, len(ANSWER), 12):
            ev = {"choices":[{"delta":{"content":ANSWER[i:i+12]},"finish_reason":None}]}
            self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode()); self.wfile.flush(); time.sleep(0.03)
        self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("FAKE_LLM_PORT", "9911"))), H).serve_forever()
