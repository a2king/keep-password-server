import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchMe, getToken, setToken, type MeResponse } from "./api";

type AuthState = {
  loading: boolean;
  me: MeResponse | null;
  refresh: () => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [me, setMe] = useState<MeResponse | null>(null);

  const refresh = async () => {
    if (!getToken()) {
      setMe(null);
      setLoading(false);
      return;
    }
    try {
      setMe(await fetchMe());
    } catch {
      setToken(null);
      setMe(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      loading,
      me,
      refresh,
      logout: () => {
        setToken(null);
        setMe(null);
      },
    }),
    [loading, me],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside provider");
  return ctx;
}
