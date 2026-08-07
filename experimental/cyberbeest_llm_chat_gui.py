#!/usr/bin/env python3
"""Cyberbeest LLM Chat.

Experimental chat UI for the local llama.cpp server (Qwen2.5-1.5B, running
on :8080 with Vulkan acceleration). The idea being tried out: "if this
laptop could talk about itself" -- a small local model given a short
knowledge pre-prompt about what a Cyberbeest is, so it can answer basic
questions about the machine without any internet access.

No agent harness, no tool use, no RAG -- just a system prompt and a plain
chat loop over the OpenAI-compatible /v1/chat/completions endpoint. Chats
persist as JSON files under ~/.config/cyberbeest/llm_chats/ so past
conversations survive a restart.

Written as a self-contained Gtk.Box page (LLMChatPage) so it can later be
dropped into a unified Cyberbeest Settings dialog as a tab, matching every
other Cyberbeest config dialog (see PowerSettingsPage in
cyberbeest_power_settings_gui.py).
"""

import json
import os
import subprocess
import threading
import time
import urllib.request
import urllib.error

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Gdk

DEFAULT_SERVER_HOST = "http://localhost:8080"

LLAMA_DIR = os.path.expanduser("~/claude/local-llm-test/llama.cpp")
SERVER_LOG = "/tmp/cyberbeest-llama-server.log"

# Two separate binaries, not one binary with a flag -- build-vulkan/bin/llama-server links
# libggml-vulkan.so.0 and still touches the GPU even with -ngl 0 (confirmed via ldd + a device-lost
# crash while "CPU" was selected). build/bin/llama-server has no Vulkan linked at all (verified via
# ldd) and is the only genuinely GPU-free path. See cyberbeest_local_llm_perf memory for the
# measurements that found this (and for how slow true CPU prefill turned out to be).
SERVER_BACKEND_BIN = {
    "vulkan": os.path.join(LLAMA_DIR, "build-vulkan/bin/llama-server"),
    "cpu": os.path.join(LLAMA_DIR, "build/bin/llama-server"),
}
SERVER_BACKEND_ARGS = {
    "vulkan": ["-m", "qwen", "-t", "1", "-c", "4096"],
    "cpu": ["-m", "qwen", "-t", "2", "-c", "4096"],
}
SERVER_PORT = 8080
BATCH_SIZES = [512, 256, 128, 64, 32]  # 512 is llama.cpp's own default -ub; Vulkan backend only

HEALTH_POLL_MS = 3000
LOG_POLL_MS = 2000
LOG_TAIL_BYTES = 30000
N_SLOTS = 4  # matches n_slots in run-server-vulkan's llama-server invocation
N_CTX = 4096  # matches -c in run-server-vulkan; kv_unified means this is shared, not divided by slot

AUTO_RESTART_MAX_ATTEMPTS = 5
AUTO_RESTART_BACKOFF_SEC = [2, 5, 10, 20, 30]  # per attempt, capped at last value

STATE_DIR = os.path.expanduser("~/.config/cyberbeest")
CHATS_DIR = os.path.join(STATE_DIR, "llm_chats")
HOST_FILE = os.path.join(STATE_DIR, "llm_chat_host.txt")

KNOWLEDGE_PREPROMPT = """You are the onboard assistant of a Cyberbeest laptop, speaking in the \
first person as the machine itself. Keep answers short (2-4 sentences unless asked for more).

Facts about what you are:
- Cyberbeest is a privacy- and security-focused Linux laptop, running a customized Debian \
("Beest OS" internally), sold in small quantities directly (not through big retailers).
- The pitch is curation and security, not app variety: a minimal set of vetted apps rather than \
letting the user pile on redundant software.
- Preinstalled secure messengers include Signal, Element (Matrix), Telegram, and Viber, plus the \
Tor Browser. VPN support is a client-side WireGuard toggle the user turns on themselves -- there \
is no VPN service running by default.
- The disk is LUKS-encrypted. There are two separate passwords: a master password that unlocks \
the disk at boot, and a shorter everyday login password for the "cyberbeest" account.
- The hardware is a modest whitebox laptop (Intel Celeron N3350 class), chosen to keep the price \
low and the machine replaceable/repairable rather than to be fast.
- You (the chat model) are a small language model (Qwen2.5, about 1.5 billion parameters) \
running via llama.cpp. {location_sentence}
- Because you're a small model, be upfront about uncertainty rather than inventing specifics you \
don't actually know (exact prices, exact specs, order status, etc.) -- suggest the user check the \
Cyberbeest website or Shopify store for anything like that.
"""

