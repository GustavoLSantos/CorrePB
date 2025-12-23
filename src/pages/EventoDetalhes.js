import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import API_URL from "../config/api";

export default function EventoDetalhes() {
  const { id } = useParams();
  const [evento, setEvento] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchEvento();
  }, [id]);

  const fetchEvento = async () => {
    try {
      setLoading(true);

      const response = await fetch(`${API_URL}/api/v1/eventos/${id}`);

      if (!response.ok) {
        if (response.status === 404) {
          throw new Error("Evento não encontrado");
        }
        throw new Error(`Erro ao buscar evento: ${response.status}`);
      }

      const data = await response.json();

      const distanciasFormatadas = processarDistanciasParaExibicao(
        data.distancias
      );

      setEvento({
        ...data,
        distanciasFormatadas,
      });
    } catch (err) {
      console.error("Erro ao buscar evento:", err);
      setError(
        err.message ||
          "Falha ao carregar o evento. Por favor, tente novamente mais tarde."
      );
    } finally {
      setLoading(false);
    }
  };

  const processarDistanciasParaExibicao = (distanciasString) => {
    if (!distanciasString) return "Não informado";

    if (typeof distanciasString === "string") {
      return distanciasString
        .replace(/\([^)]*\)/g, "")
        .replace(/\s+/g, " ")
        .trim();
    }

    if (Array.isArray(distanciasString)) {
      return distanciasString.join(", ");
    }

    return "Não informado";
  };

  const formatarData = (dataString) => {
    if (!dataString) return "Data não informada";

    try {
      let data;

      if (Array.isArray(dataString)) {
        if (dataString.length === 0) return "Data não informada";
        data = new Date(dataString[0]);
      } else {
        data = new Date(dataString);
      }

      if (isNaN(data.getTime())) return "Data inválida";

      return format(data, "dd 'de' MMMM 'de' yyyy", { locale: ptBR });
    } catch (error) {
      console.error("Erro ao formatar data:", error);
      return "Data inválida";
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-100 flex justify-center items-center">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-gray-900"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-100 p-4 max-w-4xl mx-auto">
        <Link
          to="/"
          className="inline-flex items-center gap-2 text-sm text-white bg-gray-800 hover:bg-gray-700 px-4 py-2 rounded mb-4"
        >
          <span className="text-lg">←</span> Voltar
        </Link>

        <div
          className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative"
          role="alert"
        >
          <strong className="font-bold">Erro!</strong>
          <span className="block sm:inline"> {error}</span>
        </div>
      </div>
    );
  }

  if (!evento) {
    return (
      <div className="min-h-screen bg-gray-100 p-4 max-w-4xl mx-auto">
        <Link
          to="/"
          className="inline-flex items-center gap-2 text-sm text-white bg-gray-800 hover:bg-gray-700 px-4 py-2 rounded mb-4"
        >
          <span className="text-lg">←</span> Voltar
        </Link>

        <div
          className="bg-yellow-100 border border-yellow-400 text-yellow-700 px-4 py-3 rounded relative"
          role="alert"
        >
          <strong className="font-bold">Atenção!</strong>
          <span className="block sm:inline"> Evento não encontrado.</span>
        </div>
      </div>
    );
  }

  const hoje = new Date();
  let dataEvento;
  if (
    Array.isArray(evento.datas_realizacao) &&
    evento.datas_realizacao.length > 0
  ) {
    dataEvento = new Date(evento.datas_realizacao[0]);
  } else if (evento.datas_realizacao) {
    dataEvento = new Date(evento.datas_realizacao);
  } else {
    dataEvento = new Date(evento.data_realizacao || Date.now());
  }
  const eventoRealizado = dataEvento < hoje;

  return (
    <div className="min-h-screen bg-gray-100 p-4 max-w-4xl mx-auto font-[Bebas Neue,sans-serif]">
      <Link
        to="/"
        className="inline-flex items-center gap-2 text-sm text-white bg-gray-800 hover:bg-gray-700 px-4 py-2 rounded mb-4"
      >
        <span className="text-lg">←</span> Voltar
      </Link>

      <div className="bg-white shadow rounded overflow-hidden">
        <div className="relative">
          <img
            src={
              evento.url_imagem && evento.url_imagem.startsWith("http")
                ? evento.url_imagem
                : "/images/default-event.jpg"
            }
            alt={evento.nome_evento}
            className="w-full h-64 object-cover"
            onError={(e) => {
              e.target.onerror = null;
              e.target.src = "/images/default-event.jpg";
            }}
          />

          {/* Badge de status */}
          <div
            className={`absolute top-4 right-4 px-3 py-1 rounded text-sm font-bold ${
              eventoRealizado
                ? "bg-gray-500 text-white"
                : "bg-green-500 text-white"
            }`}
          >
            {eventoRealizado ? "Realizado" : "Pendente"}
          </div>
        </div>

        <div className="p-6">
          <h1 className="text-3xl font-bold mb-4">{evento.nome_evento}</h1>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <div>
              <h2 className="text-xl font-semibold mb-2">
                Informações do Evento
              </h2>

              <div className="space-y-2">
                <p className="flex items-center text-gray-700">
                  <svg
                    className="w-5 h-5 mr-2"
                    fill="currentColor"
                    viewBox="0 0 20 20"
                  >
                    <path
                      fillRule="evenodd"
                      d="M17.707 9.293a1 1 0 010 1.414l-7 7a1 1 0 01-1.414 0l-7-7A.997.997 0 012 10V5a3 3 0 013-3h5c.256 0 .512.098.707.293l7 7zM5 6a1 1 0 100-2 1 1 0 000 2z"
                      clipRule="evenodd"
                    ></path>
                  </svg>
                  <span className="font-medium">Local:</span> {evento.cidade},{" "}
                  {evento.estado}
                </p>

                <p className="flex items-center text-gray-700">
                  <svg
                    className="w-5 h-5 mr-2"
                    fill="currentColor"
                    viewBox="0 0 20 20"
                  >
                    <path
                      fillRule="evenodd"
                      d="M6 2a1 1 0 00-1 1v1H4a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-1V3a1 1 0 10-2 0v1H7V3a1 1 0 00-1-1zm0 5a1 1 0 000 2h8a1 1 0 100-2H6z"
                      clipRule="evenodd"
                    ></path>
                  </svg>
                  <span className="font-medium">Data:</span>{" "}
                  {formatarData(evento.datas_realizacao)}
                </p>

                <p className="flex items-center text-gray-700">
                  <svg
                    className="w-5 h-5 mr-2"
                    fill="currentColor"
                    viewBox="0 0 20 20"
                  >
                    <path
                      fillRule="evenodd"
                      d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z"
                      clipRule="evenodd"
                    ></path>
                  </svg>
                  <span className="font-medium">Distâncias:</span>{" "}
                  {evento.distanciasFormatadas}
                </p>

                {evento.categorias_premiadas && (
                  <div className="flex items-start text-gray-700">
                    <svg
                      className="w-5 h-5 mt-1 mr-2"
                      fill="currentColor"
                      viewBox="0 0 20 20"
                    >
                      <path
                        fillRule="evenodd"
                        d="M17.707 9.293a1 1 0 010 1.414l-7 7a1 1 0 01-1.414 0l-7-7A.997.997 0 012 10V5a3 3 0 013-3h5c.256 0 .512.098.707.293l7 7zM5 6a1 1 0 100-2 1 1 0 000 2z"
                        clipRule="evenodd"
                      ></path>
                    </svg>
                    <div>
                      <span className="font-medium block">
                        Categorias premiadas:
                      </span>
                      <ul className="list-disc list-inside mt-1 space-y-1 text-sm">
                        {evento.categorias_premiadas
                          .split(",")
                          .map((categoria, index) => (
                            <li key={index}>{categoria.trim()}</li>
                          ))}
                      </ul>
                    </div>
                  </div>
                )}

                <p className="flex items-center text-gray-700">
                  <svg
                    className="w-5 h-5 mr-2"
                    fill="currentColor"
                    viewBox="0 0 20 20"
                  >
                    <path
                      fillRule="evenodd"
                      d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                      clipRule="evenodd"
                    ></path>
                  </svg>
                  <span className="font-medium">Organizador:</span>{" "}
                  {evento.organizador || "Não informado"}
                </p>
              </div>
            </div>

            <div>
              <h2 className="text-xl font-semibold mb-2">
                Detalhes Adicionais
              </h2>

              <div className="space-y-2">
                <p className="flex items-center text-gray-700">
                  <svg
                    className="w-5 h-5 mr-2"
                    fill="currentColor"
                    viewBox="0 0 20 20"
                  >
                    <path
                      fillRule="evenodd"
                      d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z"
                      clipRule="evenodd"
                    ></path>
                  </svg>
                  <span className="font-medium">Site de coleta:</span>{" "}
                  {evento.site_coleta || "Não informado"}
                </p>

                <p className="flex items-center text-gray-700">
                  <svg
                    className="w-5 h-5 mr-2"
                    fill="currentColor"
                    viewBox="0 0 20 20"
                  >
                    <path
                      fillRule="evenodd"
                      d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z"
                      clipRule="evenodd"
                    ></path>
                  </svg>
                  <span className="font-medium">Data de coleta:</span>{" "}
                  {evento.data_coleta
                    ? format(new Date(evento.data_coleta), "dd/MM/yyyy", {
                        locale: ptBR,
                      })
                    : "Não informada"}
                </p>

                {evento.importado_em && (
                  <p className="flex items-center text-gray-700">
                    <svg
                      className="w-5 h-5 mr-2"
                      fill="currentColor"
                      viewBox="0 0 20 20"
                    >
                      <path
                        fillRule="evenodd"
                        d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z"
                        clipRule="evenodd"
                      ></path>
                    </svg>
                    <span className="font-medium">Importado em:</span>{" "}
                    {format(new Date(evento.importado_em), "dd/MM/yyyy", {
                      locale: ptBR,
                    })}
                  </p>
                )}

                {evento.atualizado_em && (
                  <p className="flex items-center text-gray-700">
                    <svg
                      className="w-5 h-5 mr-2"
                      fill="currentColor"
                      viewBox="0 0 20 20"
                    >
                      <path
                        fillRule="evenodd"
                        d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z"
                        clipRule="evenodd"
                      ></path>
                    </svg>
                    <span className="font-medium">Atualizado em:</span>{" "}
                    {format(new Date(evento.atualizado_em), "dd/MM/yyyy", {
                      locale: ptBR,
                    })}
                  </p>
                )}

                {evento.origem && (
                  <p className="flex items-center text-gray-700">
                    <svg
                      className="w-5 h-5 mr-2"
                      fill="currentColor"
                      viewBox="0 0 20 20"
                    >
                      <path
                        fillRule="evenodd"
                        d="M10 2a1 1 0 00-1 1v1a1 1 0 002 0V3a1 1 0 00-1-1zM4 4h3a3 3 0 006 0h3a2 2 0 012 2v9a2 2 0 01-2 2H4a2 2 0 01-2-2V6a2 2 0 012-2zm2.5 7a1.5 1.5 0 100-3 1.5 1.5 0 000 3zm2.45 4a2.5 2.5 0 10-4.9 0h4.9zM12 9a1 1 0 100 2h3a1 1 0 100-2h-3zm-1 4a1 1 0 011-1h2a1 1 0 110 2h-2a1 1 0 01-1-1z"
                        clipRule="evenodd"
                      ></path>
                    </svg>
                    <span className="font-medium">Origem:</span> {evento.origem}
                  </p>
                )}
              </div>
            </div>
          </div>

          <div className="mt-6">
            <a
              href={evento.url_inscricao}
              target="_blank"
              rel="noopener noreferrer"
              className={`inline-block px-6 py-3 rounded font-medium text-white ${
                eventoRealizado
                  ? "bg-gray-500 cursor-not-allowed"
                  : "bg-blue-600 hover:bg-blue-700"
              }`}
              onClick={(e) => {
                if (eventoRealizado) {
                  e.preventDefault();
                  alert("Este evento já foi realizado.");
                }
              }}
            >
              {eventoRealizado ? "Evento já realizado" : "Fazer inscrição"}
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
