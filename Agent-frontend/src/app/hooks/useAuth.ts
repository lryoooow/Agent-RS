import { useEffect, useRef, useState } from "react";
import { fetchMe, login, logout, register, type AuthUser } from "../lib/auth-api";
import { ApiError } from "../lib/http";
import { advanceAuthEpoch, currentAuthEpoch, subscribeAuthExpiry } from "../lib/auth-session";

export function useAuth(endpoint: string) {
  const [user,setUser]=useState<AuthUser|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const version=useRef(0);
  useEffect(() => subscribeAuthExpiry(() => {
    ++version.current; setUser(null); setLoading(false); setError("");
  }), []);
  async function perform(action: () => Promise<AuthUser|null>, transition=false, quiet401=false) {
    const operation=++version.current;
    const authEpoch=transition ? advanceAuthEpoch() : currentAuthEpoch();
    if (transition) setUser(null);
    setLoading(true); setError("");
    try {
      const next=await action();
      if (operation===version.current && authEpoch===currentAuthEpoch()) setUser(next);
    } catch (err) {
      if (operation===version.current && authEpoch===currentAuthEpoch()) {
        if (!(quiet401 && err instanceof ApiError && err.status===401)) setError(err instanceof Error ? err.message : String(err));
        setUser(null);
      }
      if (!quiet401) throw err;
    } finally { if (operation===version.current) setLoading(false); }
  }
  async function refresh() { await perform(fetchMe,false,true); }
  async function signIn(email: string,password: string) { await perform(() => login(email,password),true); }
  async function signUp(email: string,password: string,name: string) { await perform(() => register(email,password,name),true); }
  async function signOut() { try { await perform(async () => { await logout(); return null; },true); } catch { /* error displayed */ } }
  useEffect(() => { void refresh(); return () => { ++version.current; }; },[endpoint]);
  return {user,loading,error,refresh,signIn,signUp,signOut};
}
