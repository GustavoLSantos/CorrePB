import json
import os
from datetime import datetime
from pymongo import MongoClient
from bson import ObjectId

MONGO_URI = "mongodb://admin:password@127.0.0.1:27018/?authSource=admin"
DB_NAME = "correpb"
COLLECTION_NAME = "eventos"
CAMINHO_SAIDA = "./eventos_compilados.json"

MESES = {
    1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril', 5: 'Maio', 6: 'Junho',
    7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
}

def formatar_data_ptbr(data_obj):
    if not data_obj:
        return ""
    try:
        if isinstance(data_obj, str):
            if 'T' in data_obj:
                data_obj = datetime.fromisoformat(data_obj)
            else:
                return data_obj
        
        dia = data_obj.day
        mes = MESES[data_obj.month]
        ano = data_obj.year
        return f"{dia} de {mes} de {ano}"
    except Exception:
        return str(data_obj)

def transformar_evento(evento_mongo):
    datas = evento_mongo.get('datas_realizacao', [])
    data_formatada = ""
    if datas and isinstance(datas, list) and len(datas) > 0:
        data_formatada = formatar_data_ptbr(datas[0])
    
    dist = evento_mongo.get('distancias', [])
    if isinstance(dist, str):
        dist = [dist]
    
    data_col = evento_mongo.get('data_coleta')
    if isinstance(data_col, datetime):
        data_col = data_col.isoformat() + "Z"

    preco_raw = evento_mongo.get('preco', '')
    lista_precos = []
    
    if preco_raw and isinstance(preco_raw, str):
        lista_precos = [p.strip() for p in preco_raw.split(';') if p.strip()]

    return {
        "_id": str(evento_mongo.get('_id')),
        "nome_evento": evento_mongo.get('nome_evento', ''),
        "url_inscricao": evento_mongo.get('url_inscricao', ''),
        "url_imagem": evento_mongo.get('url_imagem', ''),
        "data_realizacao": data_formatada,
        "cidade": evento_mongo.get('cidade', ''),
        "estado": evento_mongo.get('estado', 'PB'),
        "data_coleta": data_col,
        "distancias": dist,
        "organizador": evento_mongo.get('organizador', ''),
        "categorias": [],
        "preco": preco_raw, 
        "lista_precos": lista_precos
    }

def gerar_json_customizado():
    
    client = MongoClient(MONGO_URI)
    try:
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
        
        cursor = collection.find({})
        
        eventos_processados = []
        for doc in cursor:
            novo_doc = transformar_evento(doc)
            eventos_processados.append(novo_doc)
            
        os.makedirs(os.path.dirname(CAMINHO_SAIDA), exist_ok=True)
        
        with open(CAMINHO_SAIDA, 'w', encoding='utf-8') as f:
            json.dump(eventos_processados, f, ensure_ascii=False, indent=2)
                    
    finally:
        client.close()

if __name__ == "__main__":
    gerar_json_customizado()