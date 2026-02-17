import csv
import os
import sys
from datetime import datetime

# Configurar caminho
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, '../..'))
sys.path.insert(0, backend_dir)

from data_collection.evento_de_corrida import EventoDeCorrida
from pymongo import MongoClient

print("🔧 Conectando ao MongoDB LOCAL\n")

# ========== CONEXÃO MONGODB LOCAL ==========
LOCAL_URI = "mongodb://admin:password@localhost:27018/correpb?authSource=admin"
DB_NAME = "correpb"
COLLECTION_NAME = "eventos"

try:
    print("🔄 Conectando ao MongoDB local (porta 27018)...")
    remote_client = MongoClient(LOCAL_URI, serverSelectionTimeoutMS=5000)
    
    # Testar conexão
    remote_client.admin.command('ping')
    print("✅ MongoDB LOCAL conectado com sucesso!")
    
    remote_db = remote_client[DB_NAME]
    remote_collection = remote_db[COLLECTION_NAME]
    
    # Mostrar estatísticas atuais
    total_atual = remote_collection.count_documents({})
    print(f"📊 Eventos já cadastrados: {total_atual}\n")
    
except Exception as e:
    print(f"❌ ERRO ao conectar ao MongoDB local: {e}")
    print("\n🔍 Verifique se:")
    print("  1. MongoDB está rodando (porta 27018)")
    print("  2. Credenciais corretas: admin/password")
    print("  3. Comando: net start MongoDB (ou docker se usar container)\n")
    remote_client = None
    remote_db = None
    remote_collection = None

