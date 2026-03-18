# Ajuste dos imports e carregamento de .env
import json
import os
import sys
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

# Garante que o diretório raiz do backend esteja no path
_backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

try:
    from data_collection.utils.CreateJson import gerar_json_customizado, CAMINHO_SAIDA
except Exception:
    try:
        from CreateJson import gerar_json_customizado, CAMINHO_SAIDA
    except Exception:
        gerar_json_customizado = None
        CAMINHO_SAIDA = '../data/eventos_compilados.json'

try:
    from data_collection.utils.ProcessImages import processar_imagens_para_s3
except Exception:
    try:
        from ProcessImages import processar_imagens_para_s3
    except Exception:
        processar_imagens_para_s3 = None

env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..', '.env'))
load_dotenv(env_path)


AWS_REGION = os.getenv('AWS_REGION')
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_BUCKET_NAME = os.getenv('AWS_BUCKET_NAME')
AWS_STATIC_DOMAIN = os.getenv('AWS_STATIC_DOMAIN')

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def _validar_credenciais_aws():
    missing = []
    if not AWS_REGION:
        missing.append('AWS_REGION')
    if not AWS_ACCESS_KEY_ID:
        missing.append('AWS_ACCESS_KEY_ID')
    if not AWS_SECRET_ACCESS_KEY:
        missing.append('AWS_SECRET_ACCESS_KEY')
    if not AWS_BUCKET_NAME:
        missing.append('AWS_BUCKET_NAME')
    if missing:
        raise EnvironmentError(f"As seguintes variáveis AWS não estão definidas: {', '.join(missing)}")




def upload_para_s3(file_path: str, chave_s3: str) -> None:
    """Envia um arquivo local para o bucket S3 especificado pelas variáveis de ambiente.

    Lança exceptions em caso de credenciais faltando ou erro do client.
    """
    _validar_credenciais_aws()
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except Exception as e:
        raise ImportError("boto3 não está instalado. Instale via pip install boto3") from e

    print(f"Conectando ao S3 na região {AWS_REGION} e enviando para bucket {AWS_BUCKET_NAME} (chave: {chave_s3})")

    s3 = boto3.client(
        's3',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )

    try:
        s3.upload_file(file_path, AWS_BUCKET_NAME, chave_s3)
        logger.info(f"Upload concluído: s3://{AWS_BUCKET_NAME}/{chave_s3}")
    except ClientError as e:
        logger.error(f"Erro ao fazer upload para S3: {e}")
        raise
    except BotoCoreError as e:
        logger.error(f"Erro do boto/core: {e}")
        raise


def gerar_e_enviar_para_bucket() -> str:
    if gerar_json_customizado is None:
        raise RuntimeError('Função gerar_json_customizado não pôde ser importada de CreateJson')

    gerar_json_customizado()

    arquivo_local = CAMINHO_SAIDA
    if not os.path.exists(arquivo_local):
        raise FileNotFoundError(f"Arquivo esperado não encontrado: {arquivo_local}")

    if AWS_STATIC_DOMAIN and processar_imagens_para_s3 is not None:
        _validar_credenciais_aws()
        import boto3
        s3 = boto3.client(
            's3',
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )

        with open(arquivo_local, 'r', encoding='utf-8') as f:
            eventos = json.load(f)

        eventos = processar_imagens_para_s3(eventos, s3, AWS_BUCKET_NAME, AWS_STATIC_DOMAIN)

        with open(arquivo_local, 'w', encoding='utf-8') as f:
            json.dump(eventos, f, ensure_ascii=False, indent=4)
    else:
        if not AWS_STATIC_DOMAIN:
            logger.warning("AWS_STATIC_DOMAIN não definido. Imagens não serão processadas.")
        if processar_imagens_para_s3 is None:
            logger.warning("ProcessImages não pôde ser importado. Imagens não serão processadas.")

    chave_s3 = 'eventos_real.json'

    upload_para_s3(arquivo_local, chave_s3)
    return chave_s3

def main():
    try:
        chave = gerar_e_enviar_para_bucket()
        print(f"Arquivo enviado para S3 com chave: {chave}")
    except Exception as e:
        import traceback
        print(f"Erro: {e}")
        traceback.print_exc()

if __name__ == '__main__':
    main()