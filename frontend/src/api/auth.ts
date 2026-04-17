import { z } from 'zod';
import { apiRequest } from './client';

// All auth responses share a common envelope: {ok: true, user?: UserSummary}.
// Matches backend LoginResponse / MeResponse / SessionResponse shapes.
// JWT travels via Set-Cookie (httpOnly) per B1 — never in the body.

const userSummarySchema = z.object({
  username: z.string(),
  is_admin: z.boolean(),
});

export type CurrentUser = z.infer<typeof userSummarySchema>;

export const loginResponseSchema = z.object({
  ok: z.literal(true),
  user: userSummarySchema,
});

export type LoginResponse = z.infer<typeof loginResponseSchema>;

export const sessionResponseSchema = z.object({
  ok: z.literal(true),
});

export const meResponseSchema = z.object({
  ok: z.literal(true),
  user: userSummarySchema,
});

export function login(username: string, password: string): Promise<LoginResponse> {
  return apiRequest('/api/v1/login', {
    method: 'POST',
    body: { username, password },
    schema: loginResponseSchema,
    skipAuthRefresh: true,
  });
}

export function logout(): Promise<z.infer<typeof sessionResponseSchema>> {
  return apiRequest('/api/v1/logout', {
    method: 'POST',
    schema: sessionResponseSchema,
    skipAuthRefresh: true,
  });
}

export function refreshToken(): Promise<z.infer<typeof sessionResponseSchema>> {
  return apiRequest('/api/v1/refresh', {
    method: 'POST',
    schema: sessionResponseSchema,
    skipAuthRefresh: true,
  });
}

export async function getCurrentUser(): Promise<CurrentUser> {
  const response = await apiRequest('/api/v1/me', {
    method: 'GET',
    schema: meResponseSchema,
  });
  return response.user;
}
