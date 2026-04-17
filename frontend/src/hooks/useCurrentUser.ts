import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { getCurrentUser, type CurrentUser } from '../api/auth';

// TanStack Query wrapper for GET /api/v1/me. Pages can call this directly
// when they need the user, sharing the cached response across renders.
export function useCurrentUser(): UseQueryResult<CurrentUser> {
  return useQuery({
    queryKey: ['currentUser'],
    queryFn: getCurrentUser,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}