KNOWLEDGE_PREPROMPT_LOCAL = KNOWLEDGE_PREPROMPT.format(
    location_sentence="You're running entirely offline on this laptop's own GPU -- nothing "
    "you're asked or told leaves the machine."
)
KNOWLEDGE_PREPROMPT_REMOTE = KNOWLEDGE_PREPROMPT.format(
    location_sentence="Right now you're running on a separate machine on the local network, "
    "not on this laptop itself -- say so if asked where you're running."
)

DEFAULT_MAX_TOKENS = 512


def ensure_dirs():
    os.makedirs(CHATS_DIR, exist_ok=True)


def list_chats():
    ensure_dirs()
    chats = []
    for name in os.listdir(CHATS_DIR):
        if name.endswith(".json"):
            path = os.path.join(CHATS_DIR, name)
            try:
                with open(path) as f:
                    data = json.load(f)
                chats.append((data.get("created", 0), name[:-5], data.get("title") or "New chat"))
            except (json.JSONDecodeError, OSError):
                continue
    chats.sort(reverse=True)
    return [(cid, title) for _, cid, title in chats]


def chat_path(chat_id):
    return os.path.join(CHATS_DIR, f"{chat_id}.json")


def load_chat(chat_id):
    with open(chat_path(chat_id)) as f:
        return json.load(f)


def save_chat(chat_id, data):
    ensure_dirs()
    tmp = chat_path(chat_id) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, chat_path(chat_id))


def new_chat_id():
    return time.strftime("%Y%m%d-%H%M%S")


def normalize_host(text):
    """Turn free-typed host text into a base URL, e.g. "192.168.1.50" -> "http://192.168.1.50:8080"."""
    text = text.strip().rstrip("/")
    if not text:
        return DEFAULT_SERVER_HOST
    if "://" not in text:
        text = "http://" + text
    if ":" not in text.split("://", 1)[1]:
        text += ":8080"
    return text


def local_lan_ip():
    """Best-effort outbound-interface IP for display in the "Discoverable" hint.

    Opens a UDP socket "connected" to a public address -- no packet is actually sent, this
    just asks the kernel which local interface/IP would be used to route there.
    """
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def host_is_local(base_url):
    hostname = base_url.split("://", 1)[-1].split(":", 1)[0]
    return hostname in ("localhost", "127.0.0.1", "::1")


def load_saved_host():
    try:
        with open(HOST_FILE) as f:
            return f.read().strip() or DEFAULT_SERVER_HOST
    except OSError:
        return DEFAULT_SERVER_HOST


def save_host(base_url):
    ensure_dirs()
    try:
        with open(HOST_FILE, "w") as f:
            f.write(base_url)
    except OSError:
        pass


