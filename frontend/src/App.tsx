import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/AppLayout";
import { LoadingState } from "./components/Ui";

const DashboardPage = lazy(() => import("./pages/DashboardPage").then((module) => ({ default: module.DashboardPage })));
const HandsPage = lazy(() => import("./pages/HandsPage").then((module) => ({ default: module.HandsPage })));
const LeaksPage = lazy(() => import("./pages/LeaksPage").then((module) => ({ default: module.LeaksPage })));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage })));
const SessionsPage = lazy(() => import("./pages/SessionsPage").then((module) => ({ default: module.SessionsPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));
const TournamentDetailPage = lazy(() => import("./pages/TournamentDetailPage").then((module) => ({ default: module.TournamentDetailPage })));
const TournamentsPage = lazy(() => import("./pages/TournamentsPage").then((module) => ({ default: module.TournamentsPage })));

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
          <Route path="parametres" element={<SettingsPage />} />
          <Route path="dashboard" element={<Navigate replace to="/" />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
