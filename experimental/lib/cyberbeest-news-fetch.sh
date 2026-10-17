#!/bin/bash
# Fetches the Cyberbeest News headline list and turns the newest ones into
# Whisker menu entries (category "Ω Cyberbeest News"). EXPERIMENTAL: installed
# to /usr/local/sbin/cyberbeest-news-fetch.sh by experimental/enable-
# cyberbeest-news.sh (undo: disable-cyberbeest-news.sh), which also adds a
# systemd drop-in so this runs after every security-update-check.service run.
# That service fires every 15 minutes and mostly skips, so this script keeps
# its own throttle (about every 2 hours, like the security check).
#
# Traffic: one conditional GET (If-None-Match) of a single static file. When
# nothing changed the server answers 304 with no body. The server sends no
# cookies and keeps no access logs (see cyberbeest-vserver Caddyfile); the
# request carries a generic user agent and no machine identifier.
#
# The list is accumulated locally (by headline id), so a headline stays
# available after the server drops it. The server file is untrusted input:
# ids, dates, titles and URLs are validated strictly, and the Exec line is
# built from an allow-listed URL only.
#
# Opt-out: touch /etc/cyberbeest/news-disabled (nothing is fetched, existing
# entries are removed).
#
# Test mode: with CYBERBEEST_NEWS_TEST_DIR set, state and .desktop files go
# under that directory and CYBERBEEST_NEWS_URL may be a plain http URL.
set -uo pipefail

NEWS_URL="https://news.cyberbeest.com/headlines.json"
STATE_DIR=/var/lib/cyberbeest-news
APP_DIR=/usr/share/applications
DISABLED_FLAG=/etc/cyberbeest/news-disabled
CURL_PROTO="=https"
if [ -n "${CYBERBEEST_NEWS_TEST_DIR:-}" ]; then
    STATE_DIR="$CYBERBEEST_NEWS_TEST_DIR/state"
    APP_DIR="$CYBERBEEST_NEWS_TEST_DIR/applications"
    DISABLED_FLAG="$CYBERBEEST_NEWS_TEST_DIR/disabled"
    NEWS_URL="${CYBERBEEST_NEWS_URL:-$NEWS_URL}"
    CURL_PROTO="=http,https"
fi
SHOW_COUNT=5
MAX_ARCHIVE=200

mkdir -p "$STATE_DIR" "$APP_DIR"

# Throttle: stamp every attempt (also failed ones), at most one per ~2 hours.
# CYBERBEEST_NEWS_FORCE=1 skips the throttle for manual runs.
MIN_INTERVAL_SECONDS=$(( 115 * 60 ))
STAMP="$STATE_DIR/last-attempt"
if [ "${CYBERBEEST_NEWS_FORCE:-0}" != 1 ] && [ -e "$STAMP" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$STAMP") ))
    if [ "$age" -ge 0 ] && [ "$age" -lt "$MIN_INTERVAL_SECONDS" ]; then
        exit 0
    fi
fi

if [ -e "$DISABLED_FLAG" ]; then
    rm -f "$APP_DIR"/cyberbeest-news-*.desktop
    echo "News disabled -- nothing fetched."
    exit 0
fi

touch "$STAMP"
tmp="$(mktemp "$STATE_DIR/fetch.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

code="$(curl -sS --max-time 20 --connect-timeout 10 --max-filesize 262144 \
    --proto "$CURL_PROTO" --proto-redir "$CURL_PROTO" --max-redirs 0 \
    -A "cyberbeest-news/1" \
    --etag-save "$STATE_DIR/etag" --etag-compare "$STATE_DIR/etag" \
    -o "$tmp" -w '%{http_code}' "$NEWS_URL" 2>&1)" || {
    echo "News fetch failed: $code"
    exit 0
}

case "$code" in
    304) echo "News: not modified." ;;
    200) ;;
    *)   echo "News fetch: unexpected HTTP status $code"; exit 0 ;;
esac

python3 - "$tmp" "$code" "$STATE_DIR" "$APP_DIR" "$SHOW_COUNT" "$MAX_ARCHIVE" <<'PY'
import json, os, re, sys, tempfile

tmp, code, state_dir, app_dir, show_count, max_archive = sys.argv[1:7]
show_count, max_archive = int(show_count), int(max_archive)
archive_path = os.path.join(state_dir, "headlines.json")

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL_RE = re.compile(r"^https://(cyberbeest\.com|news\.cyberbeest\.com)/[A-Za-z0-9/._~?=&#-]{0,200}$")
LANGS = ("en", "de")


def clean_title(s):
    if not isinstance(s, str):
        return None
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    return s[:80]


def clean_entry(e):
    if not isinstance(e, dict):
        return None
    if not (isinstance(e.get("id"), str) and ID_RE.match(e["id"])):
        return None
    if not (isinstance(e.get("date"), str) and DATE_RE.match(e["date"])):
        return None
    if not (isinstance(e.get("url"), str) and URL_RE.match(e["url"])):
        return None
    titles = e.get("title")
    if not isinstance(titles, dict):
        return None
    out_titles = {}
    for lang in LANGS:
        t = clean_title(titles.get(lang))
        if t:
            out_titles[lang] = t
    if "en" not in out_titles:
        return None
    return {"id": e["id"], "date": e["date"], "url": e["url"], "title": out_titles}


archive = {}
try:
    with open(archive_path) as f:
        for e in json.load(f):
            c = clean_entry(e)
            if c:
                archive[c["id"]] = c
except (OSError, ValueError, TypeError):
    pass

if code == "200":
    try:
        with open(tmp) as f:
            data = json.load(f)
        incoming = data["headlines"]
        if not isinstance(incoming, list):
            raise ValueError("headlines is not a list")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("News: ignoring malformed response (%s)" % exc)
        sys.exit(0)
    added = 0
    for e in incoming:
        c = clean_entry(e)
        if c:
            if c["id"] not in archive:
                added += 1
            archive[c["id"]] = c
    print("News: %d headline(s) in response, %d new." % (len(incoming), added))

ordered = sorted(archive.values(), key=lambda e: (e["date"], e["id"]), reverse=True)[:max_archive]

fd, tmp_archive = tempfile.mkstemp(dir=state_dir)
with os.fdopen(fd, "w") as f:
    json.dump(ordered, f, indent=1, ensure_ascii=False)
os.chmod(tmp_archive, 0o644)
os.replace(tmp_archive, archive_path)

shown = ordered[:show_count]
wanted = set()
for e in shown:
    name = "cyberbeest-news-%s.desktop" % e["id"]
    wanted.add(name)
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=%s" % e["title"]["en"],
    ]
    if "de" in e["title"]:
        lines.append("Name[de]=%s" % e["title"]["de"])
    lines += [
        "Comment=%s" % e["date"],
        'Exec=firefox "%s"' % e["url"],
        "Icon=text-x-generic",
        "Terminal=false",
        "Categories=CyberbeestNews;",
        "",
    ]
    fd, p = tempfile.mkstemp(dir=app_dir, prefix=".news-")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines))
    os.chmod(p, 0o644)
    os.replace(p, os.path.join(app_dir, name))

for fn in os.listdir(app_dir):
    if fn.startswith("cyberbeest-news-") and fn.endswith(".desktop") and fn not in wanted:
        os.remove(os.path.join(app_dir, fn))
PY
exit 0
