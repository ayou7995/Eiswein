import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { EisweinApiError, NetworkError } from '../api/errors';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { DISCLAIMER_TEXT, ROUTES } from '../lib/constants';

const loginFormSchema = z.object({
  username: z.string().min(1, '請輸入使用者名稱'),
  password: z.string().min(1, '請輸入密碼'),
});

type LoginFormValues = z.infer<typeof loginFormSchema>;

// Error details per B6: invalid_password carries attempts_remaining, locked_out
// carries retry_after_seconds. Both surfaces require dedicated messaging.
function formatAuthError(error: unknown): string {
  if (error instanceof EisweinApiError) {
    if (error.code === 'invalid_password') {
      const remaining = error.details['attempts_remaining'];
      if (typeof remaining === 'number') {
        return `${error.message}（剩餘嘗試：${remaining}）`;
      }
      return error.message;
    }
    if (error.code === 'locked_out') {
      const retryAfter = error.details['retry_after_seconds'];
      if (typeof retryAfter === 'number') {
        return `${error.message}（請於 ${retryAfter} 秒後再試）`;
      }
      return error.message;
    }
    return error.message;
  }
  if (error instanceof NetworkError) {
    return error.message;
  }
  return '登入失敗，請稍後再試。';
}

interface LocationStateLike {
  from?: unknown;
}

function readRedirectTarget(state: unknown): string {
  if (state && typeof state === 'object') {
    const candidate = (state as LocationStateLike).from;
    if (typeof candidate === 'string' && candidate.startsWith('/')) {
      return candidate;
    }
  }
  return ROUTES.DASHBOARD;
}

export function LoginPage(): JSX.Element {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [passwordVisible, setPasswordVisible] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginFormSchema),
    defaultValues: { username: '', password: '' },
  });

  const onSubmit = async (values: LoginFormValues): Promise<void> => {
    setSubmitError(null);
    try {
      await login(values.username, values.password);
      navigate(readRedirectTarget(location.state), { replace: true });
    } catch (err) {
      setSubmitError(formatAuthError(err));
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-12">
      <section
        aria-labelledby="login-heading"
        className="w-full max-w-sm rounded-lg border border-slate-800 bg-slate-900/70 p-6 shadow-xl"
      >
        <header className="mb-6 text-center">
          <h1 id="login-heading" className="text-2xl font-semibold text-slate-100">
            Eiswein
          </h1>
          <p className="mt-1 text-sm text-slate-400">個人投資決策輔助工具</p>
        </header>

        <form noValidate onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <label htmlFor="username" className="text-sm font-medium text-slate-300">
              使用者名稱
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              autoFocus
              aria-invalid={Boolean(errors.username)}
              aria-describedby={errors.username ? 'username-error' : undefined}
              {...register('username')}
              className="rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            />
            {errors.username && (
              <p id="username-error" role="alert" className="text-sm text-signal-red">
                {errors.username.message}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="password" className="text-sm font-medium text-slate-300">
              密碼
            </label>
            <div className="relative">
              <input
                id="password"
                type={passwordVisible ? 'text' : 'password'}
                autoComplete="current-password"
                aria-invalid={Boolean(errors.password)}
                aria-describedby={errors.password ? 'password-error' : undefined}
                {...register('password')}
                className="w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 pr-10 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
              />
              <button
                type="button"
                onClick={() => setPasswordVisible((prev) => !prev)}
                aria-label={passwordVisible ? '隱藏密碼' : '顯示密碼'}
                aria-pressed={passwordVisible}
                className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:rounded-md"
              >
                {passwordVisible ? (
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="h-5 w-5"
                    aria-hidden="true"
                  >
                    <path d="M3 3l18 18" />
                    <path d="M10.584 10.587a2 2 0 002.828 2.83" />
                    <path d="M9.363 5.365A9.47 9.47 0 0112 5c4.477 0 8.268 2.943 9.542 7a10.025 10.025 0 01-4.132 5.411M6.59 6.59A10.025 10.025 0 002.458 12 9.97 9.97 0 0012 19c1.66 0 3.223-.404 4.594-1.118" />
                  </svg>
                ) : (
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="h-5 w-5"
                    aria-hidden="true"
                  >
                    <path d="M2.458 12C3.732 7.943 7.523 5 12 5s8.268 2.943 9.542 7c-1.274 4.057-5.065 7-9.542 7S3.732 16.057 2.458 12z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
            {errors.password && (
              <p id="password-error" role="alert" className="text-sm text-signal-red">
                {errors.password.message}
              </p>
            )}
          </div>

          {submitError && (
            <div
              role="alert"
              aria-live="assertive"
              className="rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-sm text-signal-red"
            >
              {submitError}
            </div>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
          >
            {isSubmitting && <LoadingSpinner label="登入中…" />}
            <span>{isSubmitting ? '登入中…' : '登入'}</span>
          </button>
        </form>

        <footer className="mt-8 text-center text-xs text-slate-500">{DISCLAIMER_TEXT}</footer>
      </section>
    </main>
  );
}