class LLMChatPage(Gtk.Box):

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.server_base = load_saved_host()
        self.chat_id = None
        self.messages = []  # [{"role": "user"/"assistant", "content": str}]
        self.streaming = False
        self._stream_iter = None  # (Gtk.TextIter position tracked via mark)
        self.last_log_text = None
        self.last_log_stat = None  # (size, mtime) of SERVER_LOG at last read
        self._suppress_chat_selected = False

        self.server_proc = None
        self.server_up = False
        self.server_seen_up = False  # has health-checked OK at least once since last (re)start
        self.crash_count = 0
        self.auto_restart_attempts = 0
        self.auto_restart_pending = False
        self.stopping_server = False  # user-initiated stop -- suppress crash auto-restart

        self._build_ui()
        self._refresh_chat_list()
        self._start_new_chat()
        self._apply_remote_gating()

        self._poll_server_status()
        GLib.timeout_add(HEALTH_POLL_MS, self._poll_server_status)
        GLib.timeout_add(LOG_POLL_MS, self._poll_log_tab)

    # -- Server host -------------------------------------------------------

    def _url(self, path):
        return f"{self.server_base}{path}"

    def _is_remote(self):
        return not host_is_local(self.server_base)

    def _on_host_changed(self):
        new_base = normalize_host(self.host_entry.get_text())
        self.host_entry.set_text(new_base)
        if new_base == self.server_base:
            return
        self.server_base = new_base
        save_host(new_base)
        self.server_seen_up = False
        self.crash_count = 0
        self.auto_restart_attempts = 0
        self._apply_remote_gating()
        self._update_context_label()
        self._poll_server_status()

    def _apply_remote_gating(self):
        # Start/stop/backend/batch/log are only meaningful for a server this GUI itself
        # launches as a subprocess -- for a remote host, the user runs llama-server there.
        if self._is_remote():
            self.backend_combo.set_sensitive(False)
            self.batch_combo.set_sensitive(False)
            self.discoverable_check.set_sensitive(False)
            self.server_btn.set_sensitive(False)
            self.stop_server_btn.set_sensitive(False)
            self._set_log_text("(server log tab only applies to a locally-launched server)")
        else:
            self.server_btn.set_sensitive(not self.server_up)
            self.stop_server_btn.set_sensitive(self.server_up)
            self.backend_combo.set_sensitive(not self.server_up)
            self.batch_combo.set_sensitive(not self.server_up and self.backend_combo.get_active_id() == "vulkan")
            self.discoverable_check.set_sensitive(not self.server_up)

    # -- UI construction -------------------------------------------------

    def _build_ui(self):
        # Sidebar: chat list + new chat button
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        sidebar.set_size_request(200, -1)
        sidebar.set_border_width(8)

        new_btn = Gtk.Button(label="+ New chat")
        new_btn.connect("clicked", lambda b: self._start_new_chat())
        sidebar.pack_start(new_btn, False, False, 0)

        self.chat_list_store = Gtk.ListStore(str, str)  # chat_id, title
        self.chat_list_view = Gtk.TreeView(model=self.chat_list_store)
        self.chat_list_view.set_headers_visible(False)
        renderer = Gtk.CellRendererText()
        renderer.set_property("ellipsize", 3)  # PANGO_ELLIPSIZE_END
        col = Gtk.TreeViewColumn("", renderer, text=1)
        col.set_expand(True)
        self.chat_list_view.append_column(col)
        self.chat_list_view.get_selection().connect("changed", self._on_chat_selected)

        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        list_scroll.add(self.chat_list_view)
        sidebar.pack_start(list_scroll, True, True, 0)

        del_btn = Gtk.Button(label="Delete chat")
        del_btn.connect("clicked", self._on_delete_chat)
        sidebar.pack_start(del_btn, False, False, 0)

        self.pack_start(sidebar, False, False, 0)
        self.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)

        # Main area: transcript + status + entry
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        main.set_border_width(8)

        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label()
        title.set_markup("<b>Cyberbeest LLM Chat</b>  (Qwen2.5-1.5B via llama.cpp)")
        title.set_halign(Gtk.Align.START)
        title_row.pack_start(title, True, True, 0)

        self.server_status_label = Gtk.Label(label="checking server...")
        title_row.pack_start(self.server_status_label, False, False, 0)

        self.status_label = Gtk.Label(label="")
        self.status_label.set_halign(Gtk.Align.END)
        title_row.pack_start(self.status_label, False, False, 0)
        header.pack_start(title_row, False, False, 0)

        controls_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        host_label = Gtk.Label(label="Server:")
        controls_row.pack_start(host_label, False, False, 0)
        self.host_entry = Gtk.Entry()
        self.host_entry.set_text(self.server_base)
        self.host_entry.set_width_chars(22)
        self.host_entry.set_tooltip_text(
            "llama.cpp server host, e.g. \"localhost:8080\" or \"192.168.1.50:8080\". "
            "Start/stop/backend controls only apply to a local server -- for a remote host, "
            "start llama-server there yourself."
        )
        self.host_entry.connect("activate", lambda e: self._on_host_changed())
        self.host_entry.connect("focus-out-event", lambda e, ev: self._on_host_changed())
        controls_row.pack_start(self.host_entry, False, False, 0)

        self.backend_combo = Gtk.ComboBoxText()
        self.backend_combo.append("vulkan", "Vulkan (GPU)")
        self.backend_combo.append("cpu", "CPU only")
        self.backend_combo.set_active_id("vulkan")
        self.backend_combo.connect("changed", self._on_backend_changed)
        controls_row.pack_start(self.backend_combo, False, False, 0)

        self.batch_combo = Gtk.ComboBoxText()
        for n in BATCH_SIZES:
            self.batch_combo.append(str(n), f"batch {n}")
        self.batch_combo.set_active_id("512")
        self.batch_combo.set_tooltip_text(
            "GPU dispatch size (-ub). Smaller batches finish faster per submission, which can "
            "avoid tripping the kernel's GPU hangcheck timeout on Vulkan with larger contexts."
        )
        controls_row.pack_start(self.batch_combo, False, False, 0)

        self.server_btn = Gtk.Button(label="Start server")
        self.server_btn.connect("clicked", lambda b: self._on_start_server())
        self.server_btn.set_sensitive(False)
        controls_row.pack_start(self.server_btn, False, False, 0)

        self.stop_server_btn = Gtk.Button(label="Stop server")
        self.stop_server_btn.connect("clicked", lambda b: self._on_stop_server())
        self.stop_server_btn.set_sensitive(False)
        controls_row.pack_start(self.stop_server_btn, False, False, 0)

        self.knowledge_check = Gtk.CheckButton(label="Laptop context")
        self.knowledge_check.set_active(True)
        self.knowledge_check.set_tooltip_text(
            "When on, prepends the Cyberbeest knowledge system prompt to every request. "
            "Turn off to talk to the raw model with an empty context (faster, no persona)."
        )
        self.knowledge_check.connect("toggled", lambda b: self._update_context_label())
        controls_row.pack_start(self.knowledge_check, False, False, 0)

        self.context_label = Gtk.Label(label="")
        controls_row.pack_start(self.context_label, False, False, 0)

        header.pack_start(controls_row, False, False, 0)

        discover_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.discoverable_check = Gtk.CheckButton(label="Discoverable (LAN)")
        self.discoverable_check.set_active(False)
        self.discoverable_check.set_tooltip_text(
            "Bind the locally-started server to 0.0.0.0 instead of localhost, so another "
            "machine on the network can point its own chat UI at this one. Off by default -- "
            "leaves the server local-only. Takes effect on the next server start."
        )
        self.discoverable_check.connect("toggled", lambda b: self._update_lan_hint())
        discover_row.pack_start(self.discoverable_check, False, False, 0)

        self.lan_hint_label = Gtk.Label(label="")
        self.lan_hint_label.set_selectable(True)
        discover_row.pack_start(self.lan_hint_label, False, False, 0)

        header.pack_start(discover_row, False, False, 0)
        main.pack_start(header, False, False, 0)

        self.transcript_buffer = Gtk.TextBuffer()
        self.transcript_buffer.create_tag("user", weight=700, foreground="#3b6ea5")
        self.transcript_buffer.create_tag("assistant", weight=700, foreground="#2e8b57")
        self.transcript_buffer.create_tag("body", left_margin=12)
        self.transcript_buffer.create_tag("error", foreground="#c0392b")

        self.transcript_view = Gtk.TextView(buffer=self.transcript_buffer)
        self.transcript_view.set_editable(False)
        self.transcript_view.set_cursor_visible(False)
        self.transcript_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.transcript_view)
        scroll.set_vexpand(True)
        self.transcript_scroll = scroll

        self.notebook = Gtk.Notebook()
        self.notebook.append_page(scroll, Gtk.Label(label="Chat"))

        self.context_buffer = Gtk.TextBuffer()
        context_view = Gtk.TextView(buffer=self.context_buffer)
        context_view.set_editable(False)
        context_view.set_cursor_visible(False)
        context_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        context_view.set_monospace(True)
        context_scroll = Gtk.ScrolledWindow()
        context_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        context_scroll.add(context_view)
        self.notebook.append_page(context_scroll, Gtk.Label(label="Context"))

        self.log_buffer = Gtk.TextBuffer()
        log_view = Gtk.TextView(buffer=self.log_buffer)
        log_view.set_editable(False)
        log_view.set_cursor_visible(False)
        log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        log_view.set_monospace(True)
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        log_scroll.add(log_view)
        self.log_scroll = log_scroll
        self.notebook.append_page(log_scroll, Gtk.Label(label="Server log"))

        self.notebook.connect("switch-page", self._on_tab_switched)

        main.pack_start(self.notebook, True, True, 0)

        entry_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Ask the laptop something...")
        self.entry.connect("activate", lambda e: self._on_send())
        entry_box.pack_start(self.entry, True, True, 0)

        self.retry_btn = Gtk.Button(label="Retry last")
        self.retry_btn.connect("clicked", lambda b: self._on_retry())
        self.retry_btn.set_sensitive(False)
        entry_box.pack_start(self.retry_btn, False, False, 0)

        self.send_btn = Gtk.Button(label="Send")
        self.send_btn.connect("clicked", lambda b: self._on_send())
        entry_box.pack_start(self.send_btn, False, False, 0)
        main.pack_start(entry_box, False, False, 0)

        self.pack_start(main, True, True, 0)

    # -- Server status / lifecycle ---------------------------------------

    def _poll_server_status(self):
        threading.Thread(target=self._check_server_health, daemon=True).start()
        return True  # keep the GLib timeout running

    def _check_server_health(self):
        try:
            with urllib.request.urlopen(self._url("/health"), timeout=3) as resp:
                up = resp.status == 200
        except Exception:
            up = False
        GLib.idle_add(self._set_server_status, up)

    def _set_server_status(self, up):
        was_up = self.server_up
        self.server_up = up
        remote = self._is_remote()
        launching = self.server_proc is not None and self.server_proc.poll() is None

        if up:
            self.server_seen_up = True
            self.auto_restart_attempts = 0
            crash_note = f" (recovered after {self.crash_count} crash{'es' if self.crash_count != 1 else ''})" if self.crash_count else ""
            self.server_status_label.set_markup(f'<span foreground="#2e8b57">● server up</span>{crash_note}')
            if not remote:
                self.server_btn.set_sensitive(False)
                self.server_btn.set_label("Start server")
                self.stop_server_btn.set_sensitive(True)
                self.backend_combo.set_sensitive(False)
                self.batch_combo.set_sensitive(False)
                self.discoverable_check.set_sensitive(False)
            if not was_up:
                self._update_context_label()
            return

        if remote:
            # No local process to manage for a remote host -- just reflect down status, don't
            # touch the (already-disabled) local server-management controls.
            self.server_status_label.set_markup('<span foreground="#c0392b">● server down</span>')
            self.server_seen_up = False
            return

        if self.stopping_server:
            self.stopping_server = False
            self.server_seen_up = False
            self.server_status_label.set_markup('<span foreground="#c0392b">● server down</span>')
            self.server_btn.set_sensitive(True)
            self.stop_server_btn.set_sensitive(False)
            self.backend_combo.set_sensitive(True)
            self.batch_combo.set_sensitive(True)
            self.discoverable_check.set_sensitive(True)
            return

        if was_up and self.server_seen_up:
            # It was healthy and just dropped -- a crash, not a cold start.
            self.crash_count += 1
            self.server_seen_up = False
            self._append_error(
                f"[Model server crashed (#{self.crash_count}) -- likely a Vulkan GPU fault on this "
                "hardware. Auto-restarting...]"
            )
            self._schedule_auto_restart()
            return

        self.stop_server_btn.set_sensitive(False)
        if launching or self.auto_restart_pending:
            self.server_status_label.set_markup('<span foreground="#b8860b">● starting...</span>')
            self.server_btn.set_sensitive(False)
            self.backend_combo.set_sensitive(False)
            self.batch_combo.set_sensitive(False)
            self.discoverable_check.set_sensitive(False)
        else:
            self.server_status_label.set_markup('<span foreground="#c0392b">● server down</span>')
            self.server_btn.set_sensitive(True)
            self.backend_combo.set_sensitive(True)
            self.batch_combo.set_sensitive(True)
            self.discoverable_check.set_sensitive(True)

    def _schedule_auto_restart(self):
        if self.auto_restart_attempts >= AUTO_RESTART_MAX_ATTEMPTS:
            self.server_status_label.set_markup(
                f'<span foreground="#c0392b">● gave up after {self.crash_count} crashes</span>'
            )
            self.server_btn.set_sensitive(True)
            self.auto_restart_pending = False
            return
        delay_idx = min(self.auto_restart_attempts, len(AUTO_RESTART_BACKOFF_SEC) - 1)
        delay = AUTO_RESTART_BACKOFF_SEC[delay_idx]
        self.auto_restart_attempts += 1
        self.auto_restart_pending = True
        self.server_status_label.set_markup(
            f'<span foreground="#b8860b">● restarting in {delay}s (attempt '
            f'{self.auto_restart_attempts}/{AUTO_RESTART_MAX_ATTEMPTS})...</span>'
        )
        GLib.timeout_add_seconds(delay, self._auto_restart_fire)

    def _auto_restart_fire(self):
        self.auto_restart_pending = False
        self._launch_server()
        return False  # one-shot timeout

    def _update_lan_hint(self):
        if not self.discoverable_check.get_active():
            self.lan_hint_label.set_text("")
            return
        ip = local_lan_ip()
        if ip:
            self.lan_hint_label.set_markup(
                f'<span foreground="#666666">others can connect to: <b>{ip}:{SERVER_PORT}</b></span>'
            )
        else:
            self.lan_hint_label.set_markup(
                '<span foreground="#c0392b">couldn\'t determine this machine\'s LAN IP</span>'
            )

    def _on_backend_changed(self, combo):
        # -ub (GPU dispatch batch size) is a Vulkan-only lever -- irrelevant on the true CPU-only
        # build, which has no Vulkan backend linked at all. Only enable it when the backend combo
        # itself is enabled (i.e. no server currently running/starting).
        self.batch_combo.set_sensitive(combo.get_active_id() == "vulkan" and combo.get_sensitive())

    def _on_start_server(self):
        self.auto_restart_attempts = 0  # manual click resets the backoff series
        self._launch_server()

    def _launch_server(self):
        if self._is_remote():
            return  # local process management doesn't apply to a remote host
        if self.server_proc is not None and self.server_proc.poll() is None:
            return  # already launching
        backend = self.backend_combo.get_active_id() or "vulkan"
        batch = self.batch_combo.get_active_id() or "512"
        discoverable = self.discoverable_check.get_active()
        bind_host = "0.0.0.0" if discoverable else "127.0.0.1"
        cmd = (
            [SERVER_BACKEND_BIN[backend]] + SERVER_BACKEND_ARGS[backend]
            + ["--host", bind_host, "--port", str(SERVER_PORT)]
        )
        batch_note = ""
        if backend == "vulkan":
            cmd += ["-ub", batch]
            batch_note = f", batch {batch}"
        self.server_btn.set_sensitive(False)
        self.backend_combo.set_sensitive(False)
        self.batch_combo.set_sensitive(False)
        self.discoverable_check.set_sensitive(False)
        self.server_status_label.set_markup(
            f'<span foreground="#b8860b">● starting ({backend}{batch_note}'
            f'{", discoverable" if discoverable else ""})...</span>'
        )
        self._update_lan_hint()
        try:
            log_f = open(SERVER_LOG, "a")
            log_f.write(f"\n=== launching {backend} backend: {' '.join(cmd)} ===\n")
            log_f.flush()
            self.server_proc = subprocess.Popen(
                cmd,
                cwd=LLAMA_DIR,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as e:
            self.server_status_label.set_markup(f'<span foreground="#c0392b">launch failed: {e}</span>')
            self.server_btn.set_sensitive(True)
            self.backend_combo.set_sensitive(True)
            self.batch_combo.set_sensitive(True)
            self.discoverable_check.set_sensitive(True)

    def _on_stop_server(self):
        if self._is_remote():
            return  # local process management doesn't apply to a remote host
        self.stopping_server = True
        self.auto_restart_attempts = AUTO_RESTART_MAX_ATTEMPTS  # block any in-flight backoff from firing
        self.auto_restart_pending = False
        self.stop_server_btn.set_sensitive(False)
        self.server_status_label.set_markup('<span foreground="#b8860b">● stopping...</span>')
        # Kill by who's actually listening on the port, not by command-line pattern -- the running
        # server may have been started manually, outside this GUI, from a different build/script
        # than SERVER_BACKENDS uses, so its cmdline won't match any fixed pattern.
        try:
            pids = subprocess.run(
                ["lsof", "-t", "-i", f":8080", "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=5,
            ).stdout.split()
            for pid in pids:
                subprocess.run(["kill", "-TERM", pid])
        except (OSError, subprocess.SubprocessError):
            pass
        self.server_proc = None

    # -- Chat list handling ------------------------------------------------

    def _refresh_chat_list(self, select_id=None):
        self._suppress_chat_selected = True
        self.chat_list_store.clear()
        for cid, title in list_chats():
            self.chat_list_store.append([cid, title])
        if select_id:
            for row in self.chat_list_store:
                if row[0] == select_id:
                    self.chat_list_view.get_selection().select_iter(row.iter)
                    break
        self._suppress_chat_selected = False

    def _on_chat_selected(self, selection):
        if self._suppress_chat_selected:
            return  # programmatic select_iter from _refresh_chat_list, not a real user click
        model, it = selection.get_selected()
        if it is None:
            return
        cid = model[it][0]
        if cid != self.chat_id:
            self._load_chat(cid)

    def _on_delete_chat(self, button):
        if not self.chat_id:
            return
        try:
            os.remove(chat_path(self.chat_id))
        except OSError:
            pass
        self._refresh_chat_list()
        self._start_new_chat()

    # -- Chat state ----------------------------------------------------

    def _start_new_chat(self):
        self.chat_id = new_chat_id()
        self.messages = []
        self.transcript_buffer.set_text("")
        data = {"created": time.time(), "title": None, "messages": []}
        save_chat(self.chat_id, data)
        self._refresh_chat_list(select_id=self.chat_id)
        self._update_retry_sensitivity()
        self._update_context_label()
        self.entry.grab_focus()

    def _load_chat(self, chat_id):
        data = load_chat(chat_id)
        self.chat_id = chat_id
        self.messages = data.get("messages", [])
        self._rebuild_transcript()
        self._refresh_chat_list(select_id=chat_id)
        self._update_retry_sensitivity()
        self._update_context_label()

    def _rebuild_transcript(self):
        self.transcript_buffer.set_text("")
        for m in self.messages:
            self._append_message(m["role"], m["content"])

    def _persist(self):
        title = None
        for m in self.messages:
            if m["role"] == "user":
                title = m["content"][:40]
                break
        data = {"created": time.time(), "title": title, "messages": self.messages}
        save_chat(self.chat_id, data)
        self._refresh_chat_list(select_id=self.chat_id)
        self._update_retry_sensitivity()

    def _update_retry_sensitivity(self):
        has_user_msg = any(m["role"] == "user" for m in self.messages)
        self.retry_btn.set_sensitive(has_user_msg and not self.streaming)

    # -- Transcript rendering -------------------------------------------

    def _append_message(self, role, content):
        buf = self.transcript_buffer
        end = buf.get_end_iter()
        label = "You" if role == "user" else "Laptop"
        tag = "user" if role == "user" else "assistant"
        if buf.get_char_count() > 0:
            buf.insert(end, "\n\n")
            end = buf.get_end_iter()
        buf.insert_with_tags_by_name(end, f"{label}:\n", tag)
        end = buf.get_end_iter()
        buf.insert_with_tags_by_name(end, content, "body")
        self._scroll_to_end()

    def _append_error(self, text):
        buf = self.transcript_buffer
        end = buf.get_end_iter()
        if buf.get_char_count() > 0:
            buf.insert(end, "\n\n")
            end = buf.get_end_iter()
        buf.insert_with_tags_by_name(end, text, "error")
        self._scroll_to_end()

    def _scroll_to_end(self):
        adj = self.transcript_scroll.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()))

    # -- Context / server log tabs -----------------------------------------

    def _on_tab_switched(self, notebook, page, page_num):
        if page_num == 2:  # Server log
            self._refresh_log_tab(force=True)

    def _poll_log_tab(self):
        if self.notebook.get_current_page() == 2:
            self._refresh_log_tab()
        return True  # keep the GLib timeout running

    def _refresh_log_tab(self, force=False):
        if self._is_remote():
            return  # placeholder text was already set by _apply_remote_gating
        try:
            st = os.stat(SERVER_LOG)
            stat_key = (st.st_size, st.st_mtime)
        except OSError:
            stat_key = None
        if not force and stat_key == self.last_log_stat:
            return  # file hasn't changed since last read -- skip the disk read entirely
        self.last_log_stat = stat_key
        threading.Thread(target=self._read_log_tail, daemon=True).start()

    def _read_log_tail(self):
        try:
            size = os.path.getsize(SERVER_LOG)
            with open(SERVER_LOG, "rb") as f:
                if size > LOG_TAIL_BYTES:
                    f.seek(size - LOG_TAIL_BYTES)
                    f.readline()  # drop partial first line
                text = f.read().decode("utf-8", errors="replace")
        except OSError:
            text = "(no server log yet -- start the server first)"
        GLib.idle_add(self._set_log_text, text)

    def _set_log_text(self, text):
        if text == self.last_log_text:
            return
        self.last_log_text = text
        was_at_bottom = self._is_scrolled_to_bottom(self.log_scroll)
        self.log_buffer.set_text(text)
        if was_at_bottom:
            GLib.idle_add(self._scroll_to_bottom, self.log_scroll)

    def _is_scrolled_to_bottom(self, scroll):
        adj = scroll.get_vadjustment()
        return adj.get_value() >= adj.get_upper() - adj.get_page_size() - 20

    def _scroll_to_bottom(self, scroll):
        adj = scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())

    # -- Context size indicator -------------------------------------------

    def _build_api_messages(self):
        if self.knowledge_check.get_active():
            preprompt = KNOWLEDGE_PREPROMPT_REMOTE if self._is_remote() else KNOWLEDGE_PREPROMPT_LOCAL
            return [{"role": "system", "content": preprompt}] + self.messages
        return list(self.messages)

    def _update_context_label(self):
        api_messages = self._build_api_messages()
        formatted = "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in api_messages) or "(empty context)"
        self.context_buffer.set_text(formatted)

        if not self.server_up:
            self.context_label.set_text("")
            return
        threading.Thread(target=self._count_context_tokens, args=(api_messages,), daemon=True).start()

    def _count_context_tokens(self, api_messages):
        # Rough approximation: tokenize the concatenated role+content text. Doesn't reproduce
        # the exact chat template (a few special tokens off), close enough for a UI indicator.
        text = "\n".join(f"{m['role']}: {m['content']}" for m in api_messages)
        payload = json.dumps({"content": text}).encode()
        req = urllib.request.Request(
            self._url("/tokenize"), data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                obj = json.loads(resp.read())
            n = len(obj.get("tokens", []))
        except Exception:
            return
        GLib.idle_add(self._set_context_label, n)

    def _set_context_label(self, n):
        pct = n / N_CTX
        color = "#c0392b" if pct > 0.85 else ("#b8860b" if pct > 0.6 else "#666666")
        self.context_label.set_markup(f'<span foreground="{color}">context: ~{n}/{N_CTX}</span>')

    # -- Sending / streaming ---------------------------------------------

    def _on_send(self):
        if self.streaming:
            return
        text = self.entry.get_text().strip()
        if not text:
            return
        if not self.server_up:
            self._append_error("The model server isn't running -- click \"Start server\" above and wait for it to come up.")
            return
        self.entry.set_text("")

        self.messages.append({"role": "user", "content": text})
        self._append_message("user", text)
        self._persist()
        self._start_generation()

    def _on_retry(self):
        if self.streaming:
            return
        last_user_idx = None
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i]["role"] == "user":
                last_user_idx = i
                break
        if last_user_idx is None:
            return
        if not self.server_up:
            self._append_error("The model server isn't running -- click \"Start server\" above and wait for it to come up.")
            return
        self.messages = self.messages[:last_user_idx + 1]
        self._rebuild_transcript()
        self._persist()
        self._start_generation()

    def _start_generation(self):
        self._begin_assistant_stream()
        self._update_context_label()
        api_messages = self._build_api_messages()

        self.streaming = True
        self.send_btn.set_sensitive(False)
        self.retry_btn.set_sensitive(False)
        self.status_label.set_text("thinking...")

        thread = threading.Thread(target=self._stream_worker, args=(api_messages,), daemon=True)
        thread.start()

    def _begin_assistant_stream(self):
        buf = self.transcript_buffer
        end = buf.get_end_iter()
        buf.insert(end, "\n\n")
        end = buf.get_end_iter()
        buf.insert_with_tags_by_name(end, "Laptop:\n", "assistant")
        end = buf.get_end_iter()
        buf.insert_with_tags_by_name(end, "", "body")
        self.stream_mark = buf.create_mark("stream_pos", buf.get_end_iter(), False)
        self._scroll_to_end()

    def _stream_append(self, chunk):
        buf = self.transcript_buffer
        it = buf.get_iter_at_mark(self.stream_mark)
        buf.insert_with_tags_by_name(it, chunk, "body")
        self._scroll_to_end()

    def _stream_worker(self, api_messages):
        # Pin each chat to one slot and keep cache_prompt on so llama-server reuses the
        # cached KV-cache prefix across turns instead of recomputing the whole history.
        id_slot = int(self.chat_id.replace("-", "")) % N_SLOTS
        payload = json.dumps({
            "model": "qwen",
            "messages": api_messages,
            "stream": True,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "temperature": 0.7,
            "cache_prompt": True,
            "id_slot": id_slot,
        }).encode()

        url = self._url("/v1/chat/completions")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )

        full_reply = []
        error = None
        saw_done = False
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    payload_str = line[len("data:"):].strip()
                    if payload_str == "[DONE]":
                        saw_done = True
                        break
                    try:
                        obj = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue
                    if "error" in obj:
                        error = f"Model server reported an error: {obj['error']}"
                        break
                    delta = obj.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        full_reply.append(content)
                        GLib.idle_add(self._stream_append, content)
        except urllib.error.URLError as e:
            error = f"Could not reach the model server at {url}: {e}"
        except Exception as e:
            error = f"Error while streaming response: {e}"

        if error is None and not saw_done and not full_reply:
            error = ("Model server closed the connection without responding -- likely a GPU "
                      "crash mid-request. Check the server status above.")

        GLib.idle_add(self._stream_done, "".join(full_reply), error)

    def _stream_done(self, reply_text, error):
        self.streaming = False
        self.send_btn.set_sensitive(True)
        self.status_label.set_text("")

        if error:
            buf = self.transcript_buffer
            end = buf.get_end_iter()
            buf.insert_with_tags_by_name(end, f"\n[{error}]", "error")
            self._scroll_to_end()
            if not reply_text:
                self._update_retry_sensitivity()
                return

        self.messages.append({"role": "assistant", "content": reply_text})
        self._persist()
        self._update_context_label()
        self.entry.grab_focus()


class LLMChatWindow(Gtk.Window):

    def __init__(self):
        super().__init__(title="Cyberbeest LLM Chat")
        self.set_default_size(820, 600)
        self.connect("destroy", Gtk.main_quit)
        self.add(LLMChatPage())


def main():
    win = LLMChatWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