# ========== FUNÇÕES ==========
def import_csv_to_mongodb(db, csv_file, fonte):
    """Importa dados do CSV para o MongoDB"""
    if db is None:
        print(f"⚠️  MongoDB não conectado. Pulando {fonte}.\n")
        return
    
    try:
        print(f"{'='*60}")
        print(f"📂 Processando: {fonte}")
        print(f"{'='*60}")
        
        with open(csv_file, 'r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file, delimiter=';')
            novos_eventos = 0
            eventos_atualizados = 0
            eventos_ignorados = 0
            erros = 0
            
            for idx, row in enumerate(reader, 1):
                try:
                    # Limpar nomes de colunas (remover BOM)
                    row = {k.strip().replace('\ufeff', ''): v for k, v in row.items()}
                    
                    # Garantir campo link_edital
                    if 'Link do Edital' in row:
                        row['link_edital'] = row['Link do Edital']
                    
                    # Criar objeto evento
                    evento = EventoDeCorrida.from_csv_row(row, fonte)
                    
                    # Verificar se já existe
                    evento_existente = db.eventos.find_one({'nome_evento': evento.nome_evento})
                    
                    if not evento_existente:
                        # Gerar _id customizado (YYYYMMXXXX)
                        now = datetime.now()
                        prefix = f"{now.year}{now.month:02d}"
                        
                        # Buscar último ID com esse prefixo
                        last = db.eventos.find_one(
                            {'_id': {'$regex': f'^{prefix}'}}, 
                            sort=[('_id', -1)]
                        )
                        
                        last_seq = 0
                        if last and isinstance(last.get('_id'), str) and len(last['_id']) >= len(prefix) + 4:
                            try:
                                last_seq = int(last['_id'][-4:])
                            except:
                                pass
                        
                        new_seq = last_seq + 1
                        new_id = f"{prefix}{new_seq:04d}"
                        
                        # Inserir novo evento
                        evento_dict = evento.to_dict()
                        evento_dict['_id'] = new_id
                        
                        db.eventos.insert_one(evento_dict)
                        novos_eventos += 1
                        
                        # Mostrar primeiros 5 eventos novos
                        if novos_eventos <= 5:
                            print(f"  [{new_id}] ✅ NOVO: {evento.nome_evento[:55]}")
                        
                    else:
                        # Comparar para atualização
                        evento_dict = evento.to_dict()
                        evento_existente_dict = {k: v for k, v in evento_existente.items() if k != '_id'}
                        
                        # Remover campos que não devem ser comparados
                        for campo in ['data_coleta']:
                            evento_dict.pop(campo, None)
                            evento_existente_dict.pop(campo, None)
                        
                        # Garantir campos opcionais existam em ambos
                        if 'link_edital' not in evento_existente_dict:
                            evento_existente_dict['link_edital'] = ''
                        if 'horario' not in evento_existente_dict:
                            evento_existente_dict['horario'] = ''
                        
                        # Atualizar se houver diferença
                        if evento_dict != evento_existente_dict:
                            db.eventos.update_one(
                                {'nome_evento': evento.nome_evento},
                                {'$set': evento.to_dict()}
                            )
                            eventos_atualizados += 1
                            
                            # Mostrar primeiros 3 atualizados
                            if eventos_atualizados <= 3:
                                print(f"  [{evento_existente['_id']}] 🔄 ATUALIZADO: {evento.nome_evento[:50]}")
                        else:
                            eventos_ignorados += 1
                        
                except Exception as e:
                    erros += 1
                    if erros <= 3:
                        print(f"  [Linha {idx}] ❌ ERRO: {str(e)[:100]}")
                        print(f"              Nome: {row.get('Nome do Evento', 'N/A')[:50]}")
                    if erros > 20:
                        print(f"\n⚠️  Muitos erros ({erros}). Parando importação de {fonte}.")
                        break
                    continue
            
            print(f"\n📊 Resumo de '{fonte}':")
            print(f"   ✅ Novos: {novos_eventos}")
            print(f"   🔄 Atualizados: {eventos_atualizados}")
            print(f"   ⏭️  Sem alterações: {eventos_ignorados}")
            print(f"   ❌ Erros: {erros}")
            print(f"{'='*60}\n")
            
    except FileNotFoundError:
        print(f"❌ Arquivo não encontrado: {csv_file}\n")
    except Exception as e:
        print(f"❌ Erro ao importar {fonte}: {str(e)}\n")
        import traceback
        traceback.print_exc()

def main():
    """Função principal"""
    try:
        if remote_db is None:
            print("❌ MongoDB não conectado. Encerrando.\n")
            return
        
        db = remote_db
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Arquivos CSV para processar
        csv_files = [
            ('eventos_smcrono.csv', 'smcrono'),
            ('eventos_brasilcorrida.csv', 'brasilcorrida'),
            ('eventos_brasilquecorre.csv', 'brasilquecorre')
        ]
        
        print(f"{'='*60}")
        print(f"🚀 INICIANDO IMPORTAÇÃO DE DADOS")
        print(f"{'='*60}\n")
        
        # Processar cada arquivo
        arquivos_processados = 0
        for filename, fonte in csv_files:
            csv_path = os.path.join(base_dir, '../data', filename)
            
            if os.path.exists(csv_path):
                import_csv_to_mongodb(db, csv_path, fonte)
                arquivos_processados += 1
            else:
                print(f"⚠️  Arquivo não encontrado: {filename}")
                print(f"    Caminho esperado: {csv_path}\n")
        
        # Estatísticas finais
        if arquivos_processados > 0:
            total = db.eventos.count_documents({})
            
            print(f"\n{'='*60}")
            print(f"📊 ESTATÍSTICAS FINAIS")
            print(f"{'='*60}")
            print(f"Total de eventos no banco: {total}")
            
            # Mostrar distribuição por fonte
            print(f"\nEventos por fonte:")
            for fonte in ['smcrono', 'brasilcorrida', 'brasilquecorre']:
                count = db.eventos.count_documents({'fonte': fonte})
                if count > 0:
                    print(f"  • {fonte}: {count} eventos")
            
            # Últimos eventos adicionados
            print(f"\n🔍 Últimos 5 eventos cadastrados:")
            for evento in db.eventos.find().sort('_id', -1).limit(5):
                data = evento.get('data', 'Sem data')
                cidade = evento.get('cidade', 'Sem cidade')
                print(f"  • [{evento['_id']}] {evento['nome_evento'][:45]}")
                print(f"    📅 {data} | 📍 {cidade}")
            
            print(f"\n{'='*60}")
        
    except Exception as e:
        print(f"\n❌ ERRO GERAL: {str(e)}")
        import traceback
        traceback.print_exc()
        
    finally:
        if remote_client:
            print(f"\n🔒 Fechando conexão com MongoDB...")
            remote_client.close()
            print("✅ Importação concluída!\n")

if __name__ == "__main__":
    main()
