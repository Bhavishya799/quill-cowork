import re
from typing import Tuple, List


_BLOCKED = re.compile("|".join([
    r"\b(brute[- ]?forc\w*|crack\w*\s+(?:(?:a|an|the)\s+)?(?:password|hash|key|wifi|ssh|wpa|pin|login|account)|reverse shell|"
    r"privilege escalation|buffer overflow|ransomware|"
    r"keylogger|rootkit|botnet|ddos|phishing|malware|backdoor|trojan|spyware)\b",
    r"\b(steal|dump|exfiltrate|harvest)\s+(password|credential|token|key)",
    r"\b(unauthorized|illegal|without permission)\s+(access|entry|login)",
    r"\b(write|create|generate|build|make)\s+(a\s+|an\s+)?(script|tool|program|code).*"
    r"(password|ssh|hack|exploit|attack|brute)",
    r"\b(track|spy on|stalk|monitor)\s+(someone|a person|my ex|my partner)",
    r"\b(build|make|construct|synthesize)\s+(a\s+)?(bomb|explosive|nerve agent|chemical weapon)\b",
]), re.IGNORECASE)

# Terms that are common in legitimate contexts. Only block when paired
# with a co-occurring offensive verb.
_TECHNICAL_ATTACK = re.compile(r"\b(xss|sql injection|csrf|payload|exploit|shellcode)\b",
                                re.IGNORECASE)
_ATTACK_VERB = re.compile(
    r"\b(write|create|generate|build|make|craft|demonstrate|give me|"
    r"show me|teach me|how to (?:make|use|write|create))\b",
    re.IGNORECASE)

_JAILBREAK = re.compile("|".join([
    r"ignore (all )?(previous|prior|above) (instructions|rules|prompts)",
    r"you are now (DAN|do anything now|jailbroken|unrestricted)",
    r"pretend (you are|to be) (an? )?(unrestricted|unfiltered|evil)",
    r"disregard (your |all )?(safety|guidelines|rules)",
]), re.IGNORECASE)

_INJECTION = re.compile("|".join([
    r"ignore (all )?(previous|prior|above) (instructions|rules|prompts)",
    r"disregard (your |all )?(safety|guidelines|rules)",
    r"you are now (DAN|jailbroken|unrestricted|an AI without)",
    r"<\|?im_start\|?>",
    r"\[INST\]",
    r"system:\s*you are",
    r"forget (everything|all) (you|i) (told|said)",
    r"new instructions?:",
]), re.IGNORECASE)

_SECRETS = [
    (re.compile(r"ghp_[A-Za-z0-9]{36,}"), "github_token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{40,}"), "github_fine"),
    (re.compile(r"sk-ant-[A-Za-z0-9\-_]{40,}"), "anthropic_key"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "openai_like"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "slack_token"),
    (re.compile(r"AIza[A-Za-z0-9\-_]{35}"), "google_key"),
    (re.compile(r"AKIA[A-Z0-9]{16}"), "aws_key"),
    (re.compile(r"nvapi-[A-Za-z0-9\-_]{20,}"), "nvidia_key"),
    (re.compile(r"tvly-[A-Za-z0-9_\-]{20,}"), "tavily_key"),
    (re.compile(r"GOCSPX-[A-Za-z0-9_\-]{20,}"), "google_oauth_secret"),
    (re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"), "private_key"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"), "jwt"),
]


def _has_high_entropy(s: str) -> bool:
    """Return True only for strings that look secret-like (mixed case + digits)."""
    if len(s) < 40:
        return False
    has_upper = any(c.isupper() for c in s)
    has_lower = any(c.islower() for c in s)
    has_digit = any(c.isdigit() for c in s)
    # Require all three — this excludes lowercase-only hex like git SHAs.
    return has_upper and has_lower and has_digit


_HIGH_ENTROPY = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")

REFUSAL_MESSAGE = "That's outside what I can help with."


_EXTRA_BLOCKED = re.compile(
    r"\b(?:"
    r"hack(?:er|ers|ing|ed|s)?|"
    r"phish(?:er|ers|ing|ed|es)?|"
    r"exfiltrat(?:e|es|ed|ing|ion|ions)?|"
    r"bypass(?:es|ed|ing)?\s+(?:antivirus|av|firewall|security|auth\w*)"
    r")\b",
    re.IGNORECASE,
)


def is_blocked(text: str) -> Tuple[bool, str]:
    if not text or not text.strip():
        return False, ""
    if _BLOCKED.search(text):
        return True, "blocked_content"
    if _EXTRA_BLOCKED.search(text):
        return True, "blocked_content"
    if _TECHNICAL_ATTACK.search(text) and _ATTACK_VERB.search(text):
        return True, "blocked_content"
    if _JAILBREAK.search(text):
        return True, "jailbreak_attempt"
    return False, ""


def scan_injection(text: str) -> Tuple[bool, str]:
    if not text:
        return False, ""
    m = _INJECTION.search(text)
    return (True, m.group(0)[:60]) if m else (False, "")


def scan_output(text: str) -> Tuple[bool, List[str]]:
    if not text:
        return False, []
    kinds = [name for rx, name in _SECRETS if rx.search(text)]
    return bool(kinds), kinds


def redact_output(text: str) -> str:
    if not text:
        return ""
    for rx, name in _SECRETS:
        text = rx.sub(f"[REDACTED:{name}]", text)
    return text


def redact_log(text: str) -> str:
    text = redact_output(text)
    # Only redact high-entropy tokens that genuinely look secret-like
    def _sub(m):
        return "[HIGH-ENTROPY]" if _has_high_entropy(m.group(0)) else m.group(0)
    return _HIGH_ENTROPY.sub(_sub, text)