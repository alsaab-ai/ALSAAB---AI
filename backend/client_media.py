# client_media.py
#
# Storage for the images a customer uploads for their own products.
#
# Before this module the upload went nowhere: the dashboard read the file,
# base64-encoded it into the payload, and the storage layer never looked at
# `uploaded_files` -- so every image group was saved with image_urls = [] and
# every file the customer picked was dropped on the floor without an error.
#
# Files live on the server's own disk, under one folder per partner:
#
#   backend/client_data/media/<partner_id>/<group_id>/<uuid>.<ext>
#
# WHAT GETS STORED IN THE DATABASE IS A ROOT-RELATIVE PATH:
#
#   /client-media/ALS-P00021/GRP-abc123/7f3e....jpg
#
# not a full URL. That is deliberate, and it is what makes the same row work
# on a laptop and on Render without a rewrite:
#
#   * A relative path in an <img src> resolves against whatever host served
#     the page, so the dashboard renders correctly on localhost:10000 and on
#     alsaab-ai.onrender.com from the identical database row.
#   * Storing "http://localhost:10000/..." would have baked the dev machine
#     into production data; storing the Render URL would have broken every
#     local run. A relative path commits to neither.
#
# Anything leaving the app -- a link the bot sends a buyer over WhatsApp --
# needs a real host in front of it, so call absolute_url() at that moment and
# nowhere else. It prefers APP_BASE_URL, falling back to the host of the
# request being served.

import os
import re
import uuid

MEDIA_URL_PREFIX = "/client-media"

ALLOWED_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}

MAX_BYTES_PER_FILE = 5 * 1024 * 1024

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_\-.]{1,120}$")


def media_root():
    """backend/client_data/media, created on first use."""
    root = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "client_data",
        "media",
    )

    os.makedirs(root, exist_ok=True)

    return root


def _extension_for(filename, mime_type=""):
    """
    Pick a safe extension, from the filename first and the browser's mime type
    second. The uploader's filename never reaches the disk -- it is replaced by
    a uuid -- so this only decides the suffix and the content type on the way
    back out.
    """
    _, ext = os.path.splitext(str(filename or "").lower())

    if ext in ALLOWED_EXTENSIONS:
        return ext

    mime = str(mime_type or "").lower().split(";")[0].strip()

    for candidate, candidate_mime in ALLOWED_EXTENSIONS.items():
        if candidate_mime == mime:
            return candidate

    return ""


def content_type_for(path):
    _, ext = os.path.splitext(str(path or "").lower())
    return ALLOWED_EXTENSIONS.get(ext, "application/octet-stream")


def _safe_segment(value, fallback):
    value = str(value or "").strip()
    return value if _SAFE_SEGMENT.match(value) else fallback


def save_uploads(partner_id, group_id, files):
    """
    Write uploaded files to disk and return their root-relative paths.

    `files` are Werkzeug FileStorage objects. Files that are empty, oversized,
    or of a type not in ALLOWED_EXTENSIONS are skipped rather than raising --
    one bad file should not lose the whole group.
    """
    partner_segment = _safe_segment(partner_id, "unknown")
    group_segment = _safe_segment(group_id, "ungrouped")

    folder = os.path.join(media_root(), partner_segment, group_segment)
    os.makedirs(folder, exist_ok=True)

    saved = []

    for item in files or []:
        if not item or not getattr(item, "filename", ""):
            continue

        extension = _extension_for(item.filename, getattr(item, "content_type", ""))

        if not extension:
            print(f"CLIENT MEDIA SKIPPED unsupported type={item.filename}", flush=True)
            continue

        raw = item.read()

        if not raw:
            continue

        if len(raw) > MAX_BYTES_PER_FILE:
            print(f"CLIENT MEDIA SKIPPED too large={item.filename} ({len(raw)} bytes)", flush=True)
            continue

        name = uuid.uuid4().hex + extension

        with open(os.path.join(folder, name), "wb") as handle:
            handle.write(raw)

        saved.append(f"{MEDIA_URL_PREFIX}/{partner_segment}/{group_segment}/{name}")

    if saved:
        print(f"CLIENT MEDIA SAVED ✅ partner_id={partner_id} files={len(saved)}", flush=True)

    return saved


def resolve_path(partner_id, group_id, filename):
    """
    Absolute filesystem path for one stored file, or "" when any segment looks
    unsafe or the result would escape the media root. The containment check is
    what stops ../ in a request path from reaching the rest of the disk.
    """
    for segment in (partner_id, group_id, filename):
        if not _SAFE_SEGMENT.match(str(segment or "")):
            return ""

    root = media_root()
    target = os.path.normpath(os.path.join(root, partner_id, group_id, filename))

    if not target.startswith(os.path.normpath(root) + os.sep):
        return ""

    return target if os.path.isfile(target) else ""


def delete_file(relative_url):
    """Remove one stored file. Missing files are not an error."""
    parts = str(relative_url or "").strip().strip("/").split("/")

    if len(parts) != 4 or "/" + parts[0] != MEDIA_URL_PREFIX:
        return False

    target = resolve_path(parts[1], parts[2], parts[3])

    if not target:
        return False

    try:
        os.remove(target)
        return True
    except OSError as error:
        print(f"CLIENT MEDIA DELETE FAILED ❌ {relative_url} {error}", flush=True)
        return False


