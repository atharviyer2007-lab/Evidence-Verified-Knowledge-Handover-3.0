"""A small, dependency-free PDF writer for the handover report (Helvetica text only)."""

PAGE_W, PAGE_H, MARGIN = 595, 842, 56
FONT_SIZES = {"title": 17, "heading": 12.5, "body": 10, "meta": 8.5}
LEADING = {"title": 22, "heading": 17, "body": 13.5, "meta": 11.5}
FONT_FOR = {"title": "F2", "heading": "F2", "body": "F1", "meta": "F1"}


def _clean(text):
    text = (str(text) or "").replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2026", "...").replace("\u2022", "-")
    return "".join(ch if 32 <= ord(ch) < 127 or ch == "\n" else "?" for ch in text)


def _escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(text, style):
    limit = int((PAGE_W - 2 * MARGIN) / (FONT_SIZES[style] * (0.56 if style in ("title", "heading") else 0.5)))
    lines = []
    for paragraph in _clean(text).split("\n"):
        line = ""
        for word in paragraph.split():
            while len(word) > limit:
                lines.append((line + " " + word[: limit - len(line) - 1]).strip() if line else word[:limit])
                word, line = word[limit - len(line) - 1 if line else limit :], ""
            if len(line) + len(word) + (1 if line else 0) > limit:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        lines.append(line)
    return lines


def build(title, blocks):
    """`blocks` is a list of (style, text) with style one of title, heading, body, meta."""
    pages, current, y = [], [], PAGE_H - MARGIN
    for style, text in [("title", title), *blocks]:
        extra = 6 if style == "heading" else 3
        y -= extra if current else 0
        for line in _wrap(text, style):
            if y - LEADING[style] < MARGIN:
                pages.append(current)
                current, y = [], PAGE_H - MARGIN
            y -= LEADING[style]
            if line:
                current.append(f"BT /{FONT_FOR[style]} {FONT_SIZES[style]} Tf {MARGIN} {y:.1f} Td ({_escape(line)}) Tj ET")
    pages.append(current)

    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    font_ids = (3 + 2 * len(pages), 4 + 2 * len(pages))
    for index, commands in enumerate(pages):
        page_id, content_id = 3 + 2 * index, 4 + 2 * index
        kids.append(f"{page_id} 0 R")
        stream = "\n".join(commands).encode("latin-1")
        objects.append(
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] /Contents {content_id} 0 R "
             f"/Resources << /Font << /F1 {font_ids[0]} 0 R /F2 {font_ids[1]} 0 R >> >> >>").encode())
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode()

    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
