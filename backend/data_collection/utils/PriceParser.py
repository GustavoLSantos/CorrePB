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

