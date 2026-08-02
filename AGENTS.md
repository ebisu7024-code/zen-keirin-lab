# zenKeirin Lab Codex Instructions

## 応答ルール
- 返答は必ず日本語で行う。
- zen本人の予想や考察をAIが上書きしない。AIは事実、解釈、学び、次回検証ポイントを分けて整理する。

## 毎回最初に参照するNotion
1. zenOS Light Context
   - Page ID: `3408cd0af1c881a1ac15d89f9ac95f42`
2. 競輪予想研究アプリ｜zenKeirin Lab
   - Page ID: `39f8cd0af1c8811694c3ed9377312ade`
   - 重要セクション: `## 23. 結果反映・GitHub更新オペレーション 2026-08-02`

## プロジェクト正本
- ローカル作業場所: `/Users/zen/Projects/zen-keirin-lab`
- GitHub: `https://github.com/zen7024/zen-keirin-lab.git`
- ブランチ: `main`
- アプリDB: `data/zen_keirin_lab.sqlite3`
- DBと取込ログ類は `.gitignore` の `data/*` によりGit管理外。DBだけ変わった場合はGitHub更新対象にしない。

## 「結果反映して」と言われたら
以下をすぐ実行する。ユーザーに同じ説明や長い前提を何度も求めない。

1. Notionの `zenOS Light Context` と `競輪予想研究アプリ｜zenKeirin Lab` を読む。
2. 対象レースの既存記録、DB状態、Git状態を確認する。
3. 会話、画像、購入明細、公開結果から、開催日、開催場、レース番号、買い目、購入額、着順、払戻、収支、本人考察を抽出する。
4. 既存レースがあれば重複作成せず更新する。未登録なら `race_date`、`venue`、`race_no`、`race_title`、`source_race_id` を手がかりに作成する。
5. WINTICKET URLまたはraceIdがある場合は、既存ヘルパーで選手、ライン、結果、払戻を補完する。
6. 反映後、的中判定、購入額、払戻、収支、`prediction_source`、`strategy_type`、買い目理由、振り返りが崩れていないか確認する。
7. Notionへ、既存の実戦記録と同じ粒度で「事実」「解釈」「今回残す学び」を追記する。
8. Git管理対象ファイルに変更があれば、テスト、コミット、GitHub更新まで進める。

## アプリ反映で優先して使う関数
- `init_db()`
- `fetch_races()`
- `fetch_race()`
- `upsert_race()`
- `upsert_result()`
- `add_bet()`
- `update_bet()`
- `recompute_hits_for_race()`
- `sync_winticket_for_race()`
- `sync_winticket_race_list_for_date()`
- `sync_winticket_details_for_race_ids()`

## GitHub更新ルール
ファイル変更が出たら、原則として最後にGitHubへ反映する。

確認:
```bash
git status --short --branch
git diff --stat
```

検証:
```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile app.py keirin_logic.py winticket_source.py venue_features.py
```

コミット例:
```bash
git add <変更ファイル>
git commit -m "Update zenKeirin Lab operation notes"
```

push:
```bash
git push origin main
```

push後は `git status --short --branch` で `main...origin/main` に戻っていることを確認する。

## 添付・コピペを減らす運用
- まずNotionとローカルDBを参照する。
- WINTICKET URL、raceId、開催日、開催場、レース番号が分かれば、こちらで可能な範囲を補完する。
- 添付が必要なのは、Codexから取得できない購入明細スクショ、ユーザーだけが見ているTIPSTAR画面、本人考察の原文がある場合だけ。
- 迷った場合でも、まず既存データから仮説を立て、足りない情報を短く1つずつ聞く。

## 現在の最新GitHub反映
- コミット: `d4bb06f Add WINTICKET sync and development forecasting`
- 状態: `origin/main` へpush済み。
- 確認: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests` は33件OK。
