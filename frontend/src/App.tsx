import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/AppLayout";
import { ErrorState, LoadingState } from "./components/Ui";
import { useSafety } from "./contexts/SafetyContext";

const DashboardPage = lazy(() => import("./pages/DashboardPage").then((module) => ({ default: module.DashboardPage })));
const CommunityPage = lazy(() => import("./pages/CommunityPage").then((module) => ({ default: module.CommunityPage })));
const HandsPage = lazy(() => import("./pages/HandsPage").then((module) => ({ default: module.HandsPage })));
const LeaksPage = lazy(() => import("./pages/LeaksPage").then((module) => ({ default: module.LeaksPage })));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage })));
const SessionsPage = lazy(() => import("./pages/SessionsPage").then((module) => ({ default: module.SessionsPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));
const TournamentDetailPage = lazy(() => import("./pages/TournamentDetailPage").then((module) => ({ default: module.TournamentDetailPage })));
const TournamentsPage = lazy(() => import("./pages/TournamentsPage").then((module) => ({ default: module.TournamentsPage })));

function CommunityRoute() {
  const { status, error, refresh } = useSafety();

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 1_500);
    return () => window.clearInterval(timer);
  }, [refresh]);

  if (error) {
    return <ErrorState error={new Error("Le statut de sécurité global est indisponible. La page Communauté a été démontée par précaution.")} retry={refresh} />;
  }
  if (!status) return <LoadingState label="Confirmation de la sécurité post-session…" />;
  return <CommunityPage />;
}

export default function App() {
  return (
    <Suspense fallback={<div className="route-loader"><LoadingState /></div>}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="parties" element={<TournamentsPage />} />
          <Route path="parties/:id" element={<TournamentDetailPage />} />
          <Route path="mains" element={<HandsPage />} />
          <Route path="sessions" element={<SessionsPage />} />
          <Route path="leaks" element={<LeaksPage />} />
          <Route path="communaute" element={<CommunityRoute />} />
          <Route path="parametres" element={<SettingsPage />} />
          <Route path="dashboard" element={<Navigate replace to="/" />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
