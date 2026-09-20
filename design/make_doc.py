"""
make_doc.py — Quill Cowork design & content document
Requires: pip install python-docx
Run: python make_doc.py
"""

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

PAPER_BASE    = "F4EFE0"
PAPER_SURFACE = "ECE5D3"
INK_PRIMARY   = "0A0A0A"
INK_SECONDARY = "2C2B27"
INK_MUTED     = "7D7A71"
ACCENT_MINT   = "1B8A5A"
ACCENT_LEMON  = "FFC700"
HINT_BG       = "E7E4DC"

F_DISPLAY = "Space Grotesk"
F_BODY    = "Plus Jakarta Sans"
F_MONO    = "JetBrains Mono"


def hex_to_rgb(h):
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def shade_cell(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill)
    tcPr.append(shd)


def no_borders(cell):
    tcPr = cell._tc.get_or_add_tcPr()
    b = OxmlElement('w:tcBorders')
    for edge in ('top', 'left', 'bottom', 'right'):
        e = OxmlElement(f'w:{edge}')
        e.set(qn('w:val'), 'nil')
        b.append(e)
    tcPr.append(b)


def dashed_borders(cell, color=INK_MUTED):
    tcPr = cell._tc.get_or_add_tcPr()
    b = OxmlElement('w:tcBorders')
    for edge in ('top', 'left', 'bottom', 'right'):
        e = OxmlElement(f'w:{edge}')
        e.set(qn('w:val'), 'dashed')
        e.set(qn('w:sz'), '8')
        e.set(qn('w:color'), color)
        b.append(e)
    tcPr.append(b)


def cell_margins(cell, top=100, left=200, bottom=100, right=200):
    tcPr = cell._tc.get_or_add_tcPr()
    m = OxmlElement('w:tcMar')
    for tag, val in (('top', top), ('left', left),
                     ('bottom', bottom), ('right', right)):
        n = OxmlElement(f'w:{tag}')
        n.set(qn('w:w'), str(val))
        n.set(qn('w:type'), 'dxa')
        m.append(n)
    tcPr.append(m)


def set_font(run, name, size, color, bold=False, italic=False):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor(*hex_to_rgb(color))
    run.bold = bold
    run.italic = italic
    rPr = run._element.get_or_add_rPr()
    rf = rPr.find(qn('w:rFonts'))
    if rf is None:
        rf = OxmlElement('w:rFonts')
        rPr.insert(0, rf)
    for a in ('w:ascii', 'w:hAnsi', 'w:eastAsia', 'w:cs'):
        rf.set(qn(a), name)


def para(container, text='', font=F_BODY, size=10.5, color=INK_SECONDARY,
         bold=False, italic=False, after=6, before=0, align=None,
         line_spacing=1.4):
    if (hasattr(container, 'paragraphs')
            and len(container.paragraphs) == 1
            and container.paragraphs[0].text == ''
            and not container.paragraphs[0].runs):
        p = container.paragraphs[0]
    else:
        p = container.add_paragraph()
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.line_spacing = line_spacing
    if text:
        r = p.add_run(text)
        set_font(r, font, size, color, bold, italic)
    return p


