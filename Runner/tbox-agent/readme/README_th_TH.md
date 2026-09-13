# Tbox Agent

## ภาพรวม

เรียกใช้แอป Ant Tbox เป็น LangBot Runner

## ข้อมูลแพ็กเกจ

- **Runner ID**: `plugin:langbot-team/TboxAgent/default`
- **เวอร์ชัน**: `0.1.0`
- **ที่เก็บโค้ด**: [https://github.com/langbot-app/langbot-plugins/tree/main/Runner/tbox-agent](https://github.com/langbot-app/langbot-plugins/tree/main/Runner/tbox-agent)

## ความสามารถหลัก

- **เปิดใช้**: `streaming`, `multimodal input`
- **ไม่ได้ประกาศ**: `tool calling`, `knowledge retrieval`, `interrupt`

## การกำหนดค่า

| ฟิลด์ | ชนิด | จำเป็น | ค่าเริ่มต้น |
| --- | --- | --- | --- |
| `api-key` | `secret` | ใช่ | ว่าง |
| `app-id` | `string` | ใช่ | ว่าง |
| `timeout` | `number` | ไม่ | `120` |

## สิทธิ์ของ Host

- **`storage`**: `plugin`

## การติดตั้งและใช้งาน

1. ติดตั้งปลั๊กอินจากตลาดปลั๊กอิน LangBot
2. เลือก Runner ID ด้านล่างในตัวเลือก Runner ของ Pipeline
3. กรอกข้อมูลการเชื่อมต่อตามตาราง และเก็บค่าลับด้วยฟิลด์ secret ในหน้าจัดการ

## ความปลอดภัยและข้อจำกัด

- Runner ใช้ได้เฉพาะทรัพยากร LangBot ที่ได้รับอนุญาตสำหรับการทำงานปัจจุบัน
- ความพร้อมใช้งาน ความสามารถของโมเดล และขีดจำกัดอัตราขึ้นอยู่กับบริการภายนอก
- ดูพฤติกรรมขั้นสูงและข้อจำกัดเฉพาะผลิตภัณฑ์ใน README ภาษาจีนที่รากหรือ README_en_US.md ภาษาอังกฤษ
