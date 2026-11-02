# Định dạng bài học

Tài liệu này mô tả định dạng đang chạy. Contract mới cho nhiều tác giả là bản nháp ở `design/02-nen-tang-nhieu-tac-gia.md`, mục 4.

## Thư mục nguồn của một bài

Nằm ngoài repo:

```
BaiNN-Ten/
├── baiNN_ten.html    trang bài đầy đủ
├── podcast/*.mp3     audio, trang bài phải gắn thẻ <audio src="audio/...">
└── app/
    ├── summary.md    các ý tóm tắt, mỗi ý một dòng bắt đầu bằng "- "
    └── cards.json    thẻ đã duyệt; bản nháp là cards.draft.json
```

`cards.json` là danh sách `{"id": "bai03-c01", "q": "...", "a": "..."}`. Id bắt đầu bằng id bài và không đổi, kể cả khi sửa nội dung thẻ, vì tiến độ gắn theo id. Viết bằng ký tự Unicode, không dùng LaTeX.

## File cấu hình đóng gói

```json
{
  "source": "đường dẫn tới thư mục chứa các bài",
  "replace": [["chuỗi cũ", "chuỗi mới"]],
  "lessons": [{
    "id": "bai03", "order": 3, "title": "Tên bài",
    "folder": "Bai03-Ten", "page": "bai03_ten.html", "doc": "lesson3", "audio_dir": "podcast",
    "tracks": {
      "short": {"file": "a.mp3", "label": "Bản ngắn"},
      "long": {"file": "b.mp3", "label": "Bản dài"}
    }
  }]
}
```

`replace` dùng để bỏ tên riêng khỏi trang trước khi đăng. File này nằm ngoài repo.

## Script chặn những gì

`scripts/package_content.py CONFIG.json OUT_DIR` dừng và báo lỗi khi:

- Trang có thuộc tính `on*`, vì CSP chặn.
- Trang không có thư viện từ cdnjs, không có `<head>` hoặc `<footer>`.
- Trang không có mảng quiz dạng `const QS=[...\n];`, mỗi câu có `q`, `o`, `a`, `w`.
- Bản podcast khai báo trong `tracks` không được trang bài dùng.
- Thẻ trùng id, thiếu nội dung, id sai tiền tố.
- Tóm tắt rỗng.
- Chưa có `cards.json`. Dùng `--allow-draft` để chấp nhận bản nháp.

Script chuyển script inline ra file riêng, chuyển thư viện CDN sang `/static/vendor/`, đo thời lượng audio bằng `ffprobe`, trích quiz bằng Node, rồi ghi `manifest.json`.

## Quy ước script chưa kiểm tra

- Trang lưu đáp án quiz qua `store.quiz["q"+i]` với đúng tên `doc`, để server tạo thẻ từ câu sai.
- Id câu quiz tính theo vị trí (`bai03-q0`). Đổi thứ tự quiz sau khi đã có người học sẽ gắn nhầm thẻ, nên chỉ thêm câu vào cuối.
- Mỗi bài khoảng 10–15 thẻ, nội dung đối chiếu với trang bài.

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
5. **Giao diện:** 3 cột trên màn hình rộng, gồm mục lục, nội dung, ô Hỏi; tiếng Việt; câu trả lời hiển thị Markdown.

Đối chiếu mọi con số và đáp án trên trang với phép tính độc lập trong trình duyệt thật trước khi đăng.
