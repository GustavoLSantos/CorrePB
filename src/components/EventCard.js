import React from "react";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { Link } from "react-router-dom";

export default function EventCard({ evento }) {
  let dataEvento;
  if (Array.isArray(evento.datas_realizacao) && evento.datas_realizacao.length > 0) {
    dataEvento = new Date(evento.datas_realizacao[0]);
  } else if (evento.datas_realizacao) {
    dataEvento = new Date(evento.datas_realizacao);
  } else {
    dataEvento = new Date(evento.data_realizacao || Date.now());
  }

  const hoje = new Date();
  const eventoRealizado = dataEvento < hoje;

  const dataFormatada = format(dataEvento, "dd 'de' MMMM 'de' yyyy", { locale: ptBR });

  const distanciasExibicao = evento.distanciasFormatadas || evento.distancias;

  return (
      <div className="bg-white rounded-lg shadow-md overflow-hidden hover:shadow-lg transition-shadow duration-300">
        <Link to={`/evento/${evento._id}`} className="block relative">
          <img
              src={evento.url_imagem || "/images/default-event.jpg"}
              alt={evento.nome_evento}
              className="w-full h-48 object-cover"
              onError={(e) => {
                e.target.onerror = null;
                e.target.src = "/images/default-event.jpg";
              }}
          />

          {/* Badge de status */}
          <div
              className={`absolute top-2 right-2 px-2 py-1 rounded text-xs font-bold ${
                  eventoRealizado
                      ? "bg-gray-500 text-white"
                      : "bg-green-500 text-white"
              }`}
          >
            {eventoRealizado ? "Realizado" : "Pendente"}
          </div>
        </Link>

        <div className="p-4">
          <Link to={`/evento/${evento._id}`} className="block">
            <h3 className="text-xl font-bold mb-2 line-clamp-2 hover:text-blue-600 transition-colors">{evento.nome_evento}</h3>
          </Link>

          <div className="mb-2 text-sm text-gray-600">
            <div className="flex items-center mb-1">
              <svg className="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M6 2a1 1 0 00-1 1v1H4a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V6a2 2 0 00-2-2h-1V3a1 1 0 10-2 0v1H7V3a1 1 0 00-1-1zm0 5a1 1 0 000 2h8a1 1 0 100-2H6z" clipRule="evenodd"></path>
              </svg>
              {dataFormatada}
            </div>

            <div className="flex items-center mb-1">
              <svg className="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clipRule="evenodd"></path>
              </svg>
              {evento.cidade}, {evento.estado}
            </div>

            <div className="flex items-center mb-1">
              <svg className="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd"></path>
              </svg>
              {distanciasExibicao}
            </div>

            <div className="flex items-center">
              <svg className="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd"></path>
              </svg>
              {evento.organizador}
            </div>
          </div>

          <div className="flex space-x-2">
            <Link
                to={`/evento/${evento._id}`}
                className="flex-1 block text-center py-2 rounded font-medium bg-gray-800 text-white hover:bg-gray-700"
            >
              Ver detalhes
            </Link>

            <a
                href={evento.url_inscricao}
                target="_blank"
                rel="noopener noreferrer"
                className={`flex-1 block text-center py-2 rounded font-medium ${
                    eventoRealizado
                        ? "bg-gray-200 text-gray-600 cursor-not-allowed"
                        : "bg-blue-600 text-white hover:bg-blue-700"
                }`}
                onClick={(e) => {
                  if (eventoRealizado) {
                    e.preventDefault();
                  }
                }}
            >
              {eventoRealizado ? "Realizado" : "Inscrever-se"}
            </a>
          </div>
        </div>
      </div>
  );
}
