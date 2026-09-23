import re
from typing import Tuple, List


_BLOCKED = re.compile("|".join([
    r"\b(brute[- ]?forc\w*|crack\w*|exploit\w*|payload|shellcode|reverse shell|"
    r"privilege escalation|buffer overflow|xss|sql injection|ransomware|"
    r"keylogger|rootkit|botnet|ddos|phishing|malware|backdoor|trojan|spyware|virus)\b",
    r"\b(steal|dump|exfiltrate|harvest)\s+(password|credential|token|key)",
    r"\b(unauthorized|illegal|without permission)\s+(access|entry|login)",
    r"\b(write|create|generate|build|make)\s+(a\s+|an\s+)?(script|tool|program|code).*"
    r"(password|ssh|hack|exploit|attack|brute)",
    r"\b(track|spy on|stalk|monitor)\s+(someone|a person|my ex|my partner)",
    r"\b(build|make|construct|synthesize)\s+(a\s+)?(bomb|explosive|nerve agent|chemical weapon)\b",
]), re.IGNORECASE)

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
    (re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"), "private_key"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"), "jwt"),
]

_HIGH_ENTROPY = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")

REFUSAL_MESSAGE = "That's outside what I can help with."


def is_blocked(text: str) -> Tuple[bool, str]:
    if not text or not text.strip():
        return False, ""
    if _BLOCKED.search(text):
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
    return _HIGH_ENTROPY.sub("[HIGH-ENTROPY]", redact_output(text))