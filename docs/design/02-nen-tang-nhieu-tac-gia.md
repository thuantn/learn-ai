# learn-ai thành nền tảng tạo và chia sẻ bài học: thiết kế

Trạng thái: **bản nháp, chờ chủ dự án duyệt, chưa xây.** Đã qua phản biện của một reviewer mới và hai model khác. Xây trên app hiện có, mô tả tại `01-app-ban-dau.md`.

Trong tài liệu, **[Chủ dự án]** là điều người dùng đã quyết định. **[Đề xuất]** là quyết định của người viết, chủ dự án có thể đổi.

## 1. Mục đích

Hiện app chỉ chạy bài do một người soạn, đọc từ một `manifest.json` lúc khởi động. [Chủ dự án] Mỗi người trong team được tự tạo bài học của mình, theo chủ đề hoặc package, rồi share cho người khác trong app. Người được share học như bài bình thường: Ôn lại, Nghe nếu có, Flashcard, trang bài đầy đủ.

Khung bài (contract) có trước, sau đó đóng thành một Claude skill để lần nào tạo bài cũng làm giống nhau.

Thành công nghĩa là: một đồng nghiệp chưa từng làm bài, dùng skill, tạo được một package đạt kiểm tra, tải lên, share cho người khác, và người đó học được mà không cần ai hỗ trợ.

## 2. Phạm vi

### Có
- Contract có số phiên bản, và một bộ kiểm tra dùng chung cho máy tác giả và server.
- Skill dẫn tác giả từ chủ đề đến file zip.
- Tải zip lên trong app, thư viện bài của tôi và bài được share.
- Share theo email hoặc link, thu hồi được.
- Góp ý theo bài, nút Báo sai trên thẻ và câu quiz.
- Vai trò admin: duyệt ô Hỏi, bật tắt Internet cho ô Hỏi, gỡ package.

### Không làm ở bản này
- Tự điều khiển Gemini. [Chủ dự án] Audio là tùy chọn và do người tạo tự cung cấp; skill chỉ hướng dẫn và kiểm tra file.
- Tự đăng ký tài khoản, gửi email mời. Admin vẫn tạo tài khoản bằng `app/cli.py`.
- Trình soạn bài trên web, kho bài công khai, tìm kiếm toàn app.
- Trả lời qua lại trong góp ý, thông báo, thống kê người học cho tác giả.
- Trang bài dạng Markdown. Thêm khi tác giả thật sự cần.

### Không được xảy ra
- Trang bài của người này đọc được phiên đăng nhập hay dữ liệu của người học khác.
- Trang bài dùng các đường đã biết để gửi dữ liệu ra ngoài: fetch, form, ảnh, script, tự điều hướng khung, mở cửa sổ mới. Rủi ro còn lại ghi ở mục 5.
- Zip xấu làm hỏng bài đang chạy hoặc ghi ra ngoài thư mục của nó.
- Người không được share mở được bài, kể cả biết đường dẫn file.
- Cập nhật package làm mất tiến độ của người học, trừ phần tác giả đã xác nhận xóa.
- Nội dung bài bị gửi sang dịch vụ AI khi admin chưa duyệt ô Hỏi cho package đó.

## 3. Khái niệm

- **Package:** một nhóm bài có thứ tự, có tên, mô tả, một nhãn chủ đề và một chủ sở hữu. [Đề xuất] Bài lẻ theo chủ đề là package một bài, nên app chỉ có một khái niệm. Bài 1, 2 hiện tại thành package đầu tiên.
- **Phiên bản:** mỗi lần tải lên tạo một phiên bản. Mọi người luôn học phiên bản mới nhất. Bản đầu không có tính năng quay lại phiên bản cũ; tác giả tải lại zip cũ nếu cần.
- **Quyền:** chủ sở hữu, người được share, admin. [Đề xuất] Mọi tài khoản đều tạo được bài, không cần duyệt, vì bài mới chỉ chủ sở hữu thấy.

## 4. Contract v1

