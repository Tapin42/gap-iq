import { Navigate, Route, Routes } from "react-router-dom";

import { Dashboard } from "./pages/Dashboard";
import { Roster } from "./pages/Roster";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Roster />} />
      <Route path="/athlete/:slug" element={<Dashboard />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
