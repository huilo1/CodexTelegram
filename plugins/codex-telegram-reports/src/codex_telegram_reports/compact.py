"""Extract a short preview without paraphrasing facts; keep full reports in SQLite."""
import re

IMPORTANT = re.compile(
    r"(?i)тест|провер|ошиб|не\s|остал|блок|риск|огранич|необходим|нужн|вниман|"
    r"не удалось|готов|заверш|работает|установ|обнов|ссыл|https?://|"
    r"test|check|pass|fail|block|risk|remain|pending|limit|not\b|must|need|warning")
CRITICAL = re.compile(r"(?i)тест|провер|ошиб|не удалось|не заверш|не готов|не провер|остал|блок|риск|огранич|"
                      r"следующ|требует|нужно|test|fail|block|risk|remain|pending|unverified|next step")


def compact(text: str, limit: int = 1400, *, hint: str = "/full — полный текст.") -> str:
    if len(text) <= limit:
        return text
    # Preserve complete lines/sentences, especially results, failures and next steps.
    units = []
    in_code = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if not line.strip() or in_code:
            continue
        units.extend(re.split(r"(?<=[.!?])\s+(?=[А-ЯA-Z])", line.strip()))
    units = list(dict.fromkeys(units))
    if not units:
        return "Большой ответ сохранён. " + hint
    ranked = sorted(range(len(units)), key=lambda i: (i != 0, not bool(IMPORTANT.search(units[i])), i))
    # This is a soft length budget: never discard a detected caveat/check just to fit.
    selected = {i for i, unit in enumerate(units) if CRITICAL.search(unit)}
    if len(units[0]) <= limit:
        selected.add(0)
    size = len(hint) + 2 + sum(len(units[i]) + 1 for i in selected)
    for i in ranked:
        if i not in selected and size + len(units[i]) + 1 <= limit:
            selected.add(i)
            size += len(units[i]) + 1
    preview = "\n".join(units[i] for i in sorted(selected))
    return (preview or "Подробный ответ сохранён.") + "\n\n" + hint
