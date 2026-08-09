# 外出先利用の公開手順

`zenKeirin Lab` は Streamlit の個人用アプリです。`ZEN_KEIRIN_DATABASE_URL` を設定するとPostgreSQL/Supabaseを正本DBとして使えます。このリポジトリのRender公開版では、URL未設定でも `ZEN_KEIRIN_APP_PASSWORD` からSupabaseのアプリ専用ロールへ接続します。外出先から使う場合は、公開URLに加えて、永続DBと最低限のアクセス制限が必要です。

## 現在のRender構成

- ホスティング: Render Web Service
- インスタンス: Free
- 保存先: `ZEN_KEIRIN_DATABASE_URL` があればそのDB。未設定時は `ZEN_KEIRIN_APP_PASSWORD` でSupabase app roleへ接続
- DBパス: SQLite時は `data/zen_keirin_lab.sqlite3`
- 認証: `ZEN_KEIRIN_APP_PASSWORD` による簡易パスワード

まず外出先から開けるURLを作るため、現在の `render.yaml` は無料構成にしています。RenderのFree Web ServiceはPersistent Diskを使えないため、SQLiteのままだと再起動や再デプロイでDBが消える可能性があります。実戦記録を長期保存する本運用では、PostgreSQL/Supabase化を優先します。

## Supabase / PostgreSQLを正本DBにする

スマホ公開版とMacローカル版で同じデータを使う本命構成です。両方に同じ `ZEN_KEIRIN_DATABASE_URL` を設定すると、同じクラウドDBを読み書きします。このリポジトリの既定運用では、Renderに `ZEN_KEIRIN_APP_PASSWORD` だけ入っていれば、Supabaseの `zen_keirin_app` ロールへ接続します。

1. Supabaseでプロジェクトを用意する。
2. Dashboardの `Connect` からPostgreSQL接続URLをコピーする。
3. Renderの環境変数に `ZEN_KEIRIN_APP_PASSWORD` を追加する。
4. 別DBに向ける場合だけ、Renderの環境変数に `ZEN_KEIRIN_DATABASE_URL` を追加する。
5. ローカルでは `.streamlit/secrets.toml` か環境変数に同じ値を入れる。
6. 初回起動時に必要テーブルが自動作成される。

RenderなどIPv4前提の環境では、Supabaseの `Session pooler` の接続URLを使うのが扱いやすいです。接続URLやパスワードはSecretとして扱い、Gitにはコミットしません。

ローカルで環境変数を使う例:

```bash
export ZEN_KEIRIN_DATABASE_URL='postgresql://postgres.xxxxx:password@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres'
streamlit run app.py
```

既存SQLite DBをSupabaseへ取り込む例:

```bash
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite-db data/zen_keirin_lab.sqlite3 \
  --database-url 'postgresql://postgres.xxxxx:password@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres'
```

公開アプリ上でも、サイドバーの `DBバックアップ/復元` からSQLite DBをアップロードすると、PostgreSQL接続中はクラウドDBへ上書き取込します。

## 認証の現在地

現時点では `ZEN_KEIRIN_APP_PASSWORD` による共通パスワードだけで保護します。スマホ公開版もローカル版も同じクラウドDBを見るため、パスワードを知っている人は同じ記録を操作できます。

後で自分以外にも使えるようにする場合は、Supabase Authなどで個別ログインを追加し、ユーザーごとの権限とデータ分離をRLSで設計します。今はその前段階として、DBだけクラウド正本に寄せています。

## TIPSTAR結果反映

TIPSTARの購入結果URLに含まれる `raceId` を保存しておくと、公開WINTICKET結果から着順・払戻表・買い目的中判定を自動補完します。起動時は `ZEN_KEIRIN_TIPSTAR_RESULT_SYNC_LIMIT` 件まで自動反映し、ダッシュボードから手動で追加反映できます。

TIPSTARの購入結果ページ自体はログインが必要なため、Render上のアプリはTIPSTARのログイン履歴を直接取得しません。購入額が入っている買い目は、公式払戻表と組番が一致したときに `公式払戻 × 購入額 / 100` で払戻を自動入力します。

## 推奨構成

- ホスティング: Render Web Service
- インスタンス: Free以上
- 保存先: Supabase PostgreSQL
- DB接続: `ZEN_KEIRIN_APP_PASSWORD` からSupabase app roleへ接続。必要に応じて `ZEN_KEIRIN_DATABASE_URL` で明示指定
- 認証: `ZEN_KEIRIN_APP_PASSWORD` による簡易パスワード

この構成なら、アプリ本体はGitHubからデプロイしつつ、レース記録DBはSupabaseに保存できます。無料Web Serviceの一時ファイル領域にSQLiteを置くと、再起動や再デプロイでDBが消える可能性があるため、本運用では避けます。

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

ただし、SQLite書き込みを長期保存する用途では、永続DBまたは外部DBへの移行が必要です。閲覧・軽い検証ならよいですが、実戦記録の正本にするならPostgreSQL/Supabase化を優先します。
