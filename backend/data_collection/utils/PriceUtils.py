import re


def parse_price_str(text):
    """
    Normaliza uma string de preço e retorna float ou None.

    Lida com separadores de milhares (.) e decimais (, ou .).
    Exemplos: '1.234,56' -> 1234.56, '89,90' -> 89.9, '50' -> 50.0
    """
    if not text:
        return None
    s = re.sub(r'[^\d.,]', '', str(text))
    if not s:
        return None

    # Se ambos separadores presentes, assume '.' para milhares e ',' para decimais
    if '.' in s and ',' in s:
        s = s.replace('.', '').replace(',', '.')
    # Se apenas '.' presente e último grupo não tem 2 dígitos, provavelmente é separador de milhares
    elif '.' in s and len(s.split('.')[-1]) != 2:
        s = s.replace('.', '')
    # Substitui vírgula decimal por ponto
    s = s.replace(',', '.')

    try:
        return float(s)
    except Exception:
        return None


# Formatação padronizada de entradas de preço
def fmt_entry(e):
    """Formata uma entrada de preço para exibição.

    Entrada: dict com chaves possivelmente 'label', 'price', 'tax', 'formatted', 'raw'.
    Retorna dict com 'label', 'price', 'tax', 'formatted', 'raw'.
    """
    v = e.get('price')
    tax = e.get('tax')
    label = (e.get('label') or '').strip()

    # Se não há preço numérico, usa o formatted existente ou uma mensagem padrão
    if v is None:
        return {
            'label': label or None,
            'price': None,
            'tax': float(tax) if tax is not None else None,
            'formatted': e.get('formatted', 'Valor não encontrado'),
            'raw': e.get('raw')
        }

    try:
        price_s = f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        price_s = f"R$ {v}"

    if tax is not None:
        try:
            tax_s = f"(+{tax:,.2f} taxa)".replace(',', 'X').replace('.', ',').replace('X', '.')
        except Exception:
            tax_s = f"(+{tax} taxa)"
        if label:
            formatted = f"{label} — {price_s} {tax_s}"
        else:
            formatted = f"{price_s} {tax_s}"
    else:
        if label:
            formatted = f"{label} — {price_s}"
        else:
            formatted = f"{price_s}"

    return {
        'label': label or None,
        'price': float(v),
        'tax': float(tax) if tax is not None else None,
        'formatted': formatted,
        'raw': e.get('raw')
    }
