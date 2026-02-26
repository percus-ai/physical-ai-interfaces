<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { Button } from 'bits-ui';

  import { api } from '$lib/api/client';

  type AuthStatus = {
    authenticated: boolean;
    user_id?: string;
    expires_at?: number;
    session_expires_at?: number;
  };

  let status: AuthStatus | null = $state(null);
  let loading = $state(true);
  let submitting = $state(false);
  let error: string | null = $state(null);
  let email = $state('');
  let password = $state('');
  const mode = $derived.by(() => {
    const next = page.url.searchParams.get('mode');
    return next === 'login' || next === 'logout' ? next : null;
  });
  const refreshStatus = async () => {
    loading = true;
    try {
      status = await api.auth.status();
    } catch (err) {
      status = { authenticated: false };
      error = err instanceof Error ? err.message : '認証状態の取得に失敗しました。';
    } finally {
      loading = false;
    }
  };

  const handleLogin = async (event?: Event) => {
    event?.preventDefault();
    if (!email || !password) {
      error = 'メールアドレスとパスワードを入力してください。';
      return;
    }
    submitting = true;
    error = null;
    try {
      await api.auth.login(email, password);
      await refreshStatus();
      if (status?.authenticated) {
        goto('/');
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'ログインに失敗しました。';
    } finally {
      submitting = false;
    }
  };

  const handleLogout = async () => {
    submitting = true;
    error = null;
    try {
      await api.auth.logout();
      status = { authenticated: false };
      await refreshStatus();
      if (status?.authenticated) {
        error = 'ログアウトに失敗しました。';
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'ログアウトに失敗しました。';
    } finally {
      submitting = false;
    }
  };

  onMount(refreshStatus);
</script>

<section class="card-strong p-8">
  <p class="section-title">Auth</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">
        {mode === 'logout' ? 'ログアウト' : status?.authenticated ? 'セッション管理' : 'ログイン'}
      </h1>
      <p class="mt-2 text-sm text-slate-600">
        {mode === 'logout'
          ? '現在のセッションを終了します。'
          : status?.authenticated
            ? '現在のセッションを確認・終了できます。'
            : 'アカウントでサインインしてください。'}
      </p>
    </div>
  </div>
</section>

{#if loading}
  <section class="card p-6 text-sm text-slate-500">認証状態を確認中...</section>
{:else if status?.authenticated && mode !== 'login'}
  <section class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">現在のセッション</h2>
    <div class="mt-4 space-y-3 text-sm text-slate-600">
      <div>
        <p class="label">ユーザーID</p>
        <p class="text-base font-semibold text-slate-800">{status.user_id ?? '-'}</p>
      </div>
      <div>
        <p class="label">セッション有効期限</p>
        <p class="text-base font-semibold text-slate-800">
          {status.session_expires_at
            ? new Date(status.session_expires_at * 1000).toLocaleString()
            : status.expires_at
              ? new Date(status.expires_at * 1000).toLocaleString()
              : '-'}
        </p>
        {#if status.expires_at}
          <p class="mt-1 text-xs text-slate-500">
            アクセストークン期限:
            {new Date(status.expires_at * 1000).toLocaleString()}
          </p>
        {/if}
      </div>
    </div>
    {#if error}
      <p class="mt-4 text-sm text-rose-600">{error}</p>
    {/if}
    <div class="mt-6 flex flex-wrap gap-3">
      <Button.Root
        class="btn-primary"
        type="button"
        onclick={handleLogout}
        disabled={submitting}
        aria-busy={submitting}
      >
        ログアウト
      </Button.Root>
      <Button.Root class="btn-ghost" href="/">戻る</Button.Root>
    </div>
  </section>
{:else if mode === 'logout'}
  <section class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">ログアウト</h2>
    <p class="mt-2 text-sm text-slate-600">ログイン中のセッションがありません。</p>
    <div class="mt-6 flex flex-wrap gap-3">
      <Button.Root class="btn-primary" href="/auth?mode=login">ログインへ</Button.Root>
      <Button.Root class="btn-ghost" href="/">戻る</Button.Root>
    </div>
  </section>
{:else}
  <section class="card p-6">
    <h2 class="text-xl font-semibold text-slate-900">ログイン情報</h2>
    <form class="mt-4 grid gap-4" onsubmit={handleLogin}>
      <label class="text-sm font-semibold text-slate-700">
        <span class="label">メールアドレス</span>
        <input class="input mt-2" type="email" bind:value={email} autocomplete="email" />
      </label>
      <label class="text-sm font-semibold text-slate-700">
        <span class="label">パスワード</span>
        <input
          class="input mt-2"
          type="password"
          bind:value={password}
          autocomplete="current-password"
        />
      </label>
      {#if error}
        <p class="text-sm text-rose-600">{error}</p>
      {/if}
      <div class="mt-2 flex flex-wrap gap-3">
        <Button.Root class="btn-primary" type="submit" disabled={submitting}>
          ログイン
        </Button.Root>
      </div>
    </form>
  </section>
{/if}
