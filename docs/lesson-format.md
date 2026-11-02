# Định dạng bài học

Contract v1 là định dạng duy nhất server nhận. Bản đầy đủ và lý do ở `design/02-nen-tang-nhieu-tac-gia.md`, mục 4. Máy kiểm tra bằng `app/contract.py`.

## Một package

```
package.json
lessons/<lesson-id>/
  lesson.json
  page/index.html      trang bài, kèm file phụ trong page/
  content.md           toàn văn bài cho AI đọc, cần có nếu muốn xin ô Hỏi
  audio/*.mp3          tùy chọn
```

- `package.json`: `contract_version`, `slug`, `title`, `topic`, `description`, `lessons` là danh sách `lesson-id` theo thứ tự.
- `lesson.json`: `title`, `summary`, `cards`, `quiz`, `tracks`.
- Id giữ nguyên qua các phiên bản, vì tiến độ gắn theo id. Sửa nội dung thẻ không đổi id. Id biến mất thì tác giả phải xác nhận lúc tải lên.
- Trong package chỉ dùng id trần. Server tự thêm tiền tố `p<12 hex>.` vào id trong các bảng tiến độ.
- Bài không có `tracks` thì buổi học bỏ bước Nghe.

## Kiểm tra và đóng gói

```
python scripts/learnpkg.py validate DIR [--profile full]
python scripts/learnpkg.py pack DIR OUT.zip
```

Tải zip lên ở màn hình Thư viện. Server chạy lại đúng bộ kiểm tra này, rồi hiện cho tác giả xem thay đổi trước khi nhận.

## Giới hạn

Zip tối đa 90 MB. Mỗi tài khoản có hạn mức 1 GB tính trên dung lượng đã giải nén. Góp ý tối đa 2.000 ký tự.

## Trang bài

Trang là mã không tin cậy, chạy trong iframe sandbox không có origin. Trang không gọi được API của app, chỉ nói chuyện qua cầu nối `MessagePort`: `doc.get`, `doc.set`, `learner.id`, `quiz.answer`, `ask.open`, `link.open`, `media.error`. Xem `design/02a-ket-qua-sandbox.md`.

## Chuyển bài cũ

`scripts/convert_legacy.py CONFIG.json OUT_DIR [--allow-draft]` chuyển thư mục bài kiểu cũ thành package. File cấu hình nằm ngoài repo:

```json
{
  "source": "đường dẫn tới thư mục chứa các bài",
  "replace": [["chuỗi cũ", "chuỗi mới"]],
  "package": {"slug": "...", "title": "...", "topic": "...", "description": "..."},
  "lessons": [{
    "id": "bai03", "order": 3, "title": "Tên bài",
    "folder": "Bai03-Ten", "page": "bai03_ten.html", "doc": "lesson3", "audio_dir": "podcast",
    "tracks": {"long": {"file": "b.mp3", "label": "Bản dài"}}
  }]
}
```

`replace` dùng để bỏ tên riêng khỏi trang trước khi đăng.

## Khung nội dung đầy đủ

1. **Khởi động:** 3 câu đoán trước. Khi quay lại thì thành ôn tập, ưu tiên câu làm sai, lấy cả câu của bài trước.
2. **4–5 phần,** mỗi phần gồm:
   - Giải thích dài vừa đủ.
   - Công cụ tính thật, không đặt số tay, có bước "Dự đoán trước khi chạy".
   - Kiểm tra nhanh 2 câu.
   - Hộp "Áp dụng vào dự án".
   - Mục gập "Đi sâu" có công thức và link bài báo gốc.
   - Nút "Hỏi về phần này" và "Tự giải thích lại".
3. **Quiz cuối bài** 8 câu, có câu phải tự tính.
4. **Podcast ôn tập,** kịch bản bản ngắn và bản dài, audio do tác giả tự tạo.
