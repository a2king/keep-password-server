import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { SiteLayout } from "./layout/SiteLayout";
import { HomePage } from "./pages/HomePage";
import { DownloadPage } from "./pages/DownloadPage";
import { DocsPage } from "./pages/DocsPage";
import { SecurityPage } from "./pages/SecurityPage";
import { LegalPage } from "./pages/LegalPage";
import { ChangelogPage } from "./pages/ChangelogPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { AccountPage } from "./pages/AccountPage";
import { AdminPage } from "./pages/AdminPage";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { loading, me } = useAuth();
  if (loading) return null;
  if (!me) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<SiteLayout />}>
          <Route index element={<HomePage />} />
          <Route path="download" element={<DownloadPage />} />
          <Route path="docs" element={<DocsPage />} />
          <Route path="security" element={<SecurityPage />} />
          <Route path="legal" element={<LegalPage />} />
          <Route path="changelog" element={<ChangelogPage />} />
          <Route path="login" element={<LoginPage />} />
          <Route path="register" element={<RegisterPage />} />
          <Route
            path="account"
            element={
              <RequireAuth>
                <AccountPage />
              </RequireAuth>
            }
          />
          <Route
            path="admin"
            element={
              <RequireAuth>
                <AdminPage />
              </RequireAuth>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
