# Phi CLI 設計書

## 概要

Backend APIと連携するハッカー風CLIインターフェース。
メニューナビゲーションを統一的に管理し、一貫した「戻る」挙動を実現する。

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│                      phi (entry point)                  │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                     PhiApplication                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │ MenuSystem  │  │  APIClient  │  │  BannerRenderer │  │
│  │ (ナビ管理)　  │  │ (HTTP通信)  │  │  (表示)        　 │  │
│  └─────────────┘  └─────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                       Menus                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Operate  │ │ Record   │ │ Train    │ │ Storage  │   │
│  │ Menu     │ │ Menu     │ │ Menu     │ │ Menu     │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                │
│  │ Setup    │ │ Info     │ │ Config   │                │
│  │ Menu     │ │ Menu     │ │ Menu     │                │
│  └──────────┘ └──────────┘ └──────────┘                │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                   Backend API Server                    │
│                   (localhost:8000)                      │
└─────────────────────────────────────────────────────────┘
```

## コアコンポーネント

### 1. MenuSystem (メニューナビゲーション管理)

```python
class MenuResult(Enum):
    CONTINUE = "continue"  # 同じメニューを続ける
    BACK = "back"          # 1つ前のメニューに戻る
    EXIT = "exit"          # アプリ終了

class MenuSystem:
    """メニュースタックを管理し、一貫したナビゲーションを提供"""

    def __init__(self):
        self._stack: List[Callable] = []  # メニュー関数のスタック

    def push(self, menu_func: Callable) -> None:
        """メニューをスタックにプッシュ"""
        self._stack.append(menu_func)

    def pop(self) -> Optional[Callable]:
        """スタックからポップ (1つ戻る)"""
        if self._stack:
            return self._stack.pop()
        return None

    def run(self, initial_menu: Callable) -> None:
        """メニューループを実行"""
        self.push(initial_menu)

        while self._stack:
            current_menu = self._stack[-1]
            result = current_menu()

            if result == MenuResult.BACK:
                self.pop()
            elif result == MenuResult.EXIT:
                break
            # CONTINUE の場合は同じメニューを再表示
```

### 2. Menu基底クラス

```python
from InquirerPy import inquirer
from InquirerPy.base.control import Choice

class BaseMenu:
    """全メニューの基底クラス"""

    BACK_VALUE = "__BACK__"  # 戻る用の特殊値

    def __init__(self, app: "PhiApplication"):
        self.app = app
        self.api = app.api_client

    @property
    def title(self) -> str:
        """メニュータイトル"""
        raise NotImplementedError

    def get_choices(self) -> List[Choice]:
        """選択肢を返す (最後に「戻る」を自動追加)"""
        raise NotImplementedError

    def handle_choice(self, choice: Any) -> MenuResult:
        """選択肢の処理"""
        raise NotImplementedError

    def show(self) -> MenuResult:
        """メニューを表示して結果を返す"""
        choices = self.get_choices()
        choices.append(Choice(value=self.BACK_VALUE, name="« 戻る"))

        try:
            selected = inquirer.select(
                message=f"[{self.title}]",
                choices=choices,
                style=hacker_style,
                qmark="",
                amark="",
                pointer="❯",
            ).execute()
        except KeyboardInterrupt:
            return MenuResult.BACK

        if selected == self.BACK_VALUE:
            return MenuResult.BACK

        return self.handle_choice(selected)
