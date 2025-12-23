import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

import API_URL from "../config/api";

export default function Dashboard() {
  const [eventos, setEventos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState({
    eventosPorCidade: [],
    eventosPorMes: [],
    eventosStatus: [],
    eventosPorEstado: [],
    eventosPorDistancia: []
  });

  useEffect(() => {
    fetchEventos();
  }, []);

  const fetchEventos = async () => {
    try {
      setLoading(true);

      const response = await fetch(`${API_URL}/api/v1/eventos/sem-paginacao?limit=1000`);

      if (!response.ok) {
        throw new Error(`Erro ao buscar eventos: ${response.status}`);
      }

      const data = await response.json();
      setEventos(data);

      processarEstatisticas(data);

    } catch (err) {
      console.error("Erro ao buscar eventos:", err);
      setError("Falha ao carregar dados. Por favor, tente novamente mais tarde.");
    } finally {
      setLoading(false);
    }
  };

  const processarEstatisticas = (dados) => {
    const cidadesContagem = dados.reduce((acc, cur) => {
      if (!cur.cidade) return acc;
      acc[cur.cidade] = (acc[cur.cidade] || 0) + 1;
      return acc;
    }, {});

    const eventosPorCidade = Object.entries(cidadesContagem)
        .map(([cidade, total]) => ({ cidade, total }))
        .sort((a, b) => b.total - a.total)
        .slice(0, 10);

    const eventosPorMes = Array(12).fill(0).map((_, i) => ({
      mes: new Date(2023, i, 1).toLocaleString("pt-BR", { month: "short" }),
      total: 0
    }));

    dados.forEach(evento => {
      let dataEvento;
      if (Array.isArray(evento.datas_realizacao) && evento.datas_realizacao.length > 0) {
        dataEvento = new Date(evento.datas_realizacao[0]);
      } else if (evento.datas_realizacao) {
        dataEvento = new Date(evento.datas_realizacao);
      } else {
        return;
      }

      const mes = dataEvento.getMonth();
      eventosPorMes[mes].total += 1;
    });
    const hoje = new Date();
    const status = { realizados: 0, pendentes: 0 };

    dados.forEach(evento => {
      let dataEvento;
      if (Array.isArray(evento.datas_realizacao) && evento.datas_realizacao.length > 0) {
        dataEvento = new Date(evento.datas_realizacao[0]);
      } else if (evento.datas_realizacao) {
        dataEvento = new Date(evento.datas_realizacao);
      } else {
        return;
      }

      if (dataEvento < hoje) {
        status.realizados++;
      } else {
        status.pendentes++;
      }
    });

    const eventosStatus = [
      { nome: "Realizados", valor: status.realizados },
      { nome: "Pendentes", valor: status.pendentes },
    ];

    const estadosContagem = dados.reduce((acc, cur) => {
      if (!cur.estado) return acc;
      acc[cur.estado] = (acc[cur.estado] || 0) + 1;
      return acc;
    }, {});

    const eventosPorEstado = Object.entries(estadosContagem)
        .map(([estado, total]) => ({ estado, total }))
        .sort((a, b) => b.total - a.total);

    const distanciasProcessadas = processarDistancias(dados.map(e => e.distancias).filter(Boolean));
    const distanciasContagem = {};

    dados.forEach(evento => {
      if (!evento.distancias) return;

      const distanciasEvento = processarDistancias([evento.distancias]);

      distanciasEvento.forEach(dist => {
        distanciasContagem[dist] = (distanciasContagem[dist] || 0) + 1;
      });
    });

    const eventosPorDistancia = Object.entries(distanciasContagem)
        .map(([distancia, total]) => ({ distancia, total }))
        .sort((a, b) => b.total - a.total)
        .slice(0, 5);

    setStats({
      eventosPorCidade,
      eventosPorMes,
      eventosStatus,
      eventosPorEstado,
      eventosPorDistancia
    });
  };

  const processarDistancias = (distanciasArray) => {
    const distanciasUnicas = new Set();

    distanciasArray.forEach(distanciaString => {
      if (!distanciaString) return;

      const semParenteses = distanciaString.replace(/\([^)]*\)/g, '');

      const partes = semParenteses
          .replace(/ e /g, ',')
          .split(',');

      partes.forEach(parte => {
        const limpa = parte.trim();
        if (!limpa) return;

        const match = limpa.match(/(\d+(?:[.,]\d+)?)\s*(km|m|mi)?/i);
        if (!match) return;

        const valor = match[1].replace(',', '.');
        let unidade = (match[2] || '').toLowerCase();

        if (!unidade || unidade === 'k' || unidade === 'km') {
          distanciasUnicas.add(`${valor}km`);
        } else if (unidade === 'm') {
          if (parseFloat(valor) >= 1000) {
            const valorKm = (parseFloat(valor) / 1000).toFixed(1);
            distanciasUnicas.add(`${valorKm}km`);
          } else {
            distanciasUnicas.add(`${valor}m`);
          }
        } else {
          distanciasUnicas.add(`${valor}${unidade}`);
        }
      });
    });

    return [...distanciasUnicas].sort((a, b) => {
      const matchA = a.match(/(\d+(?:\.\d+)?)\s*(km|m|mi)?/i);
      const matchB = b.match(/(\d+(?:\.\d+)?)\s*(km|m|mi)?/i);

      if (!matchA || !matchB) return 0;

      const valorA = parseFloat(matchA[1]);
      const valorB = parseFloat(matchB[1]);
      const unidadeA = (matchA[2] || 'km').toLowerCase();
      const unidadeB = (matchB[2] || 'km').toLowerCase();

      let valorEmMetrosA = valorA;
      let valorEmMetrosB = valorB;

      if (unidadeA === 'km') valorEmMetrosA *= 1000;
      if (unidadeB === 'km') valorEmMetrosB *= 1000;

      return valorEmMetrosA - valorEmMetrosB;
    });
  };

  const cores = [
    "#4B5563",
    "#10B981",
    "#3B82F6",
    "#F59E0B",
    "#EF4444",
    "#6366F1",
    "#EC4899",
    "#14B8A6",
    "#8B5CF6",
    "#F97316",
  ];

  if (loading) {
    return (
        <div className="min-h-screen bg-gray-100 flex justify-center items-center">
          <div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-gray-900"></div>
        </div>
    );
  }

  if (error) {
    return (
        <div className="min-h-screen bg-gray-100 p-4 max-w-6xl mx-auto">
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative" role="alert">
            <strong className="font-bold">Erro!</strong>
            <span className="block sm:inline"> {error}</span>
          </div>
        </div>
    );
  }

  return (
      <div className="min-h-screen bg-gray-100 p-4 max-w-6xl mx-auto">
        <h1 className="text-4xl mb-8 font-[Bebas Neue,sans-serif] text-gray-800">
          Dashboard de Corridas
        </h1>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-12">
          <div className="bg-white p-4 shadow rounded">
            <h2 className="text-xl mb-4">Top 10 Cidades</h2>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={stats.eventosPorCidade} layout="vertical">
                <XAxis type="number" allowDecimals={false} />
                <YAxis dataKey="cidade" type="category" width={100} />
                <Tooltip />
                <Bar dataKey="total" fill="#3B82F6" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-white p-4 shadow rounded">
            <h2 className="text-xl mb-4">Eventos por Mês</h2>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={stats.eventosPorMes}>
                <XAxis dataKey="mes" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="total" fill="#10B981" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-12">
          <div className="bg-white p-4 shadow rounded">
            <h2 className="text-xl mb-4">Eventos por Estado</h2>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={stats.eventosPorEstado} layout="vertical">
                <XAxis type="number" allowDecimals={false} />
                <YAxis dataKey="estado" type="category" width={50} />
                <Tooltip />
                <Bar dataKey="total" fill="#F59E0B" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="bg-white p-4 shadow rounded">
            <h2 className="text-xl mb-4">Top 5 Distâncias</h2>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={stats.eventosPorDistancia}>
                <XAxis dataKey="distancia" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="total" fill="#EF4444" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-white p-4 shadow rounded">
          <h2 className="text-xl mb-4">Eventos Realizados vs Pendentes</h2>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                  dataKey="valor"
                  data={stats.eventosStatus}
                  cx="50%"
                  cy="50%"
                  outerRadius={100}
                  label={({ nome, valor, percent }) =>
                      `${nome}: ${valor} (${(percent * 100).toFixed(0)}%)`
                  }
                  nameKey="nome"
              >
                {stats.eventosStatus.map((entry, index) => (
                    <Cell
                        key={`cell-${index}`}
                        fill={cores[index % cores.length]}
                    />
                ))}
              </Pie>
              <Legend />
              <Tooltip formatter={(value, name, props) => [value, props.payload.nome]} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="mt-8 text-center text-gray-600">
          <p>Total de eventos: {eventos.length}</p>
        </div>
      </div>
  );
}