BRAND_FOLDER = "__brand__"
BRAND_FILE = "brand.json"


def _brand_path(partner_id, create=False):
    partner_segment = _safe_segment(partner_id, "")

    if not partner_segment:
        return ""

    folder = os.path.join(media_root(), partner_segment, BRAND_FOLDER)

    if create:
        os.makedirs(folder, exist_ok=True)

    return os.path.join(folder, BRAND_FILE)


def load_brand(partner_id):
    """
    Display preferences for one account: what it calls its catalog, and so on.

    Kept beside the logo as a small file rather than as new columns on
    client_profiles. That table is written by a shared upsert against a live
    database; widening it for a wording preference is a schema migration in
    production to change a heading. A file needs no migration and no
    coordination, and this is presentation, not business data.
    """
    import json

    path = _brand_path(partner_id)

    if not path or not os.path.isfile(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        return data if isinstance(data, dict) else {}

    except Exception as error:
        print(f"BRAND LOAD FAILED ⚠️ {partner_id} {error}", flush=True)
        return {}


def save_brand(partner_id, **fields):
    """Merge fields into the account's brand settings. Blank values are ignored."""
    import json

    path = _brand_path(partner_id, create=True)

    if not path:
        return {}

    data = load_brand(partner_id)

    for key, value in fields.items():
        value = str(value or "").strip()

        if value:
            data[key] = value
        else:
            data.pop(key, None)

    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)

        print(f"BRAND SAVED ✅ partner_id={partner_id} keys={sorted(data)}", flush=True)

    except Exception as error:
        print(f"BRAND SAVE FAILED ❌ {partner_id} {error}", flush=True)

    return data


def save_logo(partner_id, uploaded):
    """
    Store one logo for an account and return its relative path.

    Kept as a file at a known location rather than a new database column: the
    schema is shared with a live Render deployment, and a folder needs no
    migration to reach it. One logo per account, so the previous file is
    removed first and the name is fixed.
    """
    if not uploaded or not getattr(uploaded, "filename", ""):
        return ""

    extension = _extension_for(uploaded.filename, getattr(uploaded, "content_type", ""))

    if not extension or extension == ".pdf":
        print(f"CLIENT LOGO SKIPPED unsupported={uploaded.filename}", flush=True)
        return ""

    raw = uploaded.read()

    if not raw or len(raw) > MAX_BYTES_PER_FILE:
        return ""

    partner_segment = _safe_segment(partner_id, "unknown")
    folder = os.path.join(media_root(), partner_segment, BRAND_FOLDER)
    os.makedirs(folder, exist_ok=True)

    for name in os.listdir(folder):
        if name.startswith("logo."):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass

    name = "logo" + extension

    with open(os.path.join(folder, name), "wb") as handle:
        handle.write(raw)

    print(f"CLIENT LOGO SAVED ✅ partner_id={partner_id}", flush=True)

    # Cache-bust on the page: the filename is stable, so a replaced logo would
    # otherwise keep showing the old one from the browser cache.
    return f"{MEDIA_URL_PREFIX}/{partner_segment}/{BRAND_FOLDER}/{name}?v={int(os.path.getmtime(os.path.join(folder, name)))}"


def logo_url(partner_id):
    """Relative path to this account's logo, or "" when it has none."""
    partner_segment = _safe_segment(partner_id, "")

    if not partner_segment:
        return ""

    folder = os.path.join(media_root(), partner_segment, BRAND_FOLDER)

    if not os.path.isdir(folder):
        return ""

    for name in sorted(os.listdir(folder)):
        if name.startswith("logo."):
            stamp = int(os.path.getmtime(os.path.join(folder, name)))
            return f"{MEDIA_URL_PREFIX}/{partner_segment}/{BRAND_FOLDER}/{name}?v={stamp}"

    return ""


def absolute_url(relative_url):
    """
    Turn a stored relative path into a full URL, for the one case that needs
    it: a link handed to somebody outside the app, such as an image the bot
    sends a buyer on WhatsApp. Inside the dashboard keep using the relative
    path so the page works on whichever host is serving it.
    """
    value = str(relative_url or "").strip()

    if not value:
        return ""

    if value.startswith("http://") or value.startswith("https://"):
        return value

    base = ""

    # The host actually serving this request comes first. APP_BASE_URL points
    # at production, so preferring it handed a localhost run image links on
    # alsaab-ai.onrender.com -- where the file does not exist, so nothing
    # loaded. The serving host is right for both a laptop and a custom domain.
    try:
        from flask import request

        host = request.host or ""

        if host:
            local = host.startswith("localhost") or host.startswith("127.0.0.1")

            # Render terminates TLS at its proxy, so request.url_root reports
            # http:// even though the visitor arrived over https. Only a real
            # local host is served plainly.
            base = ("http://" if local else "https://") + host

    except Exception:
        base = ""

    if not base:
        # Outside a request -- a scheduled send, a worker -- there is no host
        # to borrow, so fall back to the configured public address.
        try:
            from config import APP_BASE_URL
            base = str(APP_BASE_URL or "").strip().rstrip("/")
        except Exception:
            base = ""

    if not base:
        return value

    return base.rstrip("/") + "/" + value.lstrip("/")
