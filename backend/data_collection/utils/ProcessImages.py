import os
import logging
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_CONTENT_TYPE_PARA_EXT = {
    'image/jpeg': '.jpg',
    'image/jpg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
}

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}


def _extensao_da_url(url: str) -> str:
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    return ext if ext and len(ext) <= 5 and ext[1:].isalpha() else ''


def _chave_s3(evento_id: str, url: str) -> str:
    ext = _extensao_da_url(url) or '.jpg'
    return f"images/{evento_id}{ext}"


def _ja_existe_no_s3(s3_client, bucket: str, chave: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=chave)
        return True
    except Exception:
        return False


def _baixar_e_fazer_upload(url: str, s3_client, bucket: str, chave: str, timeout: int = 20) -> bool:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()

        content_type = resp.headers.get('Content-Type', 'image/jpeg').split(';')[0].strip()

        s3_client.put_object(
            Bucket=bucket,
            Key=chave,
            Body=resp.content,
            ContentType=content_type,
        )
        logger.info(f"Upload: {chave} [{content_type}]")
        return True
    except requests.RequestException as e:
        logger.warning(f"Falha ao baixar imagem ({url}): {e}")
        return False
    except Exception as e:
        logger.warning(f"Falha ao fazer upload ({chave}): {e}")
        return False


def processar_imagens_para_s3(
    eventos: list,
    s3_client,
    bucket: str,
    dominio_estatico: str,
) -> list:
    """
    Percorre a lista de eventos, baixa imagens ausentes no S3 e
    substitui url_imagem pelo domínio estático configurado.

    Eventos sem url_imagem ou com falha de download são mantidos inalterados.
    Retorna a lista de eventos modificada in-place.
    """
    total_com_imagem = sum(1 for e in eventos if e.get('url_imagem'))
    substituidos = 0
    ja_no_s3 = 0
    falhas = 0

    print(f"Processando imagens de {total_com_imagem} eventos...")

    for evento in eventos:
        url_original = evento.get('url_imagem') or ''
        if not url_original:
            continue

        evento_id = str(evento.get('_id', ''))
        if not evento_id:
            continue

        chave = _chave_s3(evento_id, url_original)

        if _ja_existe_no_s3(s3_client, bucket, chave):
            ja_no_s3 += 1
        else:
            ok = _baixar_e_fazer_upload(url_original, s3_client, bucket, chave)
            if not ok:
                falhas += 1
                continue

        evento['url_imagem'] = f"{dominio_estatico.rstrip('/')}/{chave}"
        substituidos += 1

    print(f"  Substituidas: {substituidos}")
    print(f"  Ja no S3 (reutilizadas): {ja_no_s3}")
    print(f"  Falhas: {falhas}")

    return eventos
