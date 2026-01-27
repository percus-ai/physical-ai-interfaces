<script lang="ts">
  import { Button } from 'bits-ui';
</script>

<section class="card-strong p-8">
  <p class="section-title">Auth</p>
  <div class="mt-2 flex flex-wrap items-end justify-between gap-4">
    <div>
      <h1 class="text-3xl font-semibold text-slate-900">ログアウト</h1>
      <p class="mt-2 text-sm text-slate-600">現在のセッションを終了します。</p>
    </div>
  </div>
</section>

<section class="card p-6">
  <h2 class="text-xl font-semibold text-slate-900">現在のセッション</h2>
  <div class="mt-4 space-y-3 text-sm text-slate-600">
    <div>
      <p class="label">ユーザー</p>
      <p class="text-base font-semibold text-slate-800">watanabe</p>
    </div>
    <div>
      <p class="label">ログイン方法</p>
      <p class="text-base font-semibold text-slate-800">API Token</p>
    </div>
  </div>
  <div class="mt-6 flex gap-3">
    <Button.Root class="btn-primary">ログアウト</Button.Root>
    <Button.Root class="btn-ghost" href="/">キャンセル</Button.Root>
  </div>
</section>