def section_label(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(18)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(text.upper())
    set_font(r, F_MONO, 9, INK_MUTED, bold=False)


def h1(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(10)
    r = p.add_run(text)
    set_font(r, F_DISPLAY, 22, INK_PRIMARY, bold=True)
    return p


def h2(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    set_font(r, F_DISPLAY, 14, INK_PRIMARY, bold=True)
    return p


def photo_placeholder(doc, label, height_in=2.6):
    t = doc.add_table(rows=1, cols=1)
    t.autofit = False
    cell = t.cell(0, 0)
    cell.width = Inches(6.5)
    shade_cell(cell, HINT_BG)
    dashed_borders(cell, INK_MUTED)
    cell_margins(cell, top=600, bottom=600, left=200, right=200)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(f"[ {label} ]")
    set_font(r, F_MONO, 10, INK_MUTED, italic=True)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)


doc = Document()
sec = doc.sections[0]
sec.page_width = Inches(8.5)
sec.page_height = Inches(11)
sec.top_margin = Inches(0.9)
sec.bottom_margin = Inches(0.9)
sec.left_margin = Inches(1.0)
sec.right_margin = Inches(1.0)

normal = doc.styles['Normal']
normal.font.name = F_BODY
normal.font.size = Pt(10.5)
rpr = normal.element.get_or_add_rPr()
rf = rpr.find(qn('w:rFonts'))
if rf is None:
    rf = OxmlElement('w:rFonts')
    rpr.append(rf)
for a in ('w:ascii', 'w:hAnsi', 'w:eastAsia', 'w:cs'):
    rf.set(qn(a), F_BODY)

# ============ COVER ============
for _ in range(3):
    doc.add_paragraph()

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(4)
r = p.add_run("✦")
set_font(r, F_DISPLAY, 40, ACCENT_MINT)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(6)
r = p.add_run("QUILL COWORK")
set_font(r, F_DISPLAY, 32, INK_PRIMARY, bold=True)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(30)
r = p.add_run("Design Document & Technical Specification")
set_font(r, F_BODY, 13, INK_MUTED)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("—  ✦  —")
set_font(r, F_BODY, 12, INK_MUTED)

for _ in range(3):
    doc.add_paragraph()

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(4)
r = p.add_run("A local-first agentic AI coworker with\nreactive interfaces and layered safety")
set_font(r, F_BODY, 11, INK_SECONDARY, italic=True)

for _ in range(6):
    doc.add_paragraph()

meta = doc.add_table(rows=4, cols=2)
meta.autofit = False
labels = ["Author", "Affiliation", "Date", "Version"]
values = ["[YOUR NAME]", "[YOUR COLLEGE]", "September 2026", "1.0"]
for i, (lbl, val) in enumerate(zip(labels, values)):
    c0, c1 = meta.rows[i].cells
    c0.width = Inches(1.4)
    c1.width = Inches(5.1)
    no_borders(c0); no_borders(c1)
    cell_margins(c0, top=20, bottom=20, left=0, right=100)
    cell_margins(c1, top=20, bottom=20, left=0, right=0)
    para(c0, lbl.upper(), font=F_MONO, size=8, color=INK_MUTED, after=2)
    para(c1, val, font=F_BODY, size=10.5, color=INK_PRIMARY, after=2)

doc.add_page_break()

# ============ CONTENTS ============
h1(doc, "Contents")
toc_items = [
    "1.  Overview",
    "2.  The Interface",
    "3.  Color System",
    "4.  Typography",
    "5.  Architecture",
    "6.  Safety Layers",
    "7.  Paper Abstract",
]
for item in toc_items:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(item)
    set_font(r, F_BODY, 11, INK_SECONDARY)

doc.add_page_break()

# ============ 1. OVERVIEW ============
section_label(doc, "Section 01")
h1(doc, "Overview")

para(doc,
     "Quill Cowork is a local-first agentic AI assistant that runs entirely on the "
     "user's machine. It reads files, checks GitHub notifications, and executes "
     "multi-step tasks through a modular connector system — without transmitting "
     "user data to any external server.",
     after=8)

para(doc,
     "The interface is designed around three principles: warmth over spectacle, "
     "clarity over density, and quiet presence over attention-grabbing animations. "
     "The palette draws from paper and ink rather than the neon gradients common in "
     "contemporary AI products. The result is an interface that feels like a "
     "long-form writing tool rather than a chat widget.",
     after=14)

section_label(doc, "Figure 1")
photo_placeholder(doc, "PHOTO PLACEHOLDER — Full interface, desktop view")

para(doc,
     "Figure 1. The Quill Cowork interface at rest. The sidebar shows connected "
     "services and quick actions; the canvas hosts the zero state; the floating "
     "input dock sits at the bottom of the viewport.",
     font=F_BODY, size=9, color=INK_MUTED, italic=True, after=0)

doc.add_page_break()

# ============ 2. INTERFACE ============
section_label(doc, "Section 02")
h1(doc, "The Interface")

h2(doc, "Sidebar")
para(doc,
     "A 240-pixel-wide column on the left holds three zones: brand and primary "
     "action at the top, connector list in the middle, quick actions below. The "
     "sidebar shares the same paper-base background as the main canvas — there is "
     "no visual divider. Separation is achieved through content spacing rather than "
     "borders, keeping the interface airy.",
     after=8)

section_label(doc, "Figure 2")
photo_placeholder(doc, "PHOTO PLACEHOLDER — Sidebar detail", height_in=2.0)

h2(doc, "Main Canvas")
para(doc,
     "The canvas is a single scroll column with a maximum content width of 768 "
     "pixels. Messages appear as they arrive: user turns on the right, in a "
     "paper-surface bubble; assistant turns on the left with no bubble, as plain "
     "text on the paper base. This asymmetry is deliberate — it treats the "
     "assistant's reply as document content rather than as a chat bubble.",
     after=8)

section_label(doc, "Figure 3")
photo_placeholder(doc, "PHOTO PLACEHOLDER — Conversation view with tool call", height_in=2.4)

h2(doc, "Input Dock")
para(doc,
     "A floating bar at the bottom of the viewport with a semi-transparent "
     "paper-surface background and an 18px backdrop blur. The dock contains the "
     "message textarea, an attach control, and a circular send button in ink "
     "primary. The dock hovers over the scroll area rather than sitting in the "
     "layout flow, so content can scroll behind it.",
     after=8)

section_label(doc, "Figure 4")
photo_placeholder(doc, "PHOTO PLACEHOLDER — Input dock close-up", height_in=1.5)

doc.add_page_break()

# ============ 3. COLOR ============
section_label(doc, "Section 03")
h1(doc, "Color System")

para(doc,
     "The palette is warm and low-contrast by design. Paper-base carries the page; "
     "paper-surface provides a subtle step for cards and inputs. Accent Mint is "
     "used sparingly — for active dots, brand marks, and inline links. Accent "
     "Lemon appears only as a text-selection highlight.",
     after=12)

palette = [
    ("paper-base",    PAPER_BASE,    "Page background"),
    ("paper-surface", PAPER_SURFACE, "Cards, inputs, chips"),
    ("ink-primary",   INK_PRIMARY,   "Primary text, send button"),
    ("ink-secondary", INK_SECONDARY, "Body text"),
    ("ink-muted",     INK_MUTED,     "Labels, metadata, placeholders"),
    ("accent-mint",   ACCENT_MINT,   "Brand accent, active state"),
    ("accent-lemon",  ACCENT_LEMON,  "Text selection highlight"),
]

t = doc.add_table(rows=1, cols=3)
t.autofit = False
hdr = t.rows[0].cells
for i, txt in enumerate(("Swatch", "Hex", "Usage")):
    hdr[i].width = Inches(1.4) if i == 0 else Inches(4.6) if i == 2 else Inches(1.0)
    shade_cell(hdr[i], INK_PRIMARY)
    cell_margins(hdr[i], top=80, bottom=80, left=140, right=140)
    no_borders(hdr[i])
    para(hdr[i], txt, font=F_MONO, size=9, color=PAPER_BASE, bold=True, after=0)

for name, hexc, usage in palette:
    row = t.add_row().cells
    widths = [1.4, 1.0, 4.6]
    for c, w in zip(row, widths):
        c.width = Inches(w)
        cell_margins(c, top=70, bottom=70, left=140, right=140)
        no_borders(c)
    shade_cell(row[0], hexc)
    text_color = PAPER_BASE if hexc == INK_PRIMARY else INK_PRIMARY
    para(row[0], "  " + name, font=F_MONO, size=9, color=text_color, after=0)
    para(row[1], "#" + hexc, font=F_MONO, size=9, color=INK_PRIMARY, after=0)
    para(row[2], usage, font=F_BODY, size=10, color=INK_SECONDARY, after=0)

doc.add_page_break()

# ============ 4. TYPOGRAPHY ============
section_label(doc, "Section 04")
h1(doc, "Typography")

para(doc,
     "Three typefaces carry the system. Space Grotesk handles display and "
     "headlines with tight tracking (-0.025em), giving them a confident, "
     "geometric feel. Plus Jakarta Sans is the body face — warm, legible, and "
     "generous at small sizes. JetBrains Mono is reserved for labels, code, "
     "timestamps, and tool names, where its mechanical rhythm is a feature.",
     after=14)

for fname, size, weight_desc, sample_text in [
    ("Space Grotesk", 26, "Display · 500 weight · tight tracking",
     "What would you like to work on today?"),
    ("Plus Jakarta Sans", 13, "Body · 400 weight · 1.6 line-height",
     "Draft documents, review notifications, or organize your workspace."),
    ("JetBrains Mono", 10, "Labels · 400 weight · uppercase, wide tracking",
     "CONNECTED · GITHUB · list_directory · 14:22"),
]:
    section_label(doc, fname)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(sample_text)
    set_font(r, fname, size, INK_PRIMARY)
    p2 = doc.add_paragraph()
    p2.paragraph_format.space_after = Pt(10)
    r2 = p2.add_run(weight_desc)
    set_font(r2, F_MONO, 8, INK_MUTED)

doc.add_page_break()

# ============ 5. ARCHITECTURE ============
section_label(doc, "Section 05")
h1(doc, "Architecture")

para(doc,
     "Quill Cowork is organized into five layers. Each layer is replaceable "
     "independently. The frontend can be swapped for a native desktop shell "
     "without touching the backend. The provider layer admits additional "
     "model runtimes without changing the agent loop. New connectors are added "
     "as single Python files with a decorator.",
     after=14)

layers = [
    ("1", "Frontend", "Single-file HTML, Tailwind, WebSocket chat",
     "Reactive UI driven by connector manifests"),
    ("2", "API", "FastAPI — /chat, /connectors, /status, /vault/*",
     "REST and WebSocket interface"),
    ("3", "Agent Loop", "Provider-agnostic message pipeline",
     "Safety filter → tool dispatch → reply"),
    ("4", "Tools", "Decorator-based registration",
     "Auto-generated JSON schemas + UI manifests"),
    ("5", "Provider + Vault", "Ollama provider, AES-256-GCM vault",
     "Local inference, OS keychain credentials"),
]

for num, name, sub, note in layers:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    r1 = p.add_run(f"{num}   ")
    set_font(r1, F_MONO, 10, ACCENT_MINT, bold=True)
    r2 = p.add_run(name)
    set_font(r2, F_DISPLAY, 12, INK_PRIMARY, bold=True)
    p2 = doc.add_paragraph()
    p2.paragraph_format.left_indent = Inches(0.4)
    p2.paragraph_format.space_after = Pt(2)
    r3 = p2.add_run(sub)
    set_font(r3, F_MONO, 9, INK_SECONDARY)
    p3 = doc.add_paragraph()
    p3.paragraph_format.left_indent = Inches(0.4)
    p3.paragraph_format.space_after = Pt(10)
    r4 = p3.add_run(note)
    set_font(r4, F_BODY, 10, INK_MUTED, italic=True)

doc.add_paragraph()
section_label(doc, "Figure 5")
photo_placeholder(doc, "PHOTO PLACEHOLDER — Architecture diagram", height_in=2.6)

doc.add_page_break()

# ============ 6. SAFETY ============
section_label(doc, "Section 06")
h1(doc, "Safety Layers")

para(doc,
     "Quill Cowork runs an abliterated model — a language model whose internal "
     "refusal direction has been removed by weight-editing. We chose this "
     "deliberately: it produces a local assistant that does not moralize on "
     "benign tasks. But it also means the model itself provides no safety. "
     "Boundaries must come from the architecture around it.",
     after=10)

para(doc,
     "We implement four independent layers. Two are enforceable at the code "
     "level and cannot be bypassed by any prompt. Two are suggested — they "
     "constrain typical behavior but are not guarantees.",
     after=14)

lt = doc.add_table(rows=1, cols=4)
lt.autofit = False
hdr = lt.rows[0].cells
headers = ["Layer", "Mechanism", "Scope", "Enforceable?"]
widths = [1.2, 2.2, 2.0, 1.1]
for i, (h, w) in enumerate(zip(headers, widths)):
    hdr[i].width = Inches(w)
    shade_cell(hdr[i], INK_PRIMARY)
    cell_margins(hdr[i], top=70, bottom=70, left=120, right=120)
    no_borders(hdr[i])
    para(hdr[i], h, font=F_MONO, size=8.5, color=PAPER_BASE, bold=True, after=0)

rows = [
    ("L1", "Input filter",       "User message text",  "No"),
    ("L2", "Tool allowlist",     "Available actions",  "Yes"),
    ("L3", "Filesystem sandbox", "File access scope",  "Yes"),
    ("L4", "Confirmation gate",  "Write operations",   "Partial"),
]
for num, mech, scope, enf in rows:
    row = lt.add_row().cells
    for c, w in zip(row, widths):
        c.width = Inches(w)
        cell_margins(c, top=60, bottom=60, left=120, right=120)
        no_borders(c)
    enf_color = ACCENT_MINT if enf == "Yes" else INK_MUTED
    para(row[0], num, font=F_MONO, size=9.5, color=ACCENT_MINT, bold=True, after=0)
    para(row[1], mech, font=F_BODY, size=10, color=INK_PRIMARY, after=0)
    para(row[2], scope, font=F_BODY, size=10, color=INK_SECONDARY, after=0)
    para(row[3], enf, font=F_MONO, size=9, color=enf_color, after=0)

para(doc, "", after=6)

para(doc,
     "The enforceable layers bound the model's action space regardless of what "
     "it says. The suggested layers bound output but can be bypassed. Reliable "
     "safety for uncensored agents must therefore be built from enforceable "
     "layers only — prompts are defense-in-depth, not guarantees.",
     italic=True, after=6)

doc.add_page_break()

# ============ 7. ABSTRACT ============
section_label(doc, "Section 07")
h1(doc, "Paper Abstract")

para(doc,
     "The full research paper accompanying this design document is titled "
     "\"Quill-Cowork: Reactive Interfaces and Layered Safety for Local-First "
     "Agentic Assistants.\" Its abstract follows.",
     after=14)

at = doc.add_table(rows=1, cols=1)
at.autofit = False
ac = at.cell(0, 0)
ac.width = Inches(6.5)
shade_cell(ac, HINT_BG)
cell_margins(ac, top=200, left=240, bottom=200, right=240)
no_borders(ac)

p = ac.paragraphs[0]
p.paragraph_format.space_after = Pt(8)
r = p.add_run("ABSTRACT")
set_font(r, F_MONO, 9, INK_MUTED, bold=True)

p = ac.add_paragraph()
p.paragraph_format.space_after = Pt(8)
p.paragraph_format.line_spacing = 1.4
r = p.add_run(
    "Commercial agentic assistants such as Claude Cowork, GitHub Copilot "
    "Workspace, and OpenAI Operator have demonstrated that large language models "
    "can autonomously execute multi-step tasks on a user's behalf. However, these "
    "systems rely on cloud inference, transmit user data to remote servers, and "
    "embed safety alignment inside the model itself. We present Quill-Cowork, a "
    "local-first agentic coworker that runs entirely on consumer hardware, stores "
    "credentials in an AES-256-GCM vault backed by the operating system keychain, "
    "and connects to external services through a declarative connector interface. "
    "Quill-Cowork makes two contributions. First, we introduce a reactive UI "
    "architecture in which each connector declares its own interface metadata — "
    "widgets, quick actions, accent colors — allowing the frontend to rebuild "
    "itself dynamically as services are added or removed without any frontend "
    "code changes. Second, we present layered safety for uncensored models: we "
    "empirically demonstrate that system-prompt guardrails are insufficient to "
    "constrain abliterated language models, and propose a defense-in-depth "
    "architecture enforcing boundaries at the input-filter, tool-allowlist, "
    "filesystem-sandbox, and confirmation-gate layers instead."
)
set_font(r, F_BODY, 10.5, INK_SECONDARY)

p = ac.add_paragraph()
p.paragraph_format.space_after = Pt(0)
r = p.add_run(
    "We evaluate Quill-Cowork on a consumer AMD RX 7600 GPU (8 GB VRAM) using "
    "an abliterated Qwen3-4B model and document the design trade-offs of "
    "local-first autonomy. All code is released under the MIT license."
)
set_font(r, F_BODY, 10.5, INK_SECONDARY)

doc.add_paragraph()

p = doc.add_paragraph()
p.paragraph_format.space_after = Pt(4)
r1 = p.add_run("Keywords: ")
set_font(r1, F_MONO, 9, INK_MUTED, bold=True)
r2 = p.add_run(
    "local-first AI · agentic systems · Model Context Protocol · credential "
    "encryption · uncensored models · reactive user interfaces"
)
set_font(r2, F_BODY, 10, INK_SECONDARY, italic=True)

doc.add_paragraph()
section_label(doc, "Figures & Tables Index")

index_items = [
    ("Figure 1", "Full interface, desktop view"),
    ("Figure 2", "Sidebar detail"),
    ("Figure 3", "Conversation view with tool call"),
    ("Figure 4", "Input dock close-up"),
    ("Figure 5", "Architecture diagram"),
    ("Table 1",  "Safety layers and enforceability"),
]
for label, desc in index_items:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.left_indent = Inches(0.2)
    r1 = p.add_run(f"{label}   ")
    set_font(r1, F_MONO, 9, ACCENT_MINT, bold=True)
    r2 = p.add_run(desc)
    set_font(r2, F_BODY, 10, INK_SECONDARY)


doc.save("quill-cowork-design.docx")
print("Wrote quill-cowork-design.docx")
print("Location: D:/Quill-Cowork/design/quill-cowork-design.docx")