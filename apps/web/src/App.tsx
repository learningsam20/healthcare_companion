import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { LoadingBlock } from "./components/primitives";
import { useAuth } from "./lib/auth";
import type { Role } from "./lib/types";
import { ForbiddenPage, NotFoundPage } from "./pages/StatusPages";

const DashboardPage = lazy(() =>
  import("./pages/DashboardPage").then((module) => ({ default: module.DashboardPage })),
);
const ChatPage = lazy(() =>
  import("./pages/ChatPage").then((module) => ({ default: module.ChatPage })),
);
const AppointmentsPage = lazy(() =>
  import("./pages/AppointmentsPage").then((module) => ({ default: module.AppointmentsPage })),
);
const PatientsPage = lazy(() =>
  import("./pages/PatientsPage").then((module) => ({ default: module.PatientsPage })),
);
const PatientFhirPage = lazy(() =>
  import("./pages/PatientFhirPage").then((module) => ({ default: module.PatientFhirPage })),
);
const RecordsPage = lazy(() =>
  import("./pages/RecordsPage").then((module) => ({ default: module.RecordsPage })),
);
const CareCirclePage = lazy(() =>
  import("./pages/CareCirclePage").then((module) => ({ default: module.CareCirclePage })),
);
const ScribePage = lazy(() =>
  import("./pages/ScribePage").then((module) => ({ default: module.ScribePage })),
);
const NotesPage = lazy(() =>
  import("./pages/NotesPage").then((module) => ({ default: module.NotesPage })),
);
const PharmacyPage = lazy(() =>
  import("./pages/PharmacyPage").then((module) => ({ default: module.PharmacyPage })),
);
const ReviewQueuePage = lazy(() =>
  import("./pages/ReviewQueuePage").then((module) => ({ default: module.ReviewQueuePage })),
);
const EscalationsPage = lazy(() =>
  import("./pages/EscalationsPage").then((module) => ({ default: module.EscalationsPage })),
);
const FrontDeskPage = lazy(() =>
  import("./pages/FrontDeskPage").then((module) => ({ default: module.FrontDeskPage })),
);
const WaitlistPage = lazy(() =>
  import("./pages/WaitlistPage").then((module) => ({ default: module.WaitlistPage })),
);
const AnalyticsPage = lazy(() =>
  import("./pages/AnalyticsPage").then((module) => ({ default: module.AnalyticsPage })),
);
const NotificationsPage = lazy(() =>
  import("./pages/NotificationsPage").then((module) => ({ default: module.NotificationsPage })),
);
const GovernancePage = lazy(() =>
  import("./pages/GovernancePage").then((module) => ({ default: module.GovernancePage })),
);
const OpsPage = lazy(() =>
  import("./pages/OpsPage").then((module) => ({ default: module.OpsPage })),
);
const SettingsPage = lazy(() =>
  import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })),
);

function Guarded({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { hasRole } = useAuth();
  if (!roles.some((role) => hasRole(role))) return <ForbiddenPage />;
  return <>{children}</>;
}

export function App() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <>
        <a className="skip-link" href="#main-content">
          Skip to main content
        </a>
        <Routes>
          <Route path="/auth/callback" element={<Navigate to="/" replace />} />
          <Route element={<AppShell />}>
          <Route index element={<DashboardPage />} />
          <Route
            path="chat"
            element={
              <Guarded roles={["patient", "caregiver", "doctor", "front_desk", "admin"]}>
                <ChatPage />
              </Guarded>
            }
          />
          <Route
            path="appointments"
            element={
              <Guarded roles={["patient", "caregiver", "doctor", "front_desk", "admin"]}>
                <AppointmentsPage />
              </Guarded>
            }
          />
          <Route
            path="patients"
            element={
              <Guarded roles={["front_desk", "doctor", "compliance", "admin"]}>
                <PatientsPage />
              </Guarded>
            }
          />
          <Route
            path="patients/:patientId/fhir"
            element={
              <Guarded roles={["front_desk", "doctor", "compliance", "admin"]}>
                <PatientFhirPage />
              </Guarded>
            }
          />
          <Route
            path="records"
            element={
              <Guarded roles={["patient", "caregiver", "doctor", "front_desk", "admin"]}>
                <RecordsPage />
              </Guarded>
            }
          />
          <Route
            path="care-circle"
            element={
              <Guarded roles={["patient", "caregiver", "admin"]}>
                <CareCirclePage />
              </Guarded>
            }
          />
          <Route
            path="scribe"
            element={
              <Guarded roles={["doctor"]}>
                <ScribePage />
              </Guarded>
            }
          />
          <Route
            path="notes"
            element={
              <Guarded
                roles={["patient", "caregiver", "doctor", "pharmacist", "compliance", "admin"]}
              >
                <NotesPage />
              </Guarded>
            }
          />
          <Route
            path="pharmacy"
            element={
              <Guarded roles={["pharmacist", "front_desk", "admin"]}>
                <PharmacyPage />
              </Guarded>
            }
          />
          <Route
            path="review-queue"
            element={
              <Guarded roles={["doctor", "pharmacist", "front_desk", "compliance", "admin"]}>
                <ReviewQueuePage />
              </Guarded>
            }
          />
          <Route
            path="escalations"
            element={
              <Guarded roles={["doctor", "front_desk", "compliance", "admin"]}>
                <EscalationsPage />
              </Guarded>
            }
          />
          <Route
            path="front-desk"
            element={
              <Guarded roles={["front_desk", "admin"]}>
                <FrontDeskPage />
              </Guarded>
            }
          />
          <Route
            path="waitlist"
            element={
              <Guarded roles={["front_desk", "admin"]}>
                <WaitlistPage />
              </Guarded>
            }
          />
          <Route
            path="analytics"
            element={
              <Guarded roles={["compliance", "admin"]}>
                <AnalyticsPage />
              </Guarded>
            }
          />
          <Route
            path="ops"
            element={
              <Guarded roles={["admin"]}>
                <OpsPage />
              </Guarded>
            }
          />
          <Route path="notifications" element={<NotificationsPage />} />
          <Route
            path="governance"
            element={
              <Guarded roles={["compliance", "admin"]}>
                <GovernancePage />
              </Guarded>
            }
          />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="403" element={<ForbiddenPage />} />
          <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </>
    </Suspense>
  );
}
