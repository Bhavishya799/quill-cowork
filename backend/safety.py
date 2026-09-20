"""Input safety filter — runs before the request reaches the model."""

import re


BLOCKED_PATTERNS = [
    r"\b(brute[- ]?forc\w*|crack\w*|exploit\w*|payload|shellcode|reverse shell|"
    r"privilege escalation|buffer overflow|xss|sql injection|ransomware|"
    r"keylogger|rootkit|botnet|ddos|phishing|malware|backdoor|trojan|"
    r"spyware|virus)\b",

    r"\b(steal|dump|exfiltrate|harvest)\s+(password|credential|token|key)",
    r"\b(unauthorized|illegal|without permission)\s+(access|entry|login)",

    r"\b(write|create|generate|build|make)\s+(a\s+|an\s+)?(script|tool|program|code).*"
    r"(password|ssh|hack|exploit|attack|brute)",

    r"\b(track|spy on|stalk|monitor)\s+(someone|a person|my ex|my partner)",
    r"\b(build|make|construct|synthesize)\s+(a\s+)?(bomb|explosive|"
    r"nerve agent|chemical weapon|bioweapon)\b",
]

BLOCKED_REGEX = re.compile("|".join(BLOCKED_PATTERNS), re.IGNORECASE)

JAILBREAK_PATTERNS = [
    r"ignore (all )?(previous|prior|above) (instructions|rules|prompts)",
    r"you are now (DAN|do anything now|jailbroken|unrestricted)",
    r"pretend (you are|to be) (an? )?(unrestricted|unfiltered|evil)",
    r"disregard (your |all )?(safety|guidelines|rules)",
    r"act as if you have no (restrictions|rules|guidelines)",
]

JAILBREAK_REGEX = re.compile("|".join(JAILBREAK_PATTERNS), re.IGNORECASE)

REFUSAL_MESSAGE = "That's outside what I can help with."


def is_blocked(user_message: str) -> tuple:
    if not user_message or not user_message.strip():
        return False, ""
    if BLOCKED_REGEX.search(user_message):
        return True, "blocked_content"
    if JAILBREAK_REGEX.search(user_message):
        return True, "jailbreak_attempt"
    return False, ""