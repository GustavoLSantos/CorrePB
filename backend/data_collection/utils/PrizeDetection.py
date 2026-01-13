import re


def is_prize_text(text):
    """Detecta se um texto sugere tratar-se de prêmio/premiação.

    Mantém as heurísticas originais do scraper.
    """
    if not text:
        return False
    text_l = text.lower()

    # Palavras-chave diretas relacionadas a prêmios
    if re.search(r'\b(prêmio|premiação|premio|prize|award|prêmios|premiações|awards)\b', text_l):
        return True

    # Padrões como "lugar", "colocado", "classificado" com preço
    if re.search(r'\b(lugar|colocado|classificado|classificação|ranking|posição|podium|pódio)\b', text_l):
        return True

    # Padrões como "destinada a quantia", "será destinada", "distribuída da seguinte forma"
    if re.search(r'(destinada a quantia|será destinada|distribuída da seguinte forma)', text_l):
        return True

    # Padrões como "masculino e feminino", "prova de", "km" com preço
    if re.search(r'(masculino|feminino|prova de|km)', text_l) and re.search(r'R\$\s*[\d.,]+', text_l):
        return True

    return False


def entry_is_prize(entry, page_html: str) -> bool:
    """Decide se uma entrada de preço corresponde a premiação.

    entry: dict com keys 'raw','label','price' (pode ser None)
    page_html: string com HTML inteiro (usado para contexto)
    """
    raw = (entry.get('raw') or '').lower()
    label = (entry.get('label') or '')
    if is_prize_text(raw) or is_prize_text(label):
        return True

    price = entry.get('price')
    if price is None:
        return False
    try:
        pv = float(price)
    except Exception:
        return False

    # Constrói variantes de string comuns para corresponder como preços aparecem na página
    price_br = f"{pv:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    price_dot = f"{pv:.2f}"

    patterns = [
        rf"R\$\s*{re.escape(price_br)}",
        rf"R\$\s*{re.escape(price_dot)}",
        rf"{re.escape(price_br)}\s*reais",
        rf"{re.escape(price_dot)}\s*reais",
        rf"{re.escape(price_br)}",
        rf"{re.escape(price_dot)}",
    ]

    prize_context_re = re.compile(
        r"\b(prêmio|premiação|premio|prize|award|prêmios|premiações|awards|"
        r"lugar|colocado|classificado|classificação|posição|podium|pódio|"
        r"destinada a quantia|será destinada|distribuída da seguinte forma)\b",
        re.IGNORECASE
    )

    for pat in patterns:
        for m in re.finditer(pat, page_html, re.IGNORECASE):
            start = max(0, m.start() - 120)
            end = min(len(page_html), m.end() + 120)
            context = page_html[start:end]
            if prize_context_re.search(context):
                return True
    return False

