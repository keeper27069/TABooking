def status_icon(status: str) -> str:
    s = (status or "").upper().strip()
    if "KELDI" in s:
        return "✅"
    elif "KELMADI" in s or "BEKOR" in s or "RAD" in s:
        return "❌"
    elif "TASDIQ" in s:
        return "🔵"
    elif "YANGI" in s:
        return "🟡"
    return "⚪️"
