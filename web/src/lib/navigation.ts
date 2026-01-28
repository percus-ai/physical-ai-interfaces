export const navItems = [
  {
    id: 'dashboard',
    label: 'ダッシュボード',
    href: '/',
    icon: '🏠',
    description: '状況の俯瞰とショートカット'
  },
  {
    id: 'operate',
    label: 'テレオペ / 推論',
    href: '/operate',
    icon: '🎮',
    description: 'テレオペレーションと推論実行'
  },
  {
    id: 'record',
    label: 'データ録画',
    href: '/record',
    icon: '📹',
    description: '録画の開始と進行状況'
  },
  {
    id: 'train',
    label: 'モデル学習',
    href: '/train',
    icon: '☁️',
    description: '学習ジョブの作成と管理'
  },
  {
    id: 'experiments',
    label: '実験管理',
    href: '/experiments',
    icon: '🧪',
    description: '実験評価と考察の管理'
  },
  {
    id: 'storage',
    label: 'データ管理',
    href: '/storage',
    icon: '📦',
    description: 'データセット・モデル・アーカイブ'
  },
  {
    id: 'setup',
    label: 'デバイス設定',
    href: '/setup',
    icon: '🔧',
    description: 'プロジェクト・デバイス・キャリブレーション'
  },
  {
    id: 'info',
    label: 'システム情報',
    href: '/info',
    icon: '📊',
    description: '環境・バージョン・稼働状況'
  },
  {
    id: 'config',
    label: '環境設定',
    href: '/config',
    icon: '⚙️',
    description: '設定とユーザー情報'
  }
];

export const quickActions = [
  {
    id: 'start-record',
    label: '録画を開始',
    href: '/record',
    tone: 'primary'
  },
  {
    id: 'new-train',
    label: '学習ジョブ作成',
    href: '/train',
    tone: 'secondary'
  },
  {
    id: 'teleop',
    label: 'テレオペ起動',
    href: '/operate',
    tone: 'secondary'
  }
];
