# Định dạng bài học

Contract v1 là định dạng duy nhất server nhận. Máy kiểm tra bằng `app/contract.py`. Với bộ đề trắc nghiệm luyện thi, xem [Định dạng bộ đề](practice-test-format.md).

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
- `lesson.json`:
  - `title`, tối đa 200 ký tự.
  - `summary`: 3–8 ý, văn bản thuần.
  - `cards`: 5–30 thẻ, mỗi thẻ `id`, `q`, `a`.
  - `quiz`: có thể rỗng, mỗi câu `id`, `q`, `options`, `answer` (vị trí đáp án đúng, tính từ 0), `why`.
  - `tracks`: có thể rỗng, tối đa `short` và `long`, mỗi bản `file` (trong `audio/`) và `label`.
- Id giữ nguyên qua các phiên bản, vì tiến độ gắn theo id. Sửa nội dung thẻ không đổi id. Id biến mất thì tác giả phải xác nhận lúc tải lên.
- Trong package chỉ dùng id trần. Server tự thêm tiền tố `p<12 hex>.` vào id trong các bảng tiến độ.
- Bài không có `tracks` thì buổi học bỏ bước Nghe.

## Kiểm tra và đóng gói

```
python scripts/learnpkg.py validate DIR [--profile full]
python scripts/learnpkg.py pack DIR OUT.zip [--profile full]
```

Tải zip lên ở màn hình Thư viện. Server chạy lại đúng bộ kiểm tra này, rồi hiện cho tác giả xem thay đổi trước khi nhận.

## Giới hạn

Zip tối đa 90 MB. Mỗi tài khoản có hạn mức 1 GB tính trên dung lượng đã giải nén. Góp ý tối đa 2.000 ký tự.

## Trang bài

Trang là mã không tin cậy, chạy trong iframe sandbox không có origin. Trang không có cookie, `localStorage`, mạng hay form. Script inline và thuộc tính `on*` không chạy; mọi script để trong file riêng ở `page/`. Thư viện chỉ dùng được bản app cấp ở `/static/` (`lesson-bridge.js`, `lesson-fonts.css`, `vendor/`), không tải từ ngoài.

Trang nói chuyện với app qua `window.LearnBridge`, có sẵn khi nạp `/static/lesson-bridge.js`:

| Gọi | Kết quả |
|---|---|
| `call("doc.get")` | Dữ liệu đã lưu của người này trong bài này, hoặc `null` |
| `call("doc.set", {data})` | Lưu một object |
| `call("quiz.answer", {id, option})` | `{correct}`. Server chấm theo `lesson.json`; câu sai thành thẻ ôn |
| `askApp(text)` | Mở ô Hỏi của app với câu điền sẵn, người học tự bấm gửi |
| `call("learner.id")` | Mã riêng của người học trong package, không phải email |
| `call("link.open", {url})` | App hỏi người học trước khi mở; chỉ nhận `https` |

`id` truyền vào `quiz.answer` là `id` của câu trong `lesson.json`. Đáp án đúng chỉ nằm trong `lesson.json`, trang không cần biết; phần giải thích `why` có thể nằm trong trang. Khung bài mẫu trong skill dùng sẵn các lệnh này.

Link `<a href>` ra ngoài tự đi qua `link.open`. Link trong trang (`#muc`) chỉ cuộn tới mục đó, không đổi `location.hash` và không kích hoạt `:target`, vì WebKit nạp lại trang sandbox khi gặp loại link này. Trên màn hình dưới 1024 px, thanh của app và `nav.top` của trang ẩn khi cuộn xuống, hiện lại khi cuộn lên; menu của trang nên đặt trong `nav.top` để được hưởng việc này. Câu kiểm tra nhanh không cần ghi nhận có thể tự chấm trong trang; người học đọc mã nguồn sẽ thấy đáp án nên đừng dùng cách này cho quiz cuối bài. Công thức dùng `/static/vendor/tex-svg.min.js` (MathJax) cùng `/static/mathjax-config.js`.

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
