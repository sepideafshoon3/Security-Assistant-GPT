import { API_BASE } from "./chat";

export interface UserPublic {
  id: string;
  email: string;
}

export interface AuthResponse {
  access_token: string;
  user: UserPublic;
}

const TOKEN_KEY = "sa_access_token";
const USER_KEY = "sa_user";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): UserPublic | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as UserPublic;
  } catch {
    return null;
  }
}

function persistAuth(auth: AuthResponse): void {
  localStorage.setItem(TOKEN_KEY, auth.access_token);
  localStorage.setItem(USER_KEY, JSON.stringify(auth.user));
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

async function parseAuthResponse(res: Response): Promise<AuthResponse> {
  const text = await res.text();
  if (!res.ok) {
    let detail = text;
    try {
      detail = JSON.parse(text)?.detail ?? text;
    } catch {
      // keep raw text
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return JSON.parse(text) as AuthResponse;
}

export async function signup(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const auth = await parseAuthResponse(res);
  persistAuth(auth);
  return auth;
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const auth = await parseAuthResponse(res);
  persistAuth(auth);
  return auth;
}

export async function fetchMe(): Promise<UserPublic> {
  const token = getToken();
  if (!token) throw new Error("Not authenticated");

  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    clearAuth();
    throw new Error("Session expired");
  }
  return res.json();
}

export function logout(): void {
  clearAuth();
}