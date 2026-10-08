# Corre PB — Backend

Composta por dois subsistemas: a **API REST** (FastAPI + MongoDB) e o **pipeline de coleta de dados** (scrapers Selenium + BeautifulSoup).

## Estrutura do Projeto

```
├── app/
│   ├── api/
│   │   └── eventos.py            # Rotas da API (/api/v1/eventos)
│   ├── core/
│   │   ├── auth.py               # Autenticação
│   │   ├── config.py             # Configuração via pydantic-settings + .env
│   │   └── database.py           # Conexão MongoDB (Motor async + auto-detect remoto)
│   └── models/
│       └── evento.py             # Modelos Pydantic (EventoResponse, EventoCreate, EventoUpdate, Percurso, Kit)
├── data_collection/
│   ├── core/
│   │   └── Driver.py             # Fábrica de Chrome WebDriver
│   ├── sources/                  # Scrapers modulares por site
│   │   ├── CircuitoDasEstacoes.py
│   │   ├── Liverun.py
│   │   ├── Nightrun.py
│   │   ├── Race83.py
│   │   ├── Sympla.py
│   │   ├── Ticketsports.py
│   │   └── Zenite.py
│   ├── utils/
│   │   ├── CreateJson.py         # Geração de JSON a partir dos dados coletados
│   │   ├── ImportToBucket.py     # Importação para S3
│   │   ├── ImportToDB.py         # Importação de CSVs para MongoDB local
│   │   ├── insert_evento.py      # Inserção de evento individual
│   │   ├── PriceUtils.py         # Utilitários de preço
│   │   ├── PrizeDetection.py     # Detecção de categorias premiadas
│   │   └── ProcessImages.py      # Download e upload de imagens
│   ├── scraper_brasilcorrida.py  # Scraper: Brasil Corrida (legado, ignorado)
│   ├── scraper_brasilquecorre.py # Scraper: Brasil que Corre
│   ├── scraper_smcrono.py        # Scraper: SM Crono
│   ├── pipeline_agent.py         # Pipeline de coleta automatizado
│   ├── evento_de_corrida.py      # Classe EventoDeCorrida (contrato scrapers → MongoDB)
│   ├── Dockerfile                # Dockerfile dos scrapers
│   └── requirements.txt          # Dependências dos scrapers
├── main.py                       # Entrada da aplicação (FastAPI + lifespan)
├── docker-compose.yml            # MongoDB local (porta 27018)
├── Dockerfile                    # Dockerfile da API
├── requirements.txt              # Dependências da API
├── .env.example                  # Exemplo de variáveis de ambiente
└── README.md
```

## Schema do Evento

| Campo | Tipo | Descrição |
|---|---|---|
| `_id` | `string` | ID customizado no formato `YYYYMM####` (ex: `2026050001`) |
| `nome_evento` | `string` | Nome do evento |
| `datas_realizacao` | `list[datetime]` | Datas de realização |
| `cidade` | `string` | Cidade do evento |
| `estado` | `string` | Estado (sigla) |
| `organizador` | `string` | Entidade organizadora |
| `site_coleta` | `string` | Site de origem dos dados |
| `data_coleta` | `datetime` | Data/hora da coleta |
| `distancias` | `string` | Distâncias oferecidas |
| `horario` | `string \| null` | Horário de largada (formato `HH:MM`) |
| `url_inscricao` | `string \| null` | URL de inscrição |
| `url_imagem` | `string \| null` | URL da imagem |
| `categoria` | `string \| null` | Categoria do evento |
| `link_edital` | `string \| null` | Link do edital/regulamento |
| `categorias_premiadas` | `string \| null` | Categorias que recebem premiação |
| `preco` | `string \| null` | Preço (texto livre) |
| `precos_entries` | `list[object] \| null` | Entradas de preço estruturadas |
| `patrocinado` | `bool` | Se o evento é patrocinado |
| `percurso` | `object \| null` | Percurso: `local_largada` (string), `trajeto` (string, opcional) |
| `kits` | `list[object] \| null` | Kits: `nome` (string), `itens` (list[string]), `local_retirada` (string, opcional), `data_retirada` (datetime, opcional) |

## Setup local

```bash
# Subir MongoDB local
docker-compose up -d

# Instalar dependências da API
pip install -r requirements.txt

# Rodar a API
python main.py
# Acesse http://localhost:8181/docs para a documentação interativa
```

## Worker de scraping (`worker.py`)

A API Go cria jobs com status `queued` e responde 202 imediatamente. Este
worker reivindica o job mais antigo (`queued` → `running`, atomicamente via
`find_one_and_update`), executa `data_collection/pipeline_agent.py` como
subprocesso e marca `complete`/`failed` com `active: false` (liberando o
slot para o próximo `POST /scrape/run`). Também grava `scrape_state`
(`last_scrape`), lido pelo `GET /scrape/last-run`.

```bash
# Dependências (API + scrapers)
pip install -r requirements.txt -r data_collection/requirements.txt

# Ver o plano sem executar nada
python worker.py --dry-run

# Processar um job e sair (ideal para Azure Container Apps Job)
python worker.py --once

# Loop contínuo (desenvolvimento)
python worker.py --loop --interval 60

# Validar o protocolo num banco de teste (sem scrape, sem S3)
MONGODB_DB_NAME=worker_selftest WORKER_ALLOW_SELF_TEST=1 python worker.py --self-test
```

Variáveis: `MONGODB_URI` (obrigatória), `MONGODB_DB_NAME` (default
`corridas_db`), `WORKER_POLL_INTERVAL` (default 60s), `WORKER_JOB_TIMEOUT`
(default 3600s). O `.env` local é carregado automaticamente; em produção
tudo chega pelo ambiente do Container Apps Job.

Imagem própria (separada da API): `Dockerfile.worker`
(`python worker.py --once` como entrypoint padrão).

## Variáveis de ambiente

Copie `.env.example` para `.env` e preencha:

| Variável | Descrição |
|---|---|
| `MONGODB_URI` | URI local (padrão: `mongodb://localhost:27017`) |
| `MONGODB_DB_NAME` | Nome do banco local |
| `MONGODB_REMOTE_URI` | URI do MongoDB Atlas (se definida, tem prioridade) |
| `MONGODB_REMOTE_DB_NAME` | Nome do banco remoto |
| `API_HOST` / `API_PORT` | Host e porta da API |
| `API_DEBUG` | Habilita reload automático |

## Deploy (ECS + ECR)

```bash
# 1. Login no ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

# 2. Build
docker build -t circuito-api-data .

# 3. Tag
docker tag circuito-api-data:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/circuito-api-data:latest

# 4. Push
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/circuito-api-data:latest

# 5. Forçar novo deploy no ECS
aws ecs update-service --cluster default --service <service> --force-new-deployment
```
