
# Estrutura do Projeto

```
├── data_collection/              # Scripts utilitários
├── .env                      # Variáveis de ambiente (não versionado)
├── .env.example              # Exemplo de variáveis de ambiente (versionado)
├── .gitignore                # Arquivos a serem ignorados pelo Git
├── requirements.txt          # Dependências do projeto
├── main.py                   # Ponto de entrada principal da aplicação
└── README.md                 # Documentação do projeto
```

# Eventos Banco de Dados

|Campo|Tipo|Descrição|
|:-:|:-:|:-|
|_id|string|ID do evento (Mongo ObjectId como string)|
|nome_evento|string|Nome do evento|
|url_inscricao|string|URL de inscrição do evento|
|url_imagem|string|URL da imagem do evento|
|data_realizacao|string|Data de realização do evento (ex.: '19 de Abril de 2026')|
|cidade|string|Cidade em que o evento será realizado|
|estado|string|Estado (sigla) do evento|
|data_coleta|datetime|Data/hora da coleta (ISO string)|
|distancias|list(string)|Distâncias oferecidas durante o evento|
|organizador|string|Entidade organizadora do evento|
|categorias|list(string)|Categorias do evento (se houver)|
|preco|string|Campo 'preco' original (pode estar vazio)|
|lista_precos|list(object)|Entradas de preço estruturadas (cada item contém 'formatted')|
|horario|string|Horário de largada no formato 'HH:MM' ou texto explicativo|