```
package.json
lessons/<lesson-id>/
  lesson.json
  page/index.html      trang bài, kèm file phụ trong page/
  content.md           toàn văn bài cho AI đọc, bắt buộc nếu muốn xin ô Hỏi
  audio/*.mp3          tùy chọn
```

`package.json`: `contract_version`, `slug`, `title`, `topic`, `description`, `lessons` là danh sách `lesson-id` theo thứ tự.

`lesson.json`:
- `title`
- `summary`: 3–8 ý, văn bản thuần.
- `cards`: 5–30 thẻ, mỗi thẻ `id`, `q`, `a`.
- `quiz`: có thể rỗng, mỗi câu `id`, `q`, `options`, `answer`, `why`.
- `tracks`: có thể rỗng, tối đa `short` và `long`, mỗi bản `file`, `label`.

Quy tắc máy kiểm tra:
- Tên tệp và id chỉ gồm chữ thường, số, dấu gạch; id không trùng trong package.
- `slug` và mọi id giữ nguyên qua các phiên bản. Id cũ biến mất thì server báo tên từng id và tác giả phải xác nhận trước khi nhận bản mới.
- Chỉ nhận đuôi file trong danh sách: html, js, css, json, svg, png, jpg, webp, woff2, mp3.
- Trang bài không có thuộc tính `on*` hay script inline, không tải tài nguyên từ ngoài; dùng thư viện app cấp sẵn ở `/static/vendor/`. Đây là cảnh báo để trang không bị hỏng dưới CSP, không phải lớp bảo mật; an toàn nằm ở mục 5.
- Trang giao tiếp với app chỉ qua cầu nối ở mục 5.
- Mỗi zip tối đa 90 MB, vì Cloudflare gói miễn phí giới hạn mỗi request 100 MB. Tổng dung lượng giải nén, số file và tỉ lệ nén cũng có giới hạn; builder chọn con số.

Bài không có `tracks` thì buổi học bỏ bước Nghe. [Đề xuất]

Quy tắc người phải đánh giá: nội dung đúng, thẻ khớp với bài, tóm tắt đọc trong khoảng 2 phút, không có dữ liệu khách hàng. Skill có điểm dừng để tác giả tự duyệt những việc này.

Bộ kiểm tra là một module Python dùng thư viện chuẩn, cộng `mutagen` để đọc mp3. Tác giả chạy nó trên máy trước khi đóng gói, và server chạy lại khi nhận zip. Bài 1 và 2 phải đạt, đây là ca kiểm tra đầu tiên.

## 5. Cách ly trang bài

Đây là thay đổi quan trọng nhất. Trang bài có JavaScript tùy ý của tác giả, nên phải coi là không tin cậy.

- Trang chạy trong iframe `sandbox="allow-scripts"`, và response của nó có header `Content-Security-Policy: sandbox allow-scripts`. Trang không có origin thật nên không đọc được cookie hay gọi API của app.
- File `.html` của tác giả chỉ được trả khi request có `Sec-Fetch-Dest: iframe`, thiếu header này cũng từ chối, nên không mở trực tiếp trong tab được. Mọi file khác của tác giả, kể cả `.svg`, có CSP `sandbox` không kèm `allow-scripts`, và `nosniff`.
- CSP của trang do server gắn bằng response header, tác giả không bỏ được: `connect-src 'none'`, `form-action 'none'`, script, ảnh, font và media chỉ từ origin ghi tường minh của app, không dùng `'self'`. Font và `/static/vendor/` cần header CORS vì trang có origin mờ.
- File của trang đi qua đường dẫn `/s/<token>/...`, để đường dẫn tương đối trong bài vẫn chạy, vì request từ iframe không mang cookie `SameSite=Strict`. Token ký, gắn với người dùng và bài, cấp mới mỗi lần mở bài, hết hạn sau vài giờ. Mỗi request đều kiểm tra lại quyền trong database, nên người bị thu hồi mất quyền ngay. File bài có `Cache-Control: no-store` hoặc `private`.
- Trang app đặt `frame-src` chỉ cho phép địa chỉ của bài, để thử chặn iframe tự điều hướng ra ngoài. Hai reviewer không thống nhất việc này có hiệu lực với điều hướng do chính iframe tạo không, nên bước 2 phải thử thật trên từng trình duyệt. Dù kết quả thế nào, nếu iframe tải lại ngoài dự kiến, app vẫn gỡ khung và báo cho người học. Nếu không chặn được, ghi vào rủi ro còn lại. Đặt thêm `webrtc 'block'` ở trình duyệt có hỗ trợ.
- Các link ngoài trong bài không tự mở được. Cầu nối báo cho app, và app hỏi người học trước khi mở, có hiện rõ địa chỉ; chỉ nhận `https`.
- Thanh điều hướng "Về app" và ô Hỏi của app nằm ngoài iframe. App luôn hiện tên tác giả và dòng nhắc rằng trang bài không bao giờ hỏi mật khẩu.

