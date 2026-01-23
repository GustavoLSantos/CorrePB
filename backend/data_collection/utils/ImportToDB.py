import csv
import os

from dotenv import load_dotenv
from data_collection.evento_de_corrida import EventoDeCorrida
from pymongo import MongoClient

# Carregar o .env da raiz do projeto
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..', '.env'))
load_dotenv(env_path)

REMOTE_URI = os.getenv('MONGODB_REMOTE_URI') or os.getenv('MONGODB_URI')
if not REMOTE_URI:
    raise Exception('A variável MONGODB_REMOTE_URI ou MONGODB_URI não está definida no .env')
remote_client = MongoClient(REMOTE_URI)

REMOTE_DB_NAME = os.getenv('MONGODB_REMOTE_DB_NAME') or os.getenv('MONGODB_DB_NAME') or 'correpb'
remote_db = remote_client[REMOTE_DB_NAME]
remote_collection = remote_db['eventos']

def import_csv_to_mongodb(db, csv_file, fonte):
    try:
        with open(csv_file, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file, delimiter=';')
            novos_eventos = 0
            eventos_atualizados = 0
            for row in reader:
                try:
                    # Garante que o campo link_edital será passado, se existir no CSV
                    if 'Link do Edital' in row:
                        row['link_edital'] = row['Link do Edital']
                    # O campo 'Categorias Premiadas' será tratado automaticamente pelo EventoDeCorrida
                    evento = EventoDeCorrida.from_csv_row(row, fonte)
                    evento_existente = db.eventos.find_one({'nome_evento': evento.nome_evento})
                    if not evento_existente:
                        db.eventos.insert_one(evento.to_dict())
                        novos_eventos += 1
                    else:
                        evento_dict = evento.to_dict()
                        evento_existente_dict = {k: v for k, v in evento_existente.items() if k != '_id'}
                        campos_nao_comparaveis = ['data_coleta']
                        for campo in campos_nao_comparaveis:
                            evento_dict.pop(campo, None)
                            evento_existente_dict.pop(campo, None)
                        # Garante que ambos os dicionários tenham o campo 'link_edital' para comparação justa
                        if 'link_edital' not in evento_existente_dict:
                            evento_existente_dict['link_edital'] = ''
                        if 'link_edital' not in evento_dict:
                            evento_dict['link_edital'] = ''
                        if evento_dict != evento_existente_dict:
                            print(f"Atualizando evento: {evento.nome_evento}")
                            print(f"Antes: {evento_existente_dict}")
                            print(f"Depois: {evento_dict}")
                            db.eventos.update_one(
                                {'nome_evento': evento.nome_evento},
                                {'$set': evento.to_dict()}
                            )
                            eventos_atualizados += 1
                except Exception as e:
                    print(f"❌ Erro ao processar linha do CSV: {str(e)}")
                    print(f"Conteúdo da linha: {row}")
                    continue
        print(f"✅ Dados de {fonte} processados com sucesso no Atlas")
        print(f"📝 {novos_eventos} novos eventos adicionados")
        print(f"🔄 {eventos_atualizados} eventos atualizados")
    except Exception as e:
        print(f"❌ Erro ao importar dados de {fonte}: {str(e)}")

def main():
    try:
        db = remote_db
        base_dir = os.path.dirname(os.path.abspath(__file__))
        csv_brasilcorrida = os.path.join(base_dir, '../data/eventos_brasilcorrida.csv')
        csv_brasilquecorre = os.path.join(base_dir, '../data/eventos_brasilquecorre.csv')
        import_csv_to_mongodb(db, csv_brasilcorrida, 'brasilcorrida')
        import_csv_to_mongodb(db, csv_brasilquecorre, 'brasilquecorre')
        total = db.eventos.count_documents({})
        print(f"\n📊 Total de eventos na base Atlas: {total}")
    except Exception as e:
        print(f"❌ Erro geral: {str(e)}")

if __name__ == "__main__":
    main()
