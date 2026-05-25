import re
from typing import Any


def parse_price_str(text: Any) -> float | None:
    if not text:
        return None
    s = re.sub(r'[^\d.,]', '', str(text))
    if not s:
        return None

    if '.' in s and ',' in s:
        s = s.replace('.', '').replace(',', '.')
    elif '.' in s and len(s.split('.')[-1]) != 2:
        s = s.replace('.', '')
    s = s.replace(',', '.')

    try:
        return float(s)
    except Exception:
        return None


def fmt_entry(e: dict[str, Any]) -> dict[str, Any]:
    v = e.get('price')
    tax = e.get('tax')
    label = (e.get('label') or '').strip()

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


def formatar_lista_precos(precos_entries: list[Any] | None, preco_raw: str | None) -> list[str]:
    lista_precos: list[str] = []

    entries = precos_entries or []

    if isinstance(entries, str) and entries.strip():
        import json
        try:
            loaded = json.loads(entries)
            if isinstance(loaded, list):
                entries = loaded
        except Exception:
            entries = []

    if entries and isinstance(entries, list):
        for p in entries:
            try:
                if isinstance(p, dict):
                    formatted = p.get('formatted') or p.get('raw') or ''
                    if not formatted and (p.get('price') is not None or p.get('label')):
                        try:
                            formatted = fmt_entry(p).get('formatted', '')
                        except Exception:
                            formatted = ''

                    if formatted:
                        m = re.search(r"R\$\s*[\d.,]+(?:.*?taxa.*)?", formatted)
                        if m:
                            price_part = m.group(0).strip()
                            label_part = formatted[:m.start()].strip(' -—–')
                            if label_part:
                                lista_precos.append(f"{label_part.upper()} — {price_part}")
                            else:
                                lista_precos.append(price_part)
                            continue
                        else:
                            lista_precos.append(formatted)
                            continue

                    label = (p.get('label') or '').strip()
                    price_val = p.get('price')
                    if price_val is not None:
                        try:
                            price_s = fmt_entry({'price': price_val}).get('formatted', '')
                        except Exception:
                            try:
                                price_s = f"R$ {float(price_val):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
                            except Exception:
                                price_s = str(price_val)
                        if label:
                            lista_precos.append(f"{label.upper()} — {price_s}")
                        else:
                            lista_precos.append(price_s)
                        continue

                    raw = p.get('raw') or ''
                    if raw:
                        m = re.search(r"R\$\s*[\d.,]+", raw)
                        if m:
                            price_part = m.group(0).strip()
                            label_part = raw.replace(m.group(0), '').strip(' -—|')
                            if label_part:
                                lista_precos.append(f"{label_part.upper()} — {price_part}")
                            else:
                                lista_precos.append(price_part)
                        else:
                            lista_precos.append(raw)

                else:
                    s = str(p).strip()
                    if '|' in s:
                        parts = [part.strip() for part in s.split('|', 1)]
                        if len(parts) == 2:
                            price_part, label_part = parts[0], parts[1]
                            lista_precos.append(f"{label_part.upper()} — {price_part}")
                            continue
                    m = re.search(r"R\$\s*[\d.,]+", s)
                    if m:
                        price_part = m.group(0).strip()
                        label_part = s.replace(m.group(0), '').strip(' -—|')
                        if label_part:
                            lista_precos.append(f"{label_part.upper()} — {price_part}")
                        else:
                            lista_precos.append(price_part)
                    else:
                        lista_precos.append(s)
            except Exception:
                continue

        seen: set[str] = set()
        deduped: list[str] = []
        for item in lista_precos:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        lista_precos = deduped
    else:
        if preco_raw and isinstance(preco_raw, str):
            lista_precos = [p.strip() for p in preco_raw.split(';') if p.strip()]

    return lista_precos