**Cầu nối:** `MessageChannel` giữa trang app và iframe. Origin của trang bài luôn là `"null"` nên không dùng origin để xác thực: app so `event.source === iframe.contentWindow` lúc bắt tay, rồi chỉ dùng cổng riêng đó, và tạo lại cổng mỗi lần iframe tải lại. App kiểm tra kích thước, giới hạn tần suất ghi, và chỉ có các việc sau:
- Đọc, ghi dữ liệu của người này trong bài này.
- Báo đáp án quiz theo `id`; đúng sai do server tính.
- Xin mở ô Hỏi của app với một câu điền sẵn. Người học phải tự bấm gửi; trang không gọi AI trực tiếp.
- Xin mở link.

Trang không nhận được email người học, chỉ nhận một mã riêng theo từng package.

Shim hiện tại (`lesson-shim.js`) đang gọi API trực tiếp và phải viết lại trên cầu nối, vẫn giữ `claude.use` cho phần lưu dữ liệu của bài 1, 2. Ô Hỏi và "Tự giải thích lại" trong bài 1, 2 hiện tự dựng prompt ở trình duyệt; phần này phải sửa để đưa câu sang ô Hỏi của app. Câu chấm điểm hiện ra trong ô Hỏi, không còn hiện trong trang bài. Khung mẫu cho bài mới không có ô Hỏi riêng.

**Rủi ro còn lại, [Chủ dự án] đã chấp nhận để giữ JavaScript của tác giả:** JavaScript của tác giả vẫn chạy, nên trang xấu có thể hiện nội dung gây hiểu nhầm, kể cả màn hình đăng nhập giả trong khung. Kênh phụ như WebRTC hoặc DNS có thể còn lọt tùy trình duyệt. Trang chỉ giữ dữ liệu của chính bài đó và những gì người học gõ vào nó, không có cookie hay email. Cách xử lý là nhãn tác giả, dòng nhắc, góp ý và gỡ package.

**Văn bản do tác giả viết** (tên, tóm tắt, thẻ, quiz) và góp ý được app hiển thị ở phía app, luôn dưới dạng văn bản thuần.

Header CSP `sandbox`, `Sec-Fetch-Dest`, font và audio có tua (`Range`, `206`) trong sandbox cần chạy thử trước, trên Chrome, Safari iPhone và Android. Nếu không đạt, phương án dự phòng là phục vụ trang từ một hostname riêng cũng qua tunnel, vẫn giữ sandbox.

## 6. Tải lên và cập nhật

