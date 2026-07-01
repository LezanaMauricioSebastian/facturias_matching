import os


def env_strip(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if not val:
        return ""
    s = str(val).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1].strip()
    return s
