#!/usr/bin/env python3
"""Start, stop and check the machine owner's own dev box through the infra launcher's JSON API.

    devbox.py status
    devbox.py start [--wait]          --wait: until running and answering SSH
    devbox.py stop [--wait] [--force] refuses while tmux sessions run on the box, unless --force

It takes no instance argument, by design: the box is fixed in the untracked ~/.claude/local/devbox.env
(DEVBOX_ENV overrides the path), so an agent using it cannot start or stop anybody else's workstation. Before
acting it checks that the launcher names that instance as DEVBOX_NAME with key pair DEVBOX_KEY, and refuses if not.

    LAUNCHER_URL=https://<launcher address>        reachable over the VPN only
    LAUNCHER_CERT_SHA256=<hex>                     the launcher's self-signed certificate, pinned (optional)
    DEVBOX_ID=i-...
    DEVBOX_NAME=pgd-dev-<region>-<name>
    DEVBOX_KEY=<key pair>
    DEVBOX_SSH=<ssh alias>                         for the tmux check and --wait (optional)

Exit status: 0 done, 1 launcher or network error, 2 refused (jobs running, wrong box, mid-transition).
Standard library only.
"""

import argparse
import hashlib
import http.client
import json
import os
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit

DEFAULT_ENV = os.path.join(os.path.expanduser("~"), ".claude", "local", "devbox.env")
REQUIRED = ("LAUNCHER_URL", "DEVBOX_ID", "DEVBOX_NAME", "DEVBOX_KEY")
PIN_HELP = ("echo | openssl s_client -connect %s 2>/dev/null | openssl x509 -outform DER | shasum -a 256")


class Refused(Exception):
    """The action would be unsafe or touch the wrong box; exit 2."""


class LauncherError(Exception):
    """The launcher could not be reached or answered with an error; exit 1."""


def load_env(path):
    """KEY=VALUE lines, # comments and blanks ignored."""
    env = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        raise LauncherError("%s lacks %s" % (path, ", ".join(missing)))
    return env


def https_api(env, timeout=20):
    """A function (method, path) -> (status, parsed JSON or None) against LAUNCHER_URL. The certificate is
    self-signed, so it is checked against LAUNCHER_CERT_SHA256 when set rather than against a CA."""
    url = urlsplit(env["LAUNCHER_URL"])
    context = ssl.create_default_context()
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE

    def call(method, path):
        conn = http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=timeout, context=context)
        try:
            conn.connect()
            pin = env.get("LAUNCHER_CERT_SHA256", "").lower()
            seen = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest()
            if pin and seen != pin:
                raise Refused("launcher certificate is %s, not the pinned %s. If the launcher was replaced, re-pin "
                              "LAUNCHER_CERT_SHA256 from: %s" % (seen, pin, PIN_HELP % url.netloc))
            conn.request(method, path, body=b"" if method == "POST" else None)
            resp = conn.getresponse()
            body = resp.read().decode()
            kind = resp.getheader("Content-Type", "")
            return resp.status, json.loads(body) if kind.startswith("application/json") else None
        except (OSError, http.client.HTTPException) as err:
            raise LauncherError("launcher %s unreachable (%s); is the VPN up?" % (env["LAUNCHER_URL"], err)) from err
        finally:
            conn.close()

    return call


def run_ssh(alias, command, timeout=15):
    """(exit status, stdout) of a non-interactive ssh command; 255 when ssh itself fails."""
    try:
        done = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", alias, command],
                              capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 255, ""
    return done.returncode, done.stdout


class DevBox:
    def __init__(self, env, api, ssh=run_ssh, sleep=time.sleep, clock=time.monotonic, out=print):
        self.env, self.api, self.ssh, self.sleep, self.clock, self.out = env, api, ssh, sleep, clock, out
        self.path = "/api/workstations/" + env["DEVBOX_ID"]

    def describe(self):
        """The launcher's row for DEVBOX_ID, after checking it is the box devbox.env says it is."""
        status, body = self.api("GET", self.path)
        if status == 404 and body is None:
            raise LauncherError("the launcher at %s has no JSON API (deployed?)" % self.env["LAUNCHER_URL"])
        if status != 200:
            raise LauncherError("launcher answered %d: %s" % (status, (body or {}).get("error", "")))
        if (body["name"], body["key"]) != (self.env["DEVBOX_NAME"], self.env["DEVBOX_KEY"]):
            raise Refused("%s is %s (key %s), not %s (key %s); fix devbox.env, refusing to touch it" % (
                body["id"], body["name"], body["key"], self.env["DEVBOX_NAME"], self.env["DEVBOX_KEY"]))
        return body

    def line(self, row):
        return "%s %s %s ip=%s since=%s" % (row["name"], row["id"], row["state"], row["ip"] or "-", row["since"])

    def status(self):
        self.out(self.line(self.describe()))

    def running_jobs(self):
        """The box's tmux sessions, or raise if they cannot be checked."""
        alias = self.env.get("DEVBOX_SSH")
        if not alias:
            raise Refused("DEVBOX_SSH is unset, so running jobs cannot be checked; stop with --force to skip")
        code, out = self.ssh(alias, "tmux ls 2>/dev/null || true")
        if code != 0:
            raise Refused("cannot reach %s to check for running jobs; stop with --force to skip" % alias)
        return [line for line in out.splitlines() if line.strip()]

    def act(self, action, force=False):
        row = self.describe()
        if action == "stop" and row["state"] == "running" and not force:
            jobs = self.running_jobs()
            if jobs:
                raise Refused("tmux sessions running on %s, not stopping (--force to stop anyway):\n  %s"
                              % (row["name"], "\n  ".join(jobs)))
        status, body = self.api("POST", self.path + "/" + action)
        if status == 409:
            raise Refused(body["error"])
        if status not in (200, 202):
            raise LauncherError("launcher answered %d: %s" % (status, (body or {}).get("error", "")))
        self.out("%s %s: %s%s" % (action, row["name"], body["state"], "" if body["changed"] else " (no change)"))

    def wait_for(self, state, timeout):
        deadline = self.clock() + timeout
        while True:
            row = self.describe()
            if row["state"] == state:
                return row
            if self.clock() > deadline:
                raise LauncherError("%s still %s after %ds" % (row["name"], row["state"], timeout))
            self.sleep(5)

    def wait_for_ssh(self, timeout):
        alias, deadline = self.env.get("DEVBOX_SSH"), self.clock() + timeout
        if not alias:
            return
        while self.ssh(alias, "true")[0] != 0:
            if self.clock() > deadline:
                raise LauncherError("%s running but %s not answering SSH after %ds" % (
                    self.env["DEVBOX_NAME"], alias, timeout))
            self.sleep(5)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start, stop or check this machine's own dev box.")
    parser.add_argument("command", choices=("status", "start", "stop"))
    parser.add_argument("--wait", action="store_true", help="return once the box is up (or stopped)")
    parser.add_argument("--force", action="store_true", help="stop even if tmux sessions are running")
    args = parser.parse_args(argv)
    try:
        env = load_env(os.environ.get("DEVBOX_ENV", DEFAULT_ENV))
        box = DevBox(env, https_api(env))
        if args.command == "status":
            box.status()
            return 0
        box.act(args.command, force=args.force)
        if args.wait and args.command == "start":
            box.out(box.line(box.wait_for("running", 300)))
            box.wait_for_ssh(180)
            box.out("ssh %s answers" % env.get("DEVBOX_SSH", "(DEVBOX_SSH unset, not checked)"))
        elif args.wait:
            box.out(box.line(box.wait_for("stopped", 600)))
        return 0
    except Refused as err:
        print("devbox: refused: %s" % err, file=sys.stderr)
        return 2
    except (LauncherError, OSError) as err:
        print("devbox: %s" % err, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
