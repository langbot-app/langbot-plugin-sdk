# Tbox Agent

## 概要

Ant Tbox アプリを LangBot Runner として実行します。

## パッケージ情報

- **Runner ID**: `plugin:langbot-team/TboxAgent/default`
- **バージョン**: `0.1.0`
- **リポジトリ**: [https://github.com/langbot-app/langbot-agent-runner](https://github.com/langbot-app/langbot-agent-runner)

## 主な機能

- **有効**: `streaming`, `multimodal input`
- **未宣言**: `tool calling`, `knowledge retrieval`, `interrupt`

## 設定

| フィールド | 型 | 必須 | 既定値 |
| --- | --- | --- | --- |
| `api-key` | `secret` | はい | 空 |
| `app-id` | `string` | はい | 空 |
| `timeout` | `number` | いいえ | `120` |

## Host 権限

- **`storage`**: `plugin`

## インストールと使用方法

1. LangBot プラグインマーケットからこのプラグインをインストールします。
2. Pipeline の Runner セレクターで下記 Runner ID を選択します。
3. 設定表に従って接続情報を入力し、機密値は管理画面の secret フィールドに保存します。

## セキュリティと制約

- Runner が利用できるのは、現在の実行で許可された LangBot リソースだけです。
- 外部サービスの可用性、モデル機能、レート制限は各プラットフォームに依存します。
- 高度な動作と製品固有の制約は、ルートの中国語 README または英語版 README_en_US.md を参照してください。
