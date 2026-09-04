import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { Dashboard } from "./pages/Dashboard";
import { Roster } from "./pages/Roster";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Roster />} />
        <Route path="/athlete/:slug" element={<Dashboard />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
