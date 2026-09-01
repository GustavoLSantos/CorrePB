import json
from datetime import datetime

import pytest

from data_collection.evento_de_corrida import EventoDeCorrida


def _base_kwargs(**overrides):
    """Base valid kwargs for EventoDeCorrida."""
    base = dict(
        nome_evento="Trun Bananeiras 2026",
        datas_realizacao=[datetime(2026, 9, 12)],
        cidade="Bananeiras",
        estado="PB",
        organizador="Race83",
        site_coleta="race83",
        data_coleta=datetime(2026, 8, 31, 12, 0, 0),
        distancias="5km, 10km",
        horario="06:00",
        url_inscricao="https://www.race83.com.br/evento/123/slug",
        url_imagem="https://cdn.example.com/img.jpg",
        categoria="Corrida",
        link_edital="https://cdn.example.com/edital.pdf",
        categorias_premiadas="5km Geral Masculino, 5km Geral Feminino",
        preco="R$ 50,00",
        precos_entries=[{"label": "Geral", "price": 50.0, "formatted": "R$ 50,00"}],
        percurso={"local_largada": "Praça Central"},
        kits=[{"nome": "Kit", "itens": ["camiseta", "medalha"], "local_retirada": "Ginásio"}],
    )
    base.update(overrides)
    return base


class TestFromCsvRow:
    def test_parse_single_date(self):
        row = {
            "Nome do Evento": "Teste",
            "Data": "15 de agosto de 2026",
            "Cidade": "João Pessoa",
            "Distância": "5km",
            "Organizador": "X",
            "Link de Inscrição": "http://x",
            "Horário": "06:00",
        }
        evento = EventoDeCorrida.from_csv_row(row, "test")
        assert len(evento.datas_realizacao) == 1
        assert evento.datas_realizacao[0].month == 8
        assert evento.datas_realizacao[0].day == 15
        assert evento.cidade == "João Pessoa"
        assert evento.estado == "PB"

    def test_parse_multi_dates(self):
        row = {
            "Nome do Evento": "Teste Multi",
            "Data": "02, 03 e 15 de Agosto de 2025",
            "Cidade": "Campina Grande",
            "Distância": "5km",
            "Organizador": "Y",
            "Link de Inscrição": "http://y",
        }
        evento = EventoDeCorrida.from_csv_row(row, "test")
        assert len(evento.datas_realizacao) == 3
        assert {d.day for d in evento.datas_realizacao} == {2, 3, 15}
        assert evento.datas_realizacao[0].month == 8

    def test_city_state_extraction(self):
        row = {
            "Nome do Evento": "Teste",
            "Data": "15 de agosto de 2026",
            "Cidade": "Santa Cruz - RN",
            "Distância": "5km",
            "Organizador": "Z",
            "Link de Inscrição": "http://z",
        }
        evento = EventoDeCorrida.from_csv_row(row, "test")
        assert evento.cidade == "Santa Cruz"
        assert evento.estado == "RN"

    def test_precos_entries_json_parsing(self):
        precos = [{"label": "Geral", "price": 50.0}]
        row = {
            "Nome do Evento": "Teste",
            "Data": "15 de agosto de 2026",
            "Cidade": "João Pessoa",
            "Distância": "5km",
            "Organizador": "X",
            "Link de Inscrição": "http://x",
            "precos_entries": json.dumps(precos),
        }
        evento = EventoDeCorrida.from_csv_row(row, "test")
        assert evento.precos_entries == precos

    def test_invalid_json_returns_none(self):
        row = {
            "Nome do Evento": "Teste",
            "Data": "15 de agosto de 2026",
            "Cidade": "João Pessoa",
            "Distância": "5km",
            "Organizador": "X",
            "Link de Inscrição": "http://x",
            "precos_entries": "not-json",
            "Percurso": "not-json",
            "Kits": "not-json",
        }
        evento = EventoDeCorrida.from_csv_row(row, "test")
        assert evento.precos_entries is None or evento.precos_entries == []
        assert evento.percurso is None
        assert evento.kits is None


