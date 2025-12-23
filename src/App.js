import { BrowserRouter as Router, Routes, Route, Link } from "react-router-dom";
import Home from "./pages/Home";
import EventoDetalhes from "./pages/EventoDetalhes";
import Dashboard from "./pages/Dashboard";

function App() {
  return (
    <Router>
      <header className="bg-gray-800 text-white py-4">
        <div className="max-w-7xl mx-auto px-4 flex justify-between items-center">
          <h1 className="text-2xl font-[Bebas Neue,sans-serif]">Corridas PB</h1>
          <nav className="flex gap-4 text-sm">
            <Link to="/" className="hover:underline">
              Eventos
            </Link>
            <Link to="/dashboard" className="hover:underline">
              Dashboard
            </Link>
          </nav>
        </div>
      </header>

      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/evento/:id" element={<EventoDetalhes />} />
      </Routes>
    </Router>
  );
}

export default App;
