# 外出先利用の公開手順

`zenKeirin Lab` は Streamlit + SQLite の個人用アプリです。外出先から使う場合は、公開URLに加えて、SQLiteファイルを消さずに保存する場所と、最低限のアクセス制限が必要です。

## 現在のRender構成

- ホスティング: Render Web Service
- インスタンス: Free
- 保存先: Renderの一時ファイル領域
- DBパス: `data/zen_keirin_lab.sqlite3`
- 認証: `ZEN_KEIRIN_APP_PASSWORD` による簡易パスワード

まず外出先から開けるURLを作るため、現在の `render.yaml` は無料構成にしています。RenderのFree Web ServiceはPersistent Diskを使えないため、再起動や再デプロイでSQLite DBが消える可能性があります。実戦記録を長期保存する本運用では、下の有料ディスク構成かPostgreSQL/Supabase化に切り替えます。

## 推奨構成

- ホスティング: Render Web Service
- インスタンス: Starter以上
- 保存先: Render Persistent Disk
- DBパス: `/var/data/zen_keirin_lab.sqlite3`
- 認証: `ZEN_KEIRIN_APP_PASSWORD` による簡易パスワード

この構成なら、アプリ本体はGitHubからデプロイしつつ、レース記録DBはRenderの永続ディスクに保存できます。無料Web Serviceの一時ファイル領域にSQLiteを置くと、再起動や再デプロイでDBが消える可能性があるため、本運用では避けます。

## Renderで作る

1. GitHubの `main` に最新コードをpushする。
2. Render Dashboardで `New > Blueprint` を選ぶ。
3. このリポジトリを選び、ルートの `render.yaml` を使う。
4. `ZEN_KEIRIN_APP_PASSWORD` を聞かれたら、自分だけが分かる強いパスワードを入れる。
5. デプロイ完了後、発行された `https://...onrender.com` をスマホや外出先PCから開く。

`render.yaml` は以下を行います。

- `pip install -r requirements.txt` で依存関係を入れる。
- `streamlit run app.py --server.address 0.0.0.0 --server.port $PORT --server.headless true` で起動する。
- Freeインスタンスで起動する。
- `ZEN_KEIRIN_APP_PASSWORD` をRender側のSecretとして設定する。

## 有料ディスク構成に戻す場合

DBを消さずに使いたい場合は、`render.yaml` のサービス定義を次のように戻します。

```yaml
    plan: starter
    disk:
      name: zen-keirin-data
      mountPath: /var/data
      sizeGB: 1
```

さらに `envVars` に以下を追加します。

```yaml
      - key: ZEN_KEIRIN_DB_PATH
        value: /var/data/zen_keirin_lab.sqlite3
```

## 既存DBを引き継ぐ

初回デプロイ直後は、Render上のDBは空です。今のローカルDBを使いたい場合は、次のどちらかで `data/zen_keirin_lab.sqlite3` を `/var/data/zen_keirin_lab.sqlite3` へ置きます。

- Render Shell + `wormhole receive`
- SSH/SCP

DBを移す前に、ローカルでバックアップを残します。

```bash
cp data/zen_keirin_lab.sqlite3 data/zen_keirin_lab.sqlite3.bak-before-render-upload
```

Render Shellで受け取る例:

```bash
cd /var/data
wormhole receive
```

ローカルから送る例:

```bash
wormhole send data/zen_keirin_lab.sqlite3
```

受け取り後、ファイル名が違う場合はRender Shellで `zen_keirin_lab.sqlite3` に変更します。

## Streamlit Community Cloudを使う場合

Streamlit Community Cloudでも起動は簡単です。GitHubリポジトリ、ブランチ `main`、エントリポイント `app.py` を指定し、Secretsに次を設定します。

```toml
ZEN_KEIRIN_APP_PASSWORD = "自分だけのパスワード"
```

ただし、現行のSQLite書き込みを長期保存する用途では、永続DBまたは外部DBへの移行が必要です。閲覧・軽い検証ならよいですが、実戦記録の正本にするならRender Persistent DiskかPostgres化を優先します。

## 将来の本命案

複数端末から同時に書いたり、長く本格運用する場合は、SQLiteのまま外に置くより PostgreSQL / Supabase へ移行します。その場合は `get_conn()` 周辺とSQLの差分を整理し、DB移行スクリプトを作ってから進めます。
