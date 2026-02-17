import json
import os
import sys
from datetime import datetime
from pymongo import MongoClient

# Configurar caminhos
current_dir = os.path.dirname(os.path.abspath(__file__))
json_output_path = os.path.join(current_dir, '../../data/eventos_correpb.json')

# ========== CONEXÃO MONGODB LOCAL ==========
LOCAL_URI = "mongodb://admin:password@localhost:27018/correpb?authSource=admin"
DB_NAME = "correpb"
COLLECTION_NAME = "eventos"

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

    # Novo: prioriza precos estruturados em 'precos_entries' (se existirem)
    horario = evento_mongo.get('horario') or ''
    precos_entries = evento_mongo.get('precos_entries', [])
    if precos_entries and isinstance(precos_entries, list) and any(isinstance(p, dict) for p in precos_entries):
        lista_precos = []
        for p in precos_entries:
            if isinstance(p, dict):
                formatted = p.get('formatted') or p.get('raw') or ''
                ph = p.get('horario') or horario
                lista_precos.append({
                    'formatted': formatted,
                    'horario': ph
                })
            else:
                lista_precos.append({
                    'formatted': str(p),
                    'horario': horario
                })
    else:
        # Fallback antigo: string 'preco' separado por ';'
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
        "lista_precos": lista_precos,
        "horario": horario
    }

def gerar_json_customizado():
    try:
        print(f"🔧 Conectando ao MongoDB Local...")
        client = MongoClient(LOCAL_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
        print("✅ Conectado com sucesso!\n")
        
        # Buscar eventos ordenados
        cursor = collection.find().sort("data_coleta", -1)
        total = collection.count_documents({})
        
        print(f"📊 Exportando {total} eventos...")
        
        eventos_lista = []
        for doc in cursor:
            # Converter _id para string se necessário
            if '_id' in doc:
                doc['_id'] = str(doc['_id'])
            
            # Remover campos internos se quiser
            # if 'data_coleta' in doc: del doc['data_coleta']
            
            eventos_lista.append(doc)
            
        # Salvar JSON
        output_dir = os.path.dirname(json_output_path)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        with open(json_output_path, 'w', encoding='utf-8') as f:
            json.dump(eventos_lista, f, ensure_ascii=False, indent=4, default=converter_datetime)
            
        print(f"✅ JSON gerado com sucesso: {json_output_path}")
        print(f"📝 Total exportado: {len(eventos_lista)}")
        
    except Exception as e:
        print(f"❌ Erro ao gerar JSON: {e}")
    finally:
        if 'client' in locals():
            client.close()

if __name__ == "__main__":
    gerar_json_customizado()
