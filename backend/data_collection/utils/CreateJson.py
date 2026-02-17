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

def converter_datetime(obj):
    """Converte objetos datetime para string ISO"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Tipo {type(obj)} não é serializável")

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
