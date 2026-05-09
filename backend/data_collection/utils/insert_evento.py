import os
import sys
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, '../..'))
sys.path.insert(0, backend_dir)

import json
import re

import certifi
from dotenv import load_dotenv
from data_collection.evento_de_corrida import EventoDeCorrida
from pymongo import MongoClient

load_dotenv(os.path.abspath(os.path.join(current_dir, '../..', '.env')))

MONGO_URI = os.getenv('MONGODB_REMOTE_URI') or os.getenv('MONGODB_URI')
DB_NAME = os.getenv('MONGODB_REMOTE_DB_NAME') or os.getenv('MONGODB_DB_NAME') or 'correpb'


def perguntar(label: str, obrigatorio: bool = False) -> str:
    sufixo = '' if obrigatorio else ' (opcional, Enter para pular)'
    while True:
        valor = input(f"  {label}{sufixo}: ").strip()
        if valor or not obrigatorio:
            return valor
        print("  Campo obrigatório. Tente novamente.")


def parse_datas(data_str: str) -> list:
    datas = []
    for part in data_str.split(','):
        part = part.strip()
        try:
            datas.append(datetime.strptime(part, '%d/%m/%Y'))
        except ValueError:
            print(f"  Data inválida ignorada: '{part}'")
    return datas


def gerar_id(db) -> str:
    now = datetime.now()
    prefix = f"{now.year}{now.month:02d}"
    last = db.eventos.find_one({'_id': {'$regex': f'^{prefix}'}}, sort=[('_id', -1)])
    if last and isinstance(last.get('_id'), str) and len(last['_id']) >= len(prefix) + 4:
        try:
            last_seq = int(last['_id'][-4:])
        except Exception:
            last_seq = 0
    else:
        last_seq = 0
    return f"{prefix}{(last_seq + 1):04d}"


def parse_preco_entry(texto: str) -> dict:
    """Converte 'LABEL - R$ XX,XX' em dict estruturado."""
    match = re.search(r'R\$\s*([\d.,]+)', texto)
    if match:
        price_str = match.group(1).replace('.', '').replace(',', '.')
        price = float(price_str)
        formatted = f"R$ {match.group(1)}"
        label = texto[:match.start()].rstrip(' -–—').strip()
    else:
        price = 0.0
        formatted = texto
        label = texto
    return {'label': label, 'price': price, 'formatted': formatted}


def coletar_precos() -> list:
    """Coleta preços estruturados. Aceita JSON array ou entrada linha a linha."""
    print("\n  Preços detalhados (opcional, Enter para pular):")
    print("  Pode colar um JSON array ou digitar um por linha (linha vazia para encerrar)")
    primeira = input("  > ").strip()
    if not primeira:
        return []

    # Tenta interpretar como JSON array
    if primeira.startswith('['):
        try:
            items = json.loads(primeira)
            return [parse_preco_entry(str(item)) for item in items]
        except json.JSONDecodeError:
            pass

    # Entrada linha a linha
    entries = [parse_preco_entry(primeira)]
    while True:
        linha = input("  > ").strip()
        if not linha:
            break
        entries.append(parse_preco_entry(linha))
    return entries


def coletar_dados() -> dict:
    print("\n--- Novo evento ---\n")

    nome = perguntar("Nome do evento", obrigatorio=True)

    while True:
        data_str = perguntar("Data(s) DD/MM/YYYY (múltiplas separadas por vírgula)", obrigatorio=True)
        datas = parse_datas(data_str)
        if datas:
            break
        print("  Nenhuma data válida. Tente novamente.")

    cidade    = perguntar("Cidade", obrigatorio=True)
    distancia = perguntar("Distância(s) ex: 5K, 10K", obrigatorio=True)
    horario   = perguntar("Horário de largada ex: 07:00")
    link      = perguntar("Link de inscrição")
    imagem    = perguntar("URL da imagem")
    edital    = perguntar("Link do edital")
    organizador = perguntar("Organizador")
    preco       = perguntar("Preço resumido ex: A partir de R$119,90")

    precos_entries = coletar_precos()

    return {
        'nome': nome,
        'datas': datas,
        'cidade': cidade,
        'distancia': distancia,
        'horario': horario or None,
        'link': link or None,
        'imagem': imagem or None,
        'edital': edital or None,
        'organizador': organizador,
        'preco': preco or None,
        'precos_entries': precos_entries,
    }


def confirmar(dados: dict) -> bool:
    print("\n--- Resumo ---")
    print(f"  Nome:        {dados['nome']}")
    print(f"  Data(s):     {', '.join(d.strftime('%d/%m/%Y') for d in dados['datas'])}")
    print(f"  Cidade:      {dados['cidade']}")
    print(f"  Distância:   {dados['distancia']}")
    if dados['horario']:    print(f"  Horário:     {dados['horario']}")
    if dados['organizador']: print(f"  Organizador: {dados['organizador']}")
    if dados['link']:       print(f"  Link:        {dados['link']}")
    if dados['imagem']:     print(f"  Imagem:      {dados['imagem']}")
    if dados['edital']:     print(f"  Edital:      {dados['edital']}")
    if dados['preco']:      print(f"  Preço:       {dados['preco']}")
    if dados['precos_entries']:
        print(f"  Preços ({len(dados['precos_entries'])} entradas):")
        for p in dados['precos_entries']:
            print(f"    - {p['label']} — {p['formatted']}")
    print()
    resposta = input("Confirmar inserção? (s/N): ").strip().lower()
    return resposta == 's'


def main():
    try:
        client = MongoClient(MONGO_URI, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=10000)
        client.admin.command('ping')
        db = client[DB_NAME]
        print("MongoDB conectado.")
    except Exception as e:
        print(f"Erro ao conectar ao MongoDB: {e}")
        sys.exit(1)

    while True:
        dados = coletar_dados()

        existente = db.eventos.find_one({'nome_evento': dados['nome']})
        if existente:
            print(f"\nEvento já existe no banco: '{dados['nome']}' (id: {existente['_id']})")
        elif confirmar(dados):
            evento = EventoDeCorrida(
                nome_evento=dados['nome'],
                datas_realizacao=dados['datas'],
                cidade=dados['cidade'],
                estado='PB',
                organizador=dados['organizador'],
                site_coleta='manual',
                data_coleta=datetime.now(),
                distancias=dados['distancia'],
                horario=dados['horario'],
                url_inscricao=dados['link'],
                url_imagem=dados['imagem'],
                link_edital=dados['edital'],
                preco=dados['preco'],
                precos_entries=dados['precos_entries'],
            )
            evento_dict = evento.to_dict()
            evento_dict['_id'] = gerar_id(db)
            db.eventos.insert_one(evento_dict)
            print(f"\nEvento inserido! id: {evento_dict['_id']}")
        else:
            print("\nInserção cancelada.")

        print()
        continuar = input("Inserir outro evento? (s/N): ").strip().lower()
        if continuar != 's':
            break

    print("Encerrando.")


if __name__ == '__main__':
    main()
