"""Microsoft Graph transport for NN's Teams chat.

Why this exists: NN currently talks to Teams by driving the desktop client with
UI automation. That is fragile (selectors move, sends silently fail, it needs an
unlocked console session) and it is the largest genuine breach in
docs/MICROSOFT-POLICY-AUDIT.md. With a licensed work account, Graph is the
sanctioned path and needs no desktop at all.

## ANSWERED 2026-07-27: Graph CANNOT drive chats with personal accounts.

Tested live against tenant aelbdltd as nn@aelbdltd.onmicrosoft.com:

  GET /me/chats                      -> 200, the federated chat IS listed
    id       19:uni01_lxalbgg5v753xsq2...   <-- note "uni01", the CONSUMER
                                                interop format, not @thread.v2
    members  [ Napco Nucleus,  {displayName:None, userId:'', tenantId:''} ]
                                                the personal account resolves
                                                to an empty member
  GET /me/chats/{id}                 -> 404 NotFound
  GET /me/chats/{id}/messages        -> 404 NotFound
  GET /chats/{id}/messages           -> 404 NotFound
  GET /me/chats/{id}/members         -> 404 NotFound

So the chat is enumerable but completely inaccessible. Every colleague is on a
personal Microsoft account, so **NN must stay on UI automation for chat** and
audit item B stands. Do not attempt this rewrite again while the team is on
personal accounts -- it cannot work.

WHAT WOULD CHANGE THIS: colleagues holding accounts IN the tenant. Internal
chats use @thread.v2, which Graph fully supports. The Business Basic trial
includes 25 seats and only 1 is used, so this is testable for free: give one
colleague a seat, have them message NN, and re-run `chats`. If the new chat
comes back as @thread.v2 and `messages` reads it, the whole rewrite unlocks.

STILL USEFUL WITHOUT ANY OF THAT: /me/presence/setPresence acts on NN's own
user, not on a chat, so proper presence control does NOT depend on this
limitation and can replace the mouse-jiggle keep-alive today.

Auth: device-code flow against the "Microsoft Graph Command Line Tools" public
client -- the same one Connect-MgGraph uses -- so this is testable without
registering an app. For production, register a dedicated app and swap CLIENT_ID.

Usage (cwd = repo root):
    py -3 -m teams.graph_chat login
    py -3 -m teams.graph_chat chats
    py -3 -m teams.graph_chat messages <chat-id>
    py -3 -m teams.graph_chat send <chat-id> "text"     # sends for real
    py -3 -m teams.graph_chat whoami
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_REPO = Path(__file__).parent.parent
TOKEN_FILE = _REPO / "data" / "graph_token.json"

# "Microsoft Graph Command Line Tools" - a Microsoft-published public client.
CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
TENANT = "aelbdltd.onmicrosoft.com"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT}"
GRAPH = "https://graph.microsoft.com/v1.0"

SCOPES = "offline_access User.Read Chat.ReadWrite ChatMessage.Send Presence.ReadWrite"


# --------------------------------------------------------------------------
# plumbing
# --------------------------------------------------------------------------
def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except Exception:
            return {"error": "http_%d" % e.code, "error_description": raw[:400]}


def _graph(method: str, path: str, token: str, payload=None) -> dict:
    url = path if path.startswith("http") else GRAPH + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(raw)
        except Exception:
            j = {"error": {"code": "http_%d" % e.code, "message": raw[:400]}}
        j["_status"] = e.code
        return j


def _save(tok: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tok["obtained_at"] = time.time()
    tmp = TOKEN_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tok, f, indent=2)
    import os
    os.replace(str(tmp), str(TOKEN_FILE))


def _load() -> dict:
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
def login() -> int:
    """Device-code sign-in. Prints a code; no browser needed on this machine."""
    r = _post_form(AUTHORITY + "/oauth2/v2.0/devicecode",
                   {"client_id": CLIENT_ID, "scope": SCOPES})
    if "user_code" not in r:
        print("device code request failed: %s" % r.get("error_description", r))
        return 1
    print(r.get("message", ""))
    print("\n  URL  : %s" % r.get("verification_uri"))
    print("  CODE : %s\n" % r.get("user_code"))
    interval = int(r.get("interval", 5))
    deadline = time.time() + int(r.get("expires_in", 900))
    while time.time() < deadline:
        time.sleep(interval)
        t = _post_form(AUTHORITY + "/oauth2/v2.0/token", {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": CLIENT_ID,
            "device_code": r["device_code"],
        })
        err = t.get("error")
        if err in ("authorization_pending", "slow_down"):
            if err == "slow_down":
                interval += 5
            continue
        if err:
            print("sign-in failed: %s" % t.get("error_description", err))
            return 1
        _save(t)
        print("signed in, token cached at %s" % TOKEN_FILE)
        return 0
    print("timed out waiting for sign-in")
    return 1


def token() -> str:
    """A valid access token, refreshed silently when needed."""
    tok = _load()
    if not tok:
        raise RuntimeError("not signed in - run: py -3 -m teams.graph_chat login")
    age = time.time() - tok.get("obtained_at", 0)
    if age < tok.get("expires_in", 3600) - 300:
        return tok["access_token"]
    rt = tok.get("refresh_token")
    if not rt:
        raise RuntimeError("token expired and no refresh_token - sign in again")
    new = _post_form(AUTHORITY + "/oauth2/v2.0/token", {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": rt,
        "scope": SCOPES,
    })
    if "access_token" not in new:
        raise RuntimeError("refresh failed: %s" % new.get("error_description", new))
    _save(new)
    return new["access_token"]


# --------------------------------------------------------------------------
# chat
# --------------------------------------------------------------------------
def whoami() -> dict:
    return _graph("GET", "/me", token())


def list_chats(top: int = 50) -> list:
    r = _graph("GET", "/me/chats?$expand=members&$top=%d" % top, token())
    return r.get("value", []) if isinstance(r, dict) else []


def messages(chat_id: str, top: int = 10) -> list:
    r = _graph("GET", "/me/chats/%s/messages?$top=%d" % (chat_id, top), token())
    return r.get("value", []) if isinstance(r, dict) else []


def send(chat_id: str, text: str) -> dict:
    return _graph("POST", "/me/chats/%s/messages" % chat_id, token(),
                  {"body": {"contentType": "text", "content": text}})


def _describe(c: dict) -> str:
    names = []
    for m in c.get("members", []) or []:
        n = m.get("displayName") or ""
        if n:
            names.append(n)
    kind = c.get("chatType", "?")
    return "%-10s %-46s %s" % (kind, ", ".join(names)[:46], c.get("id", "")[:60])


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1].lower()
    try:
        if cmd == "login":
            return login()
        if cmd == "whoami":
            me = whoami()
            print(json.dumps({k: me.get(k) for k in
                              ("displayName", "userPrincipalName", "id",
                               "mail", "error")}, indent=2))
            return 0
        if cmd == "chats":
            cs = list_chats()
            if not cs:
                print("no chats returned (or the call failed)")
                return 1
            print("%d chat(s):" % len(cs))
            for c in cs:
                print("  " + _describe(c))
            return 0
        if cmd == "messages":
            for m in reversed(messages(sys.argv[2])):
                who = (m.get("from") or {}).get("user") or {}
                body = ((m.get("body") or {}).get("content") or "").strip()
                print("  [%s] %s: %s" % (m.get("createdDateTime", "")[:19],
                                         who.get("displayName", "?"),
                                         body[:120]))
            return 0
        if cmd == "send":
            r = send(sys.argv[2], " ".join(sys.argv[3:]))
            print("sent" if r.get("id") else json.dumps(r, indent=2)[:600])
            return 0 if r.get("id") else 1
    except Exception as e:
        print("ERROR: %s" % e)
        return 1
    print("unknown command: %s" % cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
