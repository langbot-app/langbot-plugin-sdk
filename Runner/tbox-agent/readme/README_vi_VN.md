# Tbox Agent

## Tổng quan

Chạy ứng dụng Ant Tbox dưới dạng LangBot Runner.

## Thông tin gói

- **Runner ID**: `plugin:langbot-team/TboxAgent/default`
- **Phiên bản**: `0.1.0`
- **Kho mã nguồn**: [https://github.com/langbot-app/langbot-plugins/tree/main/Runner/tbox-agent](https://github.com/langbot-app/langbot-plugins/tree/main/Runner/tbox-agent)

## Khả năng chính

- **Đã bật**: `streaming`, `multimodal input`
- **Không khai báo**: `tool calling`, `knowledge retrieval`, `interrupt`

## Cấu hình

| Trường | Kiểu | Bắt buộc | Mặc định |
| --- | --- | --- | --- |
| `api-key` | `secret` | Có | Trống |
| `app-id` | `string` | Có | Trống |
| `timeout` | `number` | Không | `120` |

## Quyền Host

- **`storage`**: `plugin`

## Cài đặt và sử dụng

1. Cài đặt plugin từ chợ plugin LangBot.
2. Chọn Runner ID bên dưới trong bộ chọn Runner của Pipeline.
3. Điền thông tin kết nối theo bảng và lưu giá trị nhạy cảm bằng trường secret trong giao diện quản trị.

## Bảo mật và giới hạn

- Runner chỉ được dùng tài nguyên LangBot đã cấp quyền cho lần chạy hiện tại.
- Tính sẵn sàng, khả năng mô hình và giới hạn tốc độ phụ thuộc vào dịch vụ bên ngoài.
- Xem hành vi nâng cao và giới hạn riêng của sản phẩm trong README tiếng Trung ở thư mục gốc hoặc README_en_US.md tiếng Anh.