```

### 3. APIClient (Backend通信)

```python
class APIClient:
    """Backend APIとの通信を担当"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session = requests.Session()

    def get(self, path: str, **kwargs) -> dict:
        resp = self.session.get(f"{self.base_url}{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, **kwargs) -> dict:
        resp = self.session.post(f"{self.base_url}{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()

    # 各API用のヘルパーメソッド
    def list_projects(self) -> List[dict]:
        return self.get("/api/projects")["projects"]

    def start_teleop(self, mode: str, config: dict) -> dict:
        return self.post("/api/teleop/start", json={"mode": mode, **config})

    # ... 他のAPIメソッド
```

## ディレクトリ構造

```
interfaces/cli/
├── pyproject.toml          # パッケージ設定
├── DESIGN.md               # この設計書
└── src/
    └── phi_cli/
        ├── __init__.py
        ├── main.py             # エントリーポイント
        ├── app.py              # PhiApplication
        ├── api_client.py       # APIClient
        ├── menu_system.py      # MenuSystem, MenuResult, BaseMenu
        ├── styles.py           # ハッカー風スタイル定義
        ├── banner.py           # バナー表示
        └── menus/
            ├── __init__.py
            ├── main_menu.py    # メインメニュー
            ├── operate.py      # 操作モード
            ├── record.py       # データ収録
            ├── train.py        # モデル学習
            ├── storage.py      # データ管理
            ├── setup.py        # セットアップ
            ├── info.py         # システム情報
            └── config.py       # 設定
```

## メニュー遷移フロー

```
MainMenu
├── OperateMenu ─────────────────────────────────────────┐
│   ├── TeleopSubmenu                                    │
│   │   ├── [実行] → TeleopSession → 戻る → TeleopSubmenu│
│   │   └── [戻る] → OperateMenu                         │
│   ├── InferenceSubmenu                                 │
│   │   ├── [実行] → InferenceSession → 戻る             │
│   │   └── [戻る] → OperateMenu                         │
│   └── [戻る] → MainMenu                                │
│                                                        │
├── RecordMenu ──────────────────────────────────────────┤
│   ├── [新規録画] → RecordSession → 戻る → RecordMenu   │
│   └── [戻る] → MainMenu                                │
│                                                        │
├── TrainMenu ───────────────────────────────────────────┤
│   ├── CloudTrainSubmenu                                │
│   │   ├── [新規ジョブ] → JobCreate → 戻る              │
│   │   └── [戻る] → TrainMenu                           │
│   └── [戻る] → MainMenu                                │
│                                                        │
├── StorageMenu ─────────────────────────────────────────┤
│   ├── LocalDataSubmenu                                 │
│   │   └── [戻る] → StorageMenu                         │
│   ├── R2SyncSubmenu                                    │
│   │   └── [戻る] → StorageMenu                         │
│   ├── HuggingFaceSubmenu                               │
│   │   └── [戻る] → StorageMenu                         │
│   └── [戻る] → MainMenu                                │
│                                                        │
├── SetupMenu ───────────────────────────────────────────┤
│   ├── ProjectSubmenu                                   │
│   │   └── [戻る] → SetupMenu                           │
│   ├── DeviceSubmenu                                    │
│   │   └── [戻る] → SetupMenu                           │
│   ├── CalibrationSubmenu                               │
│   │   └── [戻る] → SetupMenu                           │
│   └── [戻る] → MainMenu                                │
│                                                        │
├── InfoMenu ────────────────────────────────────────────┤
│   └── [戻る] → MainMenu                                │
│                                                        │
├── ConfigMenu ──────────────────────────────────────────┤
│   └── [戻る] → MainMenu                                │
│                                                        │
└── [終了] → アプリ終了                                   │
```

## 「戻る」の統一挙動

1. **全メニューで最後に「« 戻る」を自動追加**
   - `BaseMenu.show()` で自動的に追加
   - 開発者は選択肢を定義するだけ

2. **BACK_VALUE または Ctrl+C で BACK を返す**
   - `__BACK__` 特殊値で「戻る」を識別
   - Ctrl+C (KeyboardInterrupt) も同様に1つ戻る
   - 統一的に1つ前のメニューに戻る

3. **スタックベースのナビゲーション**
   - サブメニューに入る = push
   - 戻る = pop
   - 常に正しい親メニューに戻る

## 実装例

```python
# menus/operate.py
from InquirerPy.base.control import Choice

class OperateMenu(BaseMenu):
    title = "OPERATE"

    def get_choices(self):
        return [
            Choice(value="teleop", name="🕹️  テレオペレーション"),
            Choice(value="inference", name="🤖 推論実行"),
        ]

    def handle_choice(self, choice):
        if choice == "teleop":
            # サブメニューをプッシュ
            self.app.menu.push(TeleopSubmenu(self.app).show)
            return MenuResult.CONTINUE
        elif choice == "inference":
            self.app.menu.push(InferenceSubmenu(self.app).show)
            return MenuResult.CONTINUE
        return MenuResult.CONTINUE


class TeleopSubmenu(BaseMenu):
    title = "TELEOP"

    def get_choices(self):
        return [
            Choice(value="simple", name="🎮 シンプル (キーボード)"),
            Choice(value="visual", name="📹 ビジュアル (カメラ付き)"),
            Choice(value="bimanual", name="🤝 双腕モード"),
            Choice(value="remote", name="🌐 リモート (HTTP)"),
        ]

    def handle_choice(self, choice):
        # APIを呼び出してテレオペ開始
        try:
            result = self.api.start_teleop(mode=choice)
            print(f"✅ テレオペレーション開始: {result}")
            input("\nEnterキーで戻る...")
        except Exception as e:
            print(f"❌ エラー: {e}")
            input("\nEnterキーで戻る...")

        return MenuResult.BACK  # 実行後は1つ戻る
```

## 依存パッケージ

```toml
[project]
dependencies = [
    "InquirerPy>=0.3.4",
    "rich>=13.0.0",
    "httpx>=0.27.0",       # requests より async 対応、型ヒント充実
]
```

## InquirerPy スタイル定義

```python
# styles.py
from InquirerPy.utils import get_style

hacker_style = get_style({
    "questionmark": "#00ff00 bold",    # マトリックスグリーン
    "answermark": "#00ff00",
    "answer": "#00ffff bold",          # シアン
    "input": "#00ff00",
    "question": "#00ff00 bold",
    "answered_question": "#00ff00",
    "instruction": "#808080",
    "long_instruction": "#808080",
    "pointer": "#00ff00 bold",
    "checkbox": "#00ff00",
    "separator": "#00ff00",
    "skipped": "#808080",
    "validator": "#ff0000",
    "marker": "#00ff00",
    "fuzzy_prompt": "#00ff00",
    "fuzzy_info": "#808080",
    "fuzzy_border": "#00ff00",
    "fuzzy_match": "#00ffff bold",
}, style_override=False)
```

## コマンド

```bash
# 起動
phi              # または python -m phi_cli

# Backend APIサーバーも起動
phi --with-server
```
