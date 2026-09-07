import { useCallback, useEffect, useState } from "react";
import {
  getToken,
  getStoredUser,
  login as apiLogin,
  signup as apiSignup,
  logout as apiLogout,
  fetchMe,
  type UserPublic,
} from "../api/auth";

export function useAuth() {
  const [user, setUser] = useState<UserPublic | null>(() => getStoredUser());
  const [isCheckingSession, setIsCheckingSession] = useState<boolean>(
    () => !!getToken(),
  );

  // On mount, if a token exists, confirm it's still valid against /auth/me.
  useEffect(() => {
    const token = getToken();
    if (!token) {
      setIsCheckingSession(false);
      return;
    }
    fetchMe()
      .then((me) => setUser(me))
      .catch(() => setUser(null))
      .finally(() => setIsCheckingSession(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const auth = await apiLogin(email, password);
    setUser(auth.user);
    return auth;
  }, []);

  const signup = useCallback(async (email: string, password: string) => {
    const auth = await apiSignup(email, password);
    setUser(auth.user);
    return auth;
  }, []);

  const logout = useCallback(() => {
    apiLogout();
    setUser(null);
  }, []);

  return {
    user,
    isAuthenticated: !!user,
    isCheckingSession,
    login,
    signup,
    logout,
  };
}