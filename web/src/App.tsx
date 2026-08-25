import { Navigate, Route, Routes } from "react-router-dom";

// Routes are filled in by the roster and dashboard work; this shell exists so the
// scaffold builds and deploys from the very first commit.
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Placeholder />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function Placeholder() {
  return (
    <main className="flex min-h-full flex-col items-center justify-center gap-3 p-8 text-center">
      <h1 className="text-3xl font-bold tracking-tight">Gap IQ</h1>
      <p className="text-ink-muted max-w-sm text-balance">
        Live race tracking. The roster and athlete dashboard land next.
      </p>
    </main>
  );
}
