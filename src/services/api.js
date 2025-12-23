import API_URL from '../config/api';

export const EventosService = {
    // Buscar todos os eventos
    post: async () => {
        const response = await fetch(`${API_URL}/eventos`);
        if (!response.ok) {
            throw new Error(`Erro ao buscar eventos: ${response.status}`);
        }
        return response.json();
    },

    // Buscar um evento pelo ID
    // getById: async (id) => {
    //     // https://correpb.onrender.com/eventos?page=1&size=50
    //     const response = await fetch(`${API_URL}/eventos?page=${id}&size=50`);
    //     if (!response.ok) {
    //         throw new Error(`Evento não encontrado: ${response.status}`);
    //     }
    //     return response.json();
    //     console.log(response.json());
    // },
    //
    getById: async (id) => {
        // https://correpb.onrender.com/eventos?page=1&size=50
        const response = await fetch(`${API_URL}/docs`);
        if (!response.ok) {
            throw new Error(`Evento não encontrado: ${response.status}`);
        }
        console.log(response.json());
        return response.json();
    },


    // Buscar eventos com filtros
    // getFiltered: async (params) => {
    //     const queryString = new URLSearchParams(params).toString();
    //     const response = await fetch(`${API_URL}/eventos?${queryString}`);
    //     if (!response.ok) {
    //         throw new Error(`Erro ao buscar eventos: ${response.status}`);
    //     }
    //     return response.json();
    // }
};