- Tác giả tải zip lên trong app. Server từ chối theo `Content-Length` trước khi đọc, ghi vào file tạm, vẫn đếm kích thước khi nhận. Giải nén trong thư mục riêng, chạy trong thread hoặc process để không treo worker duy nhất. Chặn tên trùng trong zip, đường dẫn tuyệt đối, `../`, `\`, ổ đĩa và symlink, rồi chạy bộ kiểm tra trên đúng các file đã giải nén.
- Mỗi phiên bản nằm trong thư mục không đổi `<package>/<phiên bản>/`. Đạt thì chỉ đổi con trỏ phiên bản hiện tại trong database, rồi xóa bản cũ. Không đạt thì hiện danh sách lỗi dễ hiểu, bài đang chạy không bị ảnh hưởng.
- Danh sách bài đọc từ database, không cần khởi động lại app. Thay `load_content()` và các bảng `LESSONS`, `BY_ID`, `BY_DOC`.
- Trước khi nhận, tác giả phải tích xác nhận: nội dung không chứa dữ liệu khách hàng hay thông tin mật, và họ có quyền dùng nội dung.
- Hạn mức dung lượng mỗi người, tính trên dung lượng đã giải nén. [Đề xuất] 1 GB, admin nâng được.
- Id trong database gắn với package do server cấp, không dùng id trần từ zip, để một tác giả không chạm được vào thẻ của package khác.
- Thẻ đã bị xóa khỏi bản mới thì không còn đến hạn. Thẻ giữ id thì tiến độ còn nguyên, kể cả khi đổi nội dung.
- Xóa package: chủ sở hữu xác nhận, người học mất quyền truy cập ngay.

## 7. Share

[Chủ dự án]
- Bấm share, nhập email hoặc copy link.
- Chỉ người có tài khoản trong app mới được share.

[Đề xuất]
- Email chưa có tài khoản thì báo ngay. Không gửi lời mời.
- Link chỉ mở được sau khi đăng nhập. Mọi tài khoản có link đều vào được, mở rồi thì package thêm vào mục "Được share" của họ. Chủ sở hữu tắt link hoặc tạo link mới được, và link cũ hết tác dụng.
- Chủ sở hữu thấy danh sách người có quyền và bỏ được từng người. Người bị bỏ không vào được nữa, dữ liệu tiến độ vẫn giữ.
- Người được share không share tiếp được.
- Token của link là chuỗi ngẫu nhiên 256 bit, lưu dạng băm, giới hạn tốc độ thử.

## 8. Góp ý

[Đề xuất]
- Ô góp ý theo từng bài, và nút Báo sai trên từng thẻ và câu quiz.
- Chủ sở hữu xem danh sách góp ý của package mình, có email người gửi; người gửi được báo trước điều này.
- Có lựa chọn "Báo nội dung vi phạm"; loại này admin cũng thấy.
- Văn bản thuần, tối đa 2.000 ký tự, giới hạn số lần gửi.

## 9. Ô Hỏi

[Chủ dự án]
- Ô Hỏi là tùy chọn và phải được admin duyệt.
- Khi được duyệt, AI đọc nội dung bài và trả lời theo nội dung đó.
- Dùng Internet để cập nhật hoặc kiểm tra lại thông tin là một tùy chọn bật tắt được.

[Đề xuất]
- AI đọc `content.md`, tóm tắt, thẻ và quiz của bài, có giới hạn độ dài. Server tự dựng prompt, người học và trang bài chỉ gửi được câu hỏi. Script đóng gói có thể tạo nháp `content.md` từ trang bài để tác giả sửa.
- Duyệt theo package. Tác giả bấm xin trong app, zip không tự khai được. Admin xem bài rồi đồng ý hoặc từ chối, kèm một công tắc Internet, mặc định tắt.
- Người học không tự bật Internet. Câu trả lời có dùng Internet phải tách phần lấy từ bài và phần lấy từ Internet, kèm link nguồn.
- Khi Internet tắt mà câu hỏi nằm ngoài bài, AI nói rõ bài không đề cập, không tự trả lời như thể có trong bài.
- Duyệt gắn với nội dung AI đọc. Bản mới có `content.md`, tóm tắt, thẻ hoặc quiz khác thì ô Hỏi tạm dừng và package trở lại danh sách chờ admin, để nội dung chưa ai xem không bị gửi ra ngoài. Bản mới chỉ đổi trang bài hoặc audio thì giữ nguyên duyệt. Admin tắt được bất cứ lúc nào.
- Khi admin tắt, app dừng gửi ngay.
- Nội dung tác giả viết được đưa vào prompt như dữ liệu, không phải lệnh. Câu trả lời tiếp tục qua DOMPurify, không cho thẻ ảnh. AI không có công cụ nào khác ngoài tìm kiếm.
- Câu hỏi dùng Internet có hạn mức riêng thấp hơn. Khóa API có trần chi tiêu do admin đặt ở nhà cung cấp.

Builder phải kiểm tra thực tế: tìm kiếm web của OpenRouter có dùng cùng ZDR được không, giá mỗi lượt, và phần nào của prompt bị gửi tới bộ tìm kiếm. [Chủ dự án] Điều kiện để bật Internet là giữ được ZDR. Không giữ được thì chưa làm công tắc Internet và báo chủ dự án, không tự nới. [Đề xuất] Có ZDR rồi vẫn ưu tiên chỉ gửi câu hỏi cho bộ tìm kiếm, nếu nhà cung cấp cho phép chọn. Chưa có khóa thì ô Hỏi vẫn báo chưa bật như hiện nay, và phần kiểm tra này chờ có khóa.

## 10. Skill

Tên dự kiến `creating-learn-packages`, để trong repo cùng bộ kiểm tra. [Đề xuất] App có nút tải "Bộ công cụ tác giả" ở màn hình Tải lên, gồm skill, bộ kiểm tra và khung mẫu, để đồng nghiệp lấy được dù repo vẫn private. Tác giả cần Python và Claude Code; ai không dùng Claude vẫn tạo được bài theo contract. Khung bài đầy đủ nằm ở `docs/lesson-format.md`.

[Chủ dự án] Contract chỉ bắt buộc trang bài, tóm tắt và thẻ. Skill có hai mức, chọn ở chặng 1:
- **Cơ bản**, mặc định cho người khác: trang bài theo khung mẫu đơn giản, tóm tắt, thẻ. Quiz, công cụ tương tác, mục Đi sâu là tùy chọn theo chủ đề.
- **Đầy đủ**, dùng cho chuỗi bài của chủ dự án: đúng khung chuẩn của bài 1, 2 gồm khởi động, 4–5 phần có công cụ tính thật và bước dự đoán, kiểm tra nhanh, áp dụng vào dự án, mục Đi sâu có công thức và link bài báo, quiz 8 câu có câu phải tự tính, kịch bản podcast. Mức này phải đối chiếu mọi con số với phép tính độc lập trước khi đóng gói.

Mức chỉ thay đổi những gì skill soạn và kiểm tra thêm, không đổi contract. Bộ kiểm tra có thêm tùy chọn `--profile full` để chặn nếu thiếu phần bắt buộc của mức Đầy đủ.

Các chặng, làm tiếp được khi đứt giữa chừng:
1. Hỏi chủ đề, đối tượng, tài liệu nguồn, và nhắc không đưa dữ liệu khách hàng vào.
2. Soạn trang bài theo khung trong `docs/lesson-format.md`, dùng khung HTML mẫu có sẵn cầu nối. Điểm dừng: tác giả duyệt.
3. Soạn tóm tắt, thẻ, quiz. Điểm dừng: tác giả duyệt.
4. Audio, nếu tác giả muốn: viết kịch bản, hướng dẫn tự tạo, nhận file, đổi sang mp3, kiểm tra thời lượng. Không bắt buộc.
5. Chạy bộ kiểm tra, đóng zip, báo cách tải lên. Không tự tải lên.

File skill ngắn, phần nặng để trong script. Trước khi viết, cho một agent mới không có skill thử tạo bài 3 để ghi lại chỗ nó làm sai, sau đó viết và thử lại theo `superpowers:writing-skills`.

## 11. Giao diện

Các màn hình mới cho người dùng là Thư viện, Tải lên, Share, Góp ý. [Chủ dự án] Thiết kế UI do Gemini làm; dùng ngôn ngữ của giao diện hiện có trong `web/`, chủ dự án chọn bản mẫu trước khi nối logic. Mobile vẫn là ưu tiên, ở 360 px không có cuộn ngang, nút tối thiểu 44 px.

Phần của tác giả (bài của tôi, share, xem góp ý) nằm trong Thư viện, không tách trang.

[Đề xuất] Trang quản lý `/admin` riêng, chỉ admin mở được, gồm: duyệt ô Hỏi và công tắc Internet, báo cáo vi phạm, gỡ package, dung lượng đã dùng. Claude tự làm trang này, không cần bản mẫu Gemini, dùng cùng màu, font, nút và nền sáng tối của giao diện hiện có, nhưng bố cục gọn hơn: bảng và danh sách thay cho thẻ lớn, trên điện thoại bảng chuyển thành từng dòng. Chủ dự án xem ảnh chụp trước khi xong.

## 12. Dữ liệu

Thêm các bảng package, phiên bản, quyền truy cập, link share, góp ý, duyệt Hỏi, cột admin cho `users`. Các bảng tiến độ hiện có khóa theo `lesson` và `card_id` phải gắn với id do server cấp.

[Chủ dự án] Bản hiện tại được deploy trước, chỉ cho chủ dự án. [Đề xuất] Khi chuyển sang bản nền tảng, tiến độ trên bản này có thể bị xóa, không viết script chuyển dữ liệu; sao lưu database trước khi đổi. Từ bản nền tảng trở đi cần cơ chế migration thật, vì `db.py` hiện chỉ có `CREATE TABLE IF NOT EXISTS`.

## 13. Bắt buộc kiểm tra

- Trang bài độc thử: đọc cookie, gọi `/api/*`, gọi ra ngoài, gửi form, mở trang mới, điều hướng trang cha, tự điều hướng khung ra ngoài, giả thông điệp cầu nối sai kiểu. Tất cả đều thất bại. Thử thêm WebRTC trên từng trình duyệt và ghi lại kết quả.
- Zip độc: đường dẫn `../`, đường dẫn tuyệt đối, tên trùng, symlink, bom nén, đuôi lạ, id lấy trùng của package khác, `.svg` có script mở trực tiếp.
- Quyền: người lạ, người bị thu hồi, link đã tắt, token hết hạn, token của người khác. Tất cả đều bị từ chối.
- Cập nhật: giữ id thì giữ tiến độ, xóa id phải xác nhận, tải lên lỗi không ảnh hưởng bản đang chạy.
- Ô Hỏi: chưa duyệt không có request nào ra ngoài, tắt Internet thì không có tìm kiếm, `content.md` chứa lệnh giả không đổi được vai trò AI, trang bài không tự gửi được câu hỏi khi người học chưa bấm.
- Bài 1, 2 trong sandbox: công thức, font, máy tính tương tác, quiz, audio tua được, trên Chrome và điện thoại thật.
- Mở trực tiếp đường dẫn trang bài trong tab mới bị từ chối, trên mọi trình duyệt thử.
- Chạy trình duyệt thật và xem ảnh, không chỉ tin kết quả test.
- Reviewer mới kiểm tra và thử tấn công bản chạy thật trước khi cấp tài khoản cho team.

## 14. Thứ tự xây

Mỗi bước dừng lại vẫn dùng được.

1. Contract và bộ kiểm tra. Chuyển bài 1, 2 sang contract.
2. Chạy thử sandbox và cầu nối với bài 1, 2. Quyết định đi tiếp hay dùng hostname riêng.
3. Danh sách bài từ database, tải lên, phiên bản.
4. Thư viện và share. Thiết kế màn hình bằng Gemini trước bước này.
5. Góp ý.
6. Admin, duyệt ô Hỏi, công tắc Internet.
7. Skill, thử bằng bài 3 do người thật tạo.
8. Review bảo mật, rồi mới cấp cho team.

Bản hiện tại được deploy trước để có URL thật cho bước 2. Bản đó chỉ chạy bài do chủ dự án tạo, không có nội dung của người khác, và chưa cấp cho team.

## 15. Cần chủ dự án xác nhận ngoài kỹ thuật

- Chính sách công ty về việc nhân viên đưa nội dung học lên VM này, và về việc gửi nội dung sang OpenRouter.
- Ai giữ vai trò admin ngoài chủ dự án.

## 16. Để builder tự quyết

Tên route, cấu trúc bảng, cách chia file, số giới hạn chưa nêu, cách ký token, thư viện kiểm tra file audio, cách hiển thị lỗi tải lên.
