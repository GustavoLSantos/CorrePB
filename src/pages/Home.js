import { useEffect, useState } from "react";
import EventCard from "../components/EventCard";
import { isBefore, isAfter } from "date-fns";
import API_URL from "../config/api";

export default function Home() {
  const [eventos, setEventos] = useState([]);
  const [busca, setBusca] = useState("");
  const [cidade, setCidade] = useState("");
  const [categoria, setCategoria] = useState("");
  const [distancia, setDistancia] = useState("");
  const [filtroStatus, setFiltroStatus] = useState("pendentes");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [cidades, setCidades] = useState([]);
  const [categorias, setCategorias] = useState([]);
  const [distancias, setDistancias] = useState([]);
  const [estado, setEstado] = useState("");
  const [totalEventos, setTotalEventos] = useState(0);

  const estados = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO"
  ];

  useEffect(() => {
    fetchEventos();
  }, [page, estado, filtroStatus]);

  useEffect(() => {
    fetchMetadata();
  }, []);


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

  const distanciasOriginais = [
    "0.80Km, 3Km, 5km",
    "0.80Km, 3km, 6km",
    "100m e 500m (infantil), 5km e 10km (corrida)",
    "10km, 18km, 28km e 56km (corrida - trail - ultra)",
    "12h (corrida - ultra)",
    "1km (infantil), 5km,10km e 15km (corrida)",
    "3Km, 5km, 10Km, 15KM",
    "3km (caminhada), 5km (corrida)",
    "3km (caminhada), 5km e 10km (corrida)",
    "3km (caminhada), 6km, 12km e 21km (corrida)",
    "3km e 5km (corrida)",
    "3km, 5km e 10km (corrida)",
    "3km, 5km, 10km",
    "3kmm (caminhada), 5km (corrida)",
    "400m (infantil), 5km, 10km e 18km (corrida - trail)",
    "4km (caminhada), 7km e 15km (corrida - trail)",
    "500m (infantil), 3km (caminhada), 5km e 10km (corrida)",
    "50m à 400m (infantil), 5km e 10km (corrida)",
    "5km",
    "5km (corrida)",
    "5km + 15 obstáculos e 10km + 20 obstáculos (corrida - OCR)",
    "5km e 10km (corrida)",
    "5km e 8km (corrida)",
    "5km, 10km",
    "5km, 10km e 15km (corrida)",
    "5km, 10km e 21km (corrida)",
    "5km, 10km, 21km e 42km (corrida)",
    "6KM",
    "6km (corrida)",
    "6km e 12km (corrida - trail)",
    "7,5km (corrida - trail)",
    "7km (corrida)"
  ];

  const distanciasPadronizadas = processarDistancias(distanciasOriginais);

  const fetchEventos = async () => {
    try {
      setLoading(true);

      let url = `${API_URL}/api/v1/eventos/?ordenar_por=datas_realizacao&ordem=-1&page=${page}&size=12`;

      if (estado) {
        url += `&estado=${estado}`;
      }

      if (filtroStatus !== "todos") {
        url += `&status=${filtroStatus}`;
      }

      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`Erro ao buscar eventos: ${response.status}`);
      }

      const data = await response.json();

      const todosEventos = data.items;

      const hoje = new Date();
      let eventosFiltrados = todosEventos;

      if (filtroStatus === "pendentes") {
        eventosFiltrados = todosEventos.filter(evento => {
          const dataEvento = Array.isArray(evento.datas_realizacao) && evento.datas_realizacao.length > 0
              ? new Date(evento.datas_realizacao[0])
              : new Date(evento.datas_realizacao || evento.data_realizacao);

          return isAfter(dataEvento, hoje) || isSameDay(dataEvento, hoje);
        });
      } else if (filtroStatus === "realizados") {
        eventosFiltrados = todosEventos.filter(evento => {
          const dataEvento = Array.isArray(evento.datas_realizacao) && evento.datas_realizacao.length > 0
              ? new Date(evento.datas_realizacao[0])
              : new Date(evento.datas_realizacao || evento.data_realizacao);

          return isBefore(dataEvento, hoje) && !isSameDay(dataEvento, hoje);
        });
      }

      setEventos(eventosFiltrados);
      setTotalEventos(data.total);
      setTotalPages(Math.ceil(data.total / 12));
      setError(null);
    } catch (err) {
      console.error("Erro ao buscar eventos:", err);
      setError("Falha ao carregar eventos. Por favor, tente novamente mais tarde.");
      setEventos([]);
    } finally {
      setLoading(false);
    }
  };

  const isSameDay = (date1, date2) => {
    return (
        date1.getFullYear() === date2.getFullYear() &&
        date1.getMonth() === date2.getMonth() &&
        date1.getDate() === date2.getDate()
    );
  };

  const fetchMetadata = async () => {
    try {
      const response = await fetch(`${API_URL}/api/v1/eventos/sem-paginacao?limit=100`);

      if (!response.ok) {
        throw new Error(`Erro ao buscar metadados: ${response.status}`);
      }

      const data = await response.json();
      const cidadesUnicas = [...new Set(
          data
              .map(e => e.cidade)
              .filter(c => c && /^[A-Za-zÀ-ÿ\s]+$/.test(c.trim()))
      )].sort();
      const distanciasUnicas = processarDistancias(
          data.map(e => e.distancias).filter(Boolean)
      );

      setCidades(cidadesUnicas);
      setDistancias(distanciasUnicas);
      console.log(distanciasUnicas);
      setCategorias([]);

    } catch (err) {
      console.error("Erro ao buscar metadados:", err);
      setCidades([]);
      setCategorias([]);
      setDistancias([]);
    }
  };

  const eventosFiltrados = eventos.filter((evento) => {
    const nomeMatch = evento.nome_evento
        .toLowerCase()
        .includes(busca.toLowerCase());

    const cidadeMatch = cidade === "" || evento.cidade === cidade;
    const categoriaMatch =
        categoria === "" ||
        (evento.categorias && evento.categorias.includes(categoria));

    let distanciaMatch = distancia === "";

    if (!distanciaMatch && evento.distancias) {
      if (typeof evento.distancias === 'string') {
        distanciaMatch = evento.distancias.includes(distancia);
      } else if (Array.isArray(evento.distancias)) {
        distanciaMatch = evento.distancias.includes(distancia);
      }
    }

    return (
        nomeMatch &&
        cidadeMatch &&
        categoriaMatch &&
        distanciaMatch
    );
  });

  const handlePageChange = (newPage) => {
    setPage(newPage);
    window.scrollTo(0, 0);
  };

  return (
      <div className="min-h-screen bg-gray-100 font-[Bebas Neue,sans-serif]">
        <main className="p-4 max-w-7xl mx-auto">
          <h1 className="text-3xl font-bold mb-6 text-center">Corridas na Paraíba</h1>

          <div className="grid md:grid-cols-4 gap-4 mb-6">
            <input
                type="text"
                placeholder="Buscar por nome"
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
                className="border p-2 rounded col-span-2"
            />

            <select
                value={estado}
                onChange={(e) => {
                  setEstado(e.target.value);
                  setPage(1);
                }}
                className="border p-2 rounded"
            >
              <option value="">Todos os estados</option>
              {estados.map((e) => (
                  <option key={e} value={e}>
                    {e}
                  </option>
              ))}
            </select>

            <select
                value={cidade}
                onChange={(e) => setCidade(e.target.value)}
                className="border p-2 rounded"
            >
              <option value="">Todas as cidades</option>
              {cidades.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
              ))}
            </select>

            {categorias.length > 0 && (
                <select
                    value={categoria}
                    onChange={(e) => setCategoria(e.target.value)}
                    className="border p-2 rounded"
                >
                  <option value="">Todas as categorias</option>
                  {categorias.map((cat) => (
                      <option key={cat} value={cat}>
                        {cat}
                      </option>
                  ))}
                </select>
            )}

            <select
                value={distancia}
                onChange={(e) => setDistancia(e.target.value)}
                className="border p-2 rounded"
            >
              <option value="">Todas as distâncias</option>
              {distancias.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
              ))}
            </select>
          </div>

          <div className="flex gap-4 mb-6">
            <button
                onClick={() => {
                  setFiltroStatus("pendentes");
                  setPage(1);
                }}
                className={`px-4 py-2 rounded ${
                    filtroStatus === "pendentes"
                        ? "bg-gray-800 text-white"
                        : "bg-gray-200"
                }`}
            >
              Próximos Eventos
            </button>
            <button
                onClick={() => {
                  setFiltroStatus("realizados");
                  setPage(1);
                }}
                className={`px-4 py-2 rounded ${
                    filtroStatus === "realizados"
                        ? "bg-gray-800 text-white"
                        : "bg-gray-200"
                }`}
            >
              Realizados
            </button>
            <button
                onClick={() => {
                  setFiltroStatus("todos");
                  setPage(1);
                }}
                className={`px-4 py-2 rounded ${
                    filtroStatus === "todos"
                        ? "bg-gray-800 text-white"
                        : "bg-gray-200"
                }`}
            >
              Todos
            </button>
          </div>

          {/* Contador de resultados */}
          <div className="mb-4 text-gray-600">
            Mostrando {eventosFiltrados.length} de {totalEventos} eventos
          </div>

          {loading ? (
              <div className="flex justify-center items-center h-64">
                <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-gray-900"></div>
              </div>
          ) : error ? (
              <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative" role="alert">
                <strong className="font-bold">Erro!</strong>
                <span className="block sm:inline"> {error}</span>
              </div>
          ) : eventosFiltrados.length === 0 ? (
              <div className="text-center py-10">
                <p className="text-xl text-gray-600">Nenhum evento encontrado com os filtros selecionados.</p>
                <button
                    onClick={() => {
                      setBusca("");
                      setCidade("");
                      setCategoria("");
                      setDistancia("");
                      setFiltroStatus("todos");
                      setPage(1);
                    }}
                    className="mt-4 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                >
                  Limpar filtros
                </button>
              </div>
          ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {eventosFiltrados.map((evento) => (
                    <EventCard key={evento._id} evento={evento} />
                ))}
              </div>
          )}

          {/* Paginação */}
          {totalPages > 1 && (
              <div className="flex justify-center mt-8">
                <nav className="inline-flex">
                  <button
                      onClick={() => handlePageChange(page - 1)}
                      disabled={page === 1}
                      className={`px-4 py-2 border rounded-l ${
                          page === 1 ? "bg-gray-100 text-gray-400" : "bg-white hover:bg-gray-50"
                      }`}
                  >
                    Anterior
                  </button>

                  {/* Mostrar números de página */}
                  {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                    let pageNum;
                    if (totalPages <= 5) {
                      pageNum = i + 1;
                    } else if (page <= 3) {
                      pageNum = i + 1;
                    } else if (page >= totalPages - 2) {
                      pageNum = totalPages - 4 + i;
                    } else {
                      pageNum = page - 2 + i;
                    }

                    return (
                        <button
                            key={pageNum}
                            onClick={() => handlePageChange(pageNum)}
                            className={`px-4 py-2 border-t border-b ${
                                page === pageNum
                                    ? "bg-gray-800 text-white"
                                    : "bg-white hover:bg-gray-50"
                            } ${i === 0 ? "" : "border-l"}`}
                        >
                          {pageNum}
                        </button>
                    );
                  })}

                  <button
                      onClick={() => handlePageChange(page + 1)}
                      disabled={page === totalPages}
                      className={`px-4 py-2 border rounded-r ${
                          page === totalPages ? "bg-gray-100 text-gray-400" : "bg-white hover:bg-gray-50"
                      }`}
                  >
                    Próxima
                  </button>
                </nav>
              </div>
          )}
        </main>
      </div>
  );
}
