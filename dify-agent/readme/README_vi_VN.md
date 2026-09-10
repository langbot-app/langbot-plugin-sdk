# Dify Agent

## Tổng quan

Chạy ứng dụng Dify dưới dạng LangBot Runner.

## Thông tin gói

- **Runner ID**: `plugin:langbot-team/DifyAgent/default`
- **Phiên bản**: `0.1.0`
- **Kho mã nguồn**: [https://github.com/langbot-app/langbot-agent-runner](https://github.com/langbot-app/langbot-agent-runner)

## Khả năng chính

- **Đã bật**: `streaming`, `tool calling`, `knowledge retrieval`, `multimodal input`
- **Không khai báo**: `interrupt`

## Cấu hình

| Trường | Kiểu | Bắt buộc | Mặc định |
| --- | --- | --- | --- |
| `base-url` | `string` | Có | `https://api.dify.ai/v1` |
| `base-prompt` | `text` | Có | `When the file content is readable, please read the content of this file. When the file is an image, describe the content of this image.` |
| `app-type` | `select` | Có | `chat` |
| `api-key` | `secret` | Có | Trống |
| `timeout` | `integer` | Không | `30` |
| `langbot-assets-enabled` | `boolean` | Không | false |
| `langbot-assets-gateway-host` | `string` | Không | `0.0.0.0` |
| `langbot-assets-gateway-port` | `integer` | Không | `8765` |
| `langbot-assets-gateway-request-timeout` | `integer` | Không | `60` |
| `langbot-assets-token-ttl` | `integer` | Không | `3600` |
| `langbot-assets-input-name` | `string` | Không | `langbot_asset_run_token` |

## Quyền Host

- **`tools`**: `detail`, `call`
- **`knowledge_bases`**: `retrieve`
- **`history`**: `page`
- **`storage`**: `plugin`

## Cài đặt và sử dụng

1. Cài đặt plugin từ chợ plugin LangBot.
2. Chọn Runner ID bên dưới trong bộ chọn Runner của Pipeline.
3. Điền thông tin kết nối theo bảng và lưu giá trị nhạy cảm bằng trường secret trong giao diện quản trị.

## Bảo mật và giới hạn

- Runner chỉ được dùng tài nguyên LangBot đã cấp quyền cho lần chạy hiện tại.
- Tính sẵn sàng, khả năng mô hình và giới hạn tốc độ phụ thuộc vào dịch vụ bên ngoài.
- Xem hành vi nâng cao và giới hạn riêng của sản phẩm trong README tiếng Trung ở thư mục gốc hoặc README_en_US.md tiếng Anh.
