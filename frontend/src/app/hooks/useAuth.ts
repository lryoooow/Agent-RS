import { useEffect, useState } from "react";
import {
  fetchMe,
  login,
  logout,
  register,
  type AuthUser,
} from "../lib/auth-api";

export function useAuth(endpoint: string) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      setUser(await fetchMe(endpoint));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  async function signIn(email: string, password: string) {
    setLoading(true);
    setError("");
    try {
      setUser(await login(endpoint, email, password));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      throw err;
    } finally {
      setLoading(false);
    }
  }

  async function signUp(email: string, password: string, name: string) {
    setLoading(true);
    setError("");
    try {
      setUser(await register(endpoint, email, password, name));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      throw err;
    } finally {
      setLoading(false);
    }
  }

  async function signOut() {
    setLoading(true);
    setError("");
    try {
      await logout(endpoint);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [endpoint]);

  return { user, loading, error, refresh, signIn, signUp, signOut };
}
