---
name: creating-learn-packages
description: Use when someone wants to create or update a lesson or course for the learn-ai app, turn notes or documents into a lesson, or make the zip its Library accepts.
---

# Tạo package bài học

Mọi đường dẫn dưới đây tính từ thư mục chứa file này, gọi là `SKILL_DIR`. Định dạng và cầu nối: `references/lesson-format.md`, đọc trước khi viết. Khung chạy được: `template/`. Công cụ: `scripts/learnpkg.py`, chỉ cần Python; bài có audio thì cần thêm `pip install mutagen`.

`SKILL_DIR` có thể chỉ đọc. Tạo bài ở thư mục làm việc, không tạo trong `SKILL_DIR`, và gọi công cụ bằng đường dẫn đầy đủ, kể cả các lệnh ghi trong `references/lesson-format.md`. Lệnh Python có thể là `python3`.

## Khi chạy trong Claude app hoặc web

Nếu không có quyền vào máy của tác giả, tức file nằm trong môi trường của Claude:

- **Giữ bài:** file mất khi sang cuộc trò chuyện mới. Ở mỗi Điểm dừng, chạy `python -m zipfile -c NHÁP.zip THƯ_MỤC` rồi gửi file đó cho tác giả tải về, kể cả khi bài chưa qua kiểm tra. Bản nháp chỉ để làm tiếp, không tải lên app được. Làm tiếp: tác giả gửi lại file đó, giải nén rồi đi tiếp. Tác giả đã duyệt trước thì không cần bản nháp.
- **Xem trang:** tác giả giải nén bản nháp rồi mở `page/index.html`. Không giải nén được thì đóng gói và để tác giả tải lên app; chưa share thì chỉ tác giả thấy.
- **Audio:** file lớn có thể không gửi vào cuộc trò chuyện được, và `mutagen` có thể không cài được. Gặp một trong hai thì báo tác giả, làm bài không có audio, rồi hướng dẫn thêm audio bằng Claude Code hoặc trên máy có Python, theo chặng 4.

## Làm tiếp khi đứt giữa chừng

Trước chặng 1, xem thư mục package đã có gì và làm tiếp từ chặng còn dở. Có `page/index.html` đã duyệt thì không soạn lại. Bài đã đăng thì giữ nguyên `slug` và mọi id, vì tiến độ gắn theo id.

## Năm chặng

Mỗi **Điểm dừng**: đưa cho tác giả xem, chờ tác giả trả lời rồi mới đi tiếp. Tác giả chưa duyệt thì báo đang chờ, không tự coi là đã duyệt. Tác giả giục gấp vẫn phải dừng. Chỉ bỏ qua khi tác giả nói rõ là duyệt trước, ví dụ "tôi duyệt trước mọi điểm dừng"; "làm nhanh giúp tôi" thì chưa phải. Khi bỏ qua, báo lại rằng chưa ai đọc nội dung.

1. **Hỏi:** chủ đề, người học là ai, tài liệu nguồn, mức Cơ bản (mặc định) hay Đầy đủ. Tác giả không trả lời đủ thì dùng mặc định và liệt kê điều đã tự chọn ở điểm dừng kế tiếp. Nhắc: không đưa dữ liệu khách hàng, tên riêng hay thông tin nội bộ vào bài, vì người được share sẽ đọc được.
2. **Trang bài:** chép `template/` vào một thư mục riêng, đổi `bai-mau` thành id của bài ở mọi nơi: tên thư mục, `package.json` (`slug`, `lessons`), `lesson.json` (id thẻ, id quiz), `data-quiz` trong trang. Viết `page/index.html`. Trang có quiz thì ghi luôn các câu đó vào `lesson.json`. **Điểm dừng:** tác giả mở trang và duyệt. Mở file trực tiếp thì chưa chấm được quiz và chưa hỏi được, nói trước với tác giả.
3. **Tóm tắt, thẻ, `content.md`, đáp án quiz:** thẻ và quiz phải khớp trang. Mọi con số, kết quả code và đáp án quiz tự tính lại bằng cách chạy thật, không tính nhẩm. **Điểm dừng:** tác giả duyệt.
4. **Audio, chỉ khi tác giả muốn:** viết kịch bản, hướng dẫn tác giả tự tạo, nhận file, đổi sang mp3 bằng `ffmpeg -i VÀO -b:a 64k RA.mp3`, đặt vào `audio/`, khai trong `tracks`: `{"short": {"file": "RA.mp3", "label": "Bản ngắn"}}`, tối đa `short` và `long`. Cả zip tối đa 90 MB; 64 kbps tốn khoảng 0,5 MB mỗi phút. Không muốn thì để `tracks` rỗng và đi tiếp.
5. **Đóng gói:**
   ```
   python SKILL_DIR/scripts/learnpkg.py validate THƯ_MỤC [--profile full]
   python SKILL_DIR/scripts/learnpkg.py pack THƯ_MỤC TÊN.zip [--profile full]
   ```
   Để zip ngoài thư mục bài. Xử lý hết lỗi và cảnh báo. Đưa zip cho tác giả, là đường dẫn trên máy hoặc file tải về trong Claude app, web, kèm cách tải lên: Thư viện, Tải lên. Tác giả tự tải lên, rồi mở bài để thử; chưa share thì chỉ tác giả thấy. Không tải lên thay tác giả.

## Mức của bài

- **Cơ bản:** trang theo khung, tóm tắt, thẻ. Quiz, công cụ tương tác, mục Đi sâu là tùy chọn.
- **Đầy đủ:** theo mục "Khung nội dung đầy đủ" trong `references/lesson-format.md`, đúng 8 câu quiz do server chấm, có `content.md`, kiểm tra bằng `--profile full`. Máy chỉ kiểm tra được một phần khung, phần còn lại tự đối chiếu. Audio vẫn không bắt buộc. Câu khởi động và kiểm tra nhanh tự chấm trong trang được.

## Trang chạy trong sandbox

Những điều này không báo lỗi lúc viết mà trang im lặng không chạy:

| Đừng dùng | Dùng |
|---|---|
| `<form>`, submit | Nút `type="button"` và `addEventListener` |
| Script inline, `onclick` | File `.js` trong `page/` |
| `localStorage`, cookie, `fetch` | `LearnBridge.call("doc.set", {data})`, `call("doc.get")` |
| CDN, font và ảnh từ ngoài | File trong `page/`, hoặc `/static/` |
| Đáp án quiz cuối bài trong trang | `call("quiz.answer", {id, option})`, server chấm |

Khung mẫu đã lưu tiến độ và chấm quiz. Dùng lại nguyên phần đó, không tự viết thêm lớp xác minh lưu: `doc.set` được app tự ghi lại khi lỗi.

Bảng, code và công thức rộng phải tự cuộn ngang trong khung của chúng. Kiểm tra ở chiều rộng 360 px bằng công cụ thiết bị của trình duyệt: trang không tràn chưa có nghĩa là cột quan trọng không bị cắt.

Thêm câu quiz vào cuối, không đổi thứ tự lựa chọn sau khi đã đăng.
