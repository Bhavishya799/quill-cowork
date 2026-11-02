import sys
import json
import httpx
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(".")
backend = root / "backend"

# ==========================================
# 1. Create AGENTS.md from .cursorrules
# ==========================================
cursorrules_path = root / ".cursorrules"
agents_path = root / "AGENTS.md"
if cursorrules_path.exists():
    agents_path.write_text(cursorrules_path.read_text(encoding="utf-8"), encoding="utf-8")
    print("[+] Created AGENTS.md from .cursorrules")

# ==========================================
# 2. Create CITATION.cff
# ==========================================
citation_content = """cff-version: 1.2.0
message: "If you use this software, please cite it as below."
authors:
  - family-names: "Agarwal"
    given-names: "Bhavishya"
title: "Quill-Cowork"
version: 0.3.0
date-released: "2026-10-31"
url: "https://github.com/Bhavishya799/quill-cowork"
"""
(root / "CITATION.cff").write_text(citation_content, encoding="utf-8")
print("[+] Created CITATION.cff")

# ==========================================
# 3. Append FAQ to README.md
# ==========================================
readme_path = root / "README.md"
readme_content = readme_path.read_text(encoding="utf-8")

if "## FAQ" not in readme_content:
    faq_content = """
## FAQ

**Q: Does Quill-Cowork send data to the cloud?**
A: No. Everything runs locally on your machine. The AI models run via Ollama on your local GPU/CPU. No accounts, no servers, no telemetry. Your files, emails, and credentials never leave your computer.

**Q: What is the advantage of the Rust core?**
A: The Rust binary (`quill_core`) handles heavy I/O, codebase indexing, and tool routing. This offloads string parsing and regex matching from Python to a compiled language, making file operations and message routing near-instant.

**Q: Can I use this on an 8GB GPU?**
A: Yes. Quill-Cowork is optimized for 8GB cards (like the RX 7600 or RTX 3060). By using `q8_0` KV cache quantization and Flash Attention, you can run a 16K context window comfortably.

**Q: How does the calendar automation work?**
A: A background Python daemon watches your Gmail every 60 seconds. If it detects an email with a meeting time, it uses a local AI model to extract the details, creates a Google Calendar event, and replies to the email confirming the action.

**Q: Is this safe to use?**
A: The app runs an abliterated (uncensored) model and has access to your filesystem, email, and GitHub. It is designed for single-user, trusted-machine use. Never expose it to the public internet without enabling the built-in web auth (L11).
"""
    readme_path.write_text(readme_content + faq_content, encoding="utf-8")
    print("[+] Appended SEO-optimized FAQ to README.md")

# ==========================================
# 4. Generate Social Preview Image
# ==========================================
print("[*] Generating social_preview.png...")
img = Image.new('RGB', (1280, 640), color = '#0D0C09')
d = ImageDraw.Draw(img)

try:
    # Try to load a default Windows font
    title_font = ImageFont.truetype("C:\\Windows\\Fonts\\segoeuib.ttf", 80)
    subtitle_font = ImageFont.truetype("C:\\Windows\\Fonts\\segoeui.ttf", 36)
except:
    title_font = ImageFont.load_default()
    subtitle_font = ImageFont.load_default()

# Draw Text
d.text((100, 220), "Quill-Cowork", font=title_font, fill="#F0E9CE")
d.text((100, 320), "Local-first Hybrid Python/Rust AI Agent", font=subtitle_font, fill="#807A6A")
d.text((100, 380), "16K Context • Semantic Search • Calendar Automation", font=subtitle_font, fill="#807A6A")

# Draw a visual accent bar
d.rectangle([100, 180, 400, 190], fill="#C98A2B")

img.save(root / "social_preview.png")
print("[+] Generated social_preview.png (Please upload this manually to GitHub Settings)")

# ==========================================
# 5. Update GitHub Repo Metadata
# ==========================================
print("\n[*] Updating GitHub Repository Description and Topics...")

# Add backend to path to import vault
sys.path.insert(0, str(backend))
try:
    from vault import vault
    token = vault.get_safe("GITHUB_PERSONAL_ACCESS_TOKEN")
except Exception as e:
    token = ""
    print(f"[-] Could not load vault: {e}")

if not token:
    print("[-] GITHUB_PERSONAL_ACCESS_TOKEN not found in vault.")
    print("    Run: python vault.py set GITHUB_PERSONAL_ACCESS_TOKEN <token> --sensitive")
else:
    api_url = "https://api.github.com/repos/Bhavishya799/quill-cowork"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    payload = {
        "description": "A local-first, hybrid Python/Rust AI agent with 16K context support for Ollama. Features automated codebase indexing, semantic search, email-to-calendar automation, and a global hotkey vision overlay.",
        "topics": [
            "local-llm", "ollama", "rust-ffi", "ai-agents", "semantic-search", 
            "python", "fastapi", "desktop-automation", "gmail-api", "google-calendar", 
            "rag", "local-first", "privacy", "cursor-rules", "gemini", "abliterated"
        ]
    }
    
    r = httpx.patch(api_url, headers=headers, json=payload, timeout=20)
    if r.status_code == 200:
        print("[+] Successfully updated GitHub Description and Topics!")
    else:
        print(f"[-] Failed to update GitHub metadata: {r.status_code} - {r.text}")

print("\n" + "="*50)
print("OPTIMIZATION COMPLETE")
print("="*50)