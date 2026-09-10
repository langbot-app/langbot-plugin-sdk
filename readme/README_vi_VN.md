# Tác nhân tích hợp

## Tổng quan

Tác nhân tích hợp hỗ trợ mô hình dự phòng, gọi công cụ và truy xuất tri thức.

## Thông tin gói

- **Runner ID**: `plugin:langbot-team/LocalAgent/default`
- **Phiên bản**: `0.1.0`
- **Kho mã nguồn**: [https://github.com/langbot-app/langbot-local-agent](https://github.com/langbot-app/langbot-local-agent)

## Khả năng chính

- **Đã bật**: `streaming`, `tool calling`, `knowledge retrieval`, `multimodal input`, `skill authoring`, `interrupt`, `steering`
- **Không khai báo**: Trống

## Cấu hình

| Trường | Kiểu | Bắt buộc | Mặc định |
| --- | --- | --- | --- |
| `model` | `model-fallback-selector` | Có | `{fallbacks: [], primary: ''}` |
| `timeout` | `integer` | Không | `300` |
| `prompt` | `prompt-editor` | Có | `[{content: You are a helpful assistant., role: system}]` |
| `remove-think` | `boolean` | Không | false |
| `knowledge-bases` | `knowledge-base-multi-selector` | Không | `[]` |
| `advanced-settings` | `boolean` | Không | `false` |
| `retrieval-top-k` | `integer` | Không | `5` |
| `rerank-model` | `rerank-model-selector` | Không | Trống |
| `rerank-top-k` | `integer` | Không | `5` |
| `max-tool-iterations` | `integer` | Không | `100` |
| `tool-execution-mode` | `select` | Không | `parallel` |
| `max-tool-result-chars` | `integer` | Không | `20000` |
| `context-history-fetch-limit` | `integer` | Không | `50` |
| `context-window-tokens` | `integer` | Không | `200000` |
| `context-reserve-tokens` | `integer` | Không | `16384` |
| `context-keep-recent-tokens` | `integer` | Không | `20000` |
| `context-summary-tokens` | `integer` | Không | `8000` |

## Quyền Host

- **`models`**: `count_tokens`, `invoke`, `stream`, `rerank`
- **`tools`**: `detail`, `call`
- **`knowledge_bases`**: `list`, `retrieve`
- **`history`**: `page`

## Cài đặt và sử dụng

1. Cài đặt plugin từ chợ plugin LangBot.
2. Chọn Runner ID bên dưới trong bộ chọn Runner của Pipeline.
3. Điền thông tin kết nối theo bảng và lưu giá trị nhạy cảm bằng trường secret trong giao diện quản trị.

## Bảo mật và giới hạn

- Runner chỉ được dùng tài nguyên LangBot đã cấp quyền cho lần chạy hiện tại.
- Tính sẵn sàng, khả năng mô hình và giới hạn tốc độ phụ thuộc vào dịch vụ bên ngoài.
- Xem hành vi nâng cao và giới hạn riêng của sản phẩm trong README tiếng Trung ở thư mục gốc hoặc README_en_US.md tiếng Anh.
