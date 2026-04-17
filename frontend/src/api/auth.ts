import { z } from 'zod';
import { apiRequest } from './client';

// STAFF_REVIEW_DECISIONS.md B1: login JWT is set via Set-Cookie (httpOnly),
// NEVER in the response body. The body only confirms success + minimal profile.
export const loginResponseSchema = z.object({
  ok: z.literal(true),
  user: z.object({
    username: z.string(),
    is_admin: z.boolean(),
  }),
});

export type LoginResponse = z.infer<typeof loginResponseSchema>;

export const refreshResponseSchema = z.object({
  ok: z.literal(true),
});

export const logoutResponseSchema = z.object({
  ok: z.literal(true),
});

export const currentUserSchema = z.object({
  username: z.string(),
  is_admin: z.boolean(),
});

export type CurrentUser = z.infer<typeof currentUserSchema>;

export function login(password: string): Promise<LoginResponse> {
  return apiRequest('/api/v1/login', {
    method: 'POST',
    body: { password },
    schema: loginResponseSchema,
    skipAuthRefresh: true,
  });
}

export function logout(): Promise<z.infer<typeof logoutResponseSchema>> {
  return apiRequest('/api/v1/logout', {
    method: 'POST',
    schema: logoutResponseSchema,
    skipAuthRefresh: true,
  });
}

export function refreshToken(): Promise<z.infer<typeof refreshResponseSchema>> {
  return apiRequest('/api/v1/refresh', {
    method: 'POST',
    schema: refreshResponseSchema,
    skipAuthRefresh: true,
  });
}

export function getCurrentUser(): Promise<CurrentUser> {
  return apiRequest('/api/v1/me', {
    method: 'GET',
    schema: currentUserSchema,
  });
}