class TestToDict:
    def test_empty_optional_not_persisted(self):
        evento = EventoDeCorrida(
            **_base_kwargs(
                horario="", url_inscricao="", preco="   ", link_edital="  ", categorias_premiadas=""
            )
        )
        doc = evento.to_dict()
        assert "horario" not in doc
        assert "url_inscricao" not in doc
        assert "preco" not in doc
        assert "link_edital" not in doc
        assert "categorias_premiadas" not in doc

    def test_non_empty_persisted(self):
        evento = EventoDeCorrida(**_base_kwargs())
        doc = evento.to_dict()
        assert doc["horario"] == "06:00"
        assert doc["link_edital"] == "https://cdn.example.com/edital.pdf"
        assert doc["preco"] == "R$ 50,00"
        assert doc["precos_entries"] == [{"label": "Geral", "price": 50.0, "formatted": "R$ 50,00"}]

    def test_percurso_kits_defaults(self):
        evento = EventoDeCorrida(
            **_base_kwargs(percurso={"local_largada": "Praça"}, kits=[{"itens": ["camiseta"]}])
        )
        doc = evento.to_dict()
        assert doc["percurso"]["local_largada"] == "Praça"
        assert doc["kits"][0]["nome"] == "Kit"

    def test_precos_entries_empty_not_persisted(self):
        evento = EventoDeCorrida(**_base_kwargs(precos_entries=[]))
        doc = evento.to_dict()
        assert "precos_entries" not in doc
        assert "kits" in doc  # kits still has value from base, check empty
        evento2 = EventoDeCorrida(**_base_kwargs(kits=[]))
        assert "kits" not in evento2.to_dict()


class TestEquality:
    def test_equal_same_fields(self):
        e1 = EventoDeCorrida(**_base_kwargs())
        e2 = EventoDeCorrida(**_base_kwargs())
        assert e1 == e2

    def test_not_equal_different_price_entries(self):
        e1 = EventoDeCorrida(**_base_kwargs(precos_entries=[{"label": "Geral", "price": 50.0}]))
        e2 = EventoDeCorrida(**_base_kwargs(precos_entries=[{"label": "Geral", "price": 90.0}]))
        assert e1 != e2

    def test_not_equal_different_kits(self):
        e1 = EventoDeCorrida(**_base_kwargs(kits=[{"nome": "Kit", "itens": ["camiseta"]}]))
        e2 = EventoDeCorrida(
            **_base_kwargs(kits=[{"nome": "Kit", "itens": ["camiseta", "medalha"]}])
        )
        assert e1 != e2

    def test_not_equal_different_edital(self):
        e1 = EventoDeCorrida(**_base_kwargs(link_edital="https://a.pdf"))
        e2 = EventoDeCorrida(**_base_kwargs(link_edital="https://b.pdf"))
        assert e1 != e2

    def test_equal_edital_placeholder_vs_empty(self):
        # to_dict normalizes, but __eq__ should treat "" and "edital não encontrado" as different?
        # Actually __eq__ compares raw objects, so placeholder vs empty are different — test documents behavior
        e1 = EventoDeCorrida(**_base_kwargs(link_edital="edital não encontrado"))
        e2 = EventoDeCorrida(**_base_kwargs(link_edital=""))
        # Current __eq__ treats them as different because link_edital is compared via !=
        # This is expected — placeholder is stored as is, but to_dict omits empty. Test ensures difference is detected.
        assert e1 != e2

    def test_equal_order_independent_price_entries(self):
        e1 = EventoDeCorrida(
            **_base_kwargs(
                precos_entries=[{"label": "A", "price": 50.0}, {"label": "B", "price": 90.0}]
            )
        )
        e2 = EventoDeCorrida(
            **_base_kwargs(
                precos_entries=[{"label": "B", "price": 90.0}, {"label": "A", "price": 50.0}]
            )
        )
        assert e1 == e2

    def test_not_equal_different_city_state(self):
        e1 = EventoDeCorrida(**_base_kwargs(cidade="João Pessoa", estado="PB"))
        e2 = EventoDeCorrida(**_base_kwargs(cidade="Campina Grande", estado="PB"))
        assert e1 != e2
