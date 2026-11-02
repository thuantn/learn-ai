# App học AI trên điện thoại: thiết kế

Trạng thái: đã xây và đã deploy, chỉ chủ dự án dùng. Thiết kế đã qua một vòng phản biện độc lập trước khi xây. Tên riêng và thông tin hạ tầng đã được thay bằng mô tả chung để giữ repo sạch.

Ghi chú nguồn: **[Chủ dự án]** là điều chủ dự án đã nói hoặc đã chọn. **[Đề xuất]** là quyết định của người viết, có thể đổi.

## 1. Mục đích

Chủ dự án đang học AI qua các trang bài HTML và podcast, nhưng trang đăng trên claude.ai có ba vướng mắc: ô Hỏi tốn quota của tài khoản đang xem, mỗi bài lưu tiến độ riêng nên không ôn được câu sai xuyên bài, và khó chia sẻ cho team. Mục tiêu là học được trên điện thoại ở nhà, ngoài mạng công ty, rồi mở cho dev team nhỏ.

Thành công nghĩa là: người dùng mở app trên điện thoại ở nhà bằng 4G hoặc Wi-Fi, làm trọn một buổi học, và hôm sau được nhắc đúng các thẻ đến hạn, kể cả thẻ của bài trước.

## 2. Phạm vi

### Có trong bản đầu

- Buổi học 3 bước: tóm tắt ngắn, podcast, flashcard. **[Chủ dự án]**
- Trang bài đầy đủ như hiện tại, kèm quiz và ô Hỏi, nằm ngoài luồng chính. **[Chủ dự án]**
- Thẻ do AI soạn, người dùng duyệt trước khi đưa lên; câu quiz làm sai tự thành thẻ riêng của từng người. **[Chủ dự án]**
- Nghe podcast khi có mạng, app nhớ chỗ đang nghe. **[Chủ dự án]**
- Chủ dự án dùng thử trước, sau đó cấp quyền cho team; dữ liệu tách theo từng người từ đầu. **[Chủ dự án]**
- Lịch ôn theo FSRS, chấm Quên, Khó, Được, Dễ. **[Đề xuất]**
- Tua 15 giây, chỉnh tốc độ, điều khiển từ màn hình khóa qua Media Session API. **[Đề xuất]**
- Thêm app vào màn hình chính bằng một manifest đơn giản. **[Đề xuất]**

### Không làm ở bản đầu

- Nghe khi mất mạng và service worker. **[Chủ dự án]**
- App native, thông báo đẩy, bảng xếp hạng, chuỗi ngày học. **[Đề xuất]**
- Viết lại nội dung trang bài cho điện thoại. **[Đề xuất]**
- Giao diện web để duyệt thẻ. Thẻ được duyệt trong file, xem mục 5. **[Đề xuất]**

### Không được xảy ra

- Ảnh hưởng tới code, cấu hình, dữ liệu hoặc quota của app khác trên cùng VM.
- App học đọc được credential của app khác.
- Có dữ liệu khách hàng trong app này.
- Lộ khóa API hoặc mật khẩu trong log, trang web hay file được đóng gói.

## 3. Màn hình

Giao diện lấy theo bản mẫu do Gemini thiết kế, chủ dự án đã chọn. **[Chủ dự án]** Kết quả nằm ở `web/`. Bản mẫu là điểm xuất phát, những chỗ đã sửa khi xây: **[Đề xuất]**
- Đăng nhập và đổi mật khẩu là trang riêng, không hiện menu, trình phát, ô Hỏi.
- Bỏ các nút giả lập trạng thái, tab Đăng nhập, tab Kết thúc khỏi menu; sửa tab mất chữ ở nền sáng; thanh dock không che nút trên điện thoại.
- Bỏ màn hình bài giả lập: "Đọc bài đầy đủ" mở URL trang bài đã đóng gói. Audio dừng khi rời app và mở lại đúng chỗ khi quay về.
- Ô Hỏi ở cột phải (máy tính) hoặc nút nổi (điện thoại) trong app, theo bản mẫu. Trang bài vẫn có ô Hỏi riêng.
- Chuyển mọi `onclick` sang `addEventListener` trong file JS, tự host font, theo CSP ở mục 5A.
- Màn hình Kết thúc có trong luồng, sau thẻ cuối.

| Màn hình | Nội dung | Hành động |
|---|---|---|
| Trang đầu | Danh sách bài, số thẻ đến hạn | Bắt đầu buổi học, Đọc bài đầy đủ |
| Bước 1, Ôn lại | Tóm tắt đọc trong khoảng 2 phút | Nghe podcast, Đọc bài đầy đủ |
| Bước 2, Nghe | Chọn bản 5 hoặc 10 phút, thanh tua, tốc độ | Làm flashcard |
| Bước 3, Flashcard | Thẻ đến hạn, gồm cả thẻ từ các bài trước | Lật thẻ, chấm 4 mức |
| Trang bài đầy đủ | Trang hiện tại, gồm công cụ, Đi sâu, quiz, ô Hỏi | Quay về app |

Giao diện dùng được cả trên web máy tính và điện thoại, chung một app. **[Chủ dự án]** Bước nào cũng bỏ qua được. Trên điện thoại ưu tiên thao tác một tay; trên máy tính dùng hết chiều rộng hợp lý và có phím tắt. Kiểm tra không tràn ngang từ 360 đến 1920 px. **[Đề xuất]**

## 4. Hạ tầng

Làm app riêng, chạy trên một VM nội bộ dùng chung, tách khỏi các app khác trên máy đó. **[Chủ dự án]**

- Docker Compose project riêng, chạy bằng user Linux riêng, không có quyền đọc home của app khác. **[Đề xuất]**
- Cloudflare Tunnel riêng, không sửa cấu hình tunnel của app khác. Không mở cổng trên host. **[Đề xuất]**
- Đặt giới hạn bộ nhớ container, đề xuất 512 MB. **[Đề xuất]**
- Không dùng self-hosted runner. Deploy thủ công bằng cách chép gói mới lên VM rồi build lại container, xem `docs/operations.md`. **[Đề xuất]**
- Dữ liệu và sao lưu dùng bind mount trong home của user `learnai`, container chạy đúng uid đó. App tự sao lưu lúc khởi động và mỗi 24 giờ bằng `sqlite3.Connection.backup` sang thư mục sao lưu, giữ 14 bản. **[Đề xuất]**
- SQLite dùng `journal_mode=WAL`, `busy_timeout=5000`, uvicorn 1 worker. **[Đề xuất]**

Heroku không dùng ở bản đầu vì Eco ngủ sau 30 phút, cần thêm Postgres, và nền tảng đã ngừng phát triển tính năng mới. Đây là phương án dự phòng khi VM quá tải hoặc không còn được phép dùng. **[Đề xuất]**

Lưu ý vận hành: VM dùng chung có lúc tải cao, và container cần `restart: unless-stopped` để tự chạy lại khi máy khởi động lại.

## 5. Xây thế nào

**Repo.** Hiện để private, dự định public sau. **[Chủ dự án]**

Repo được giữ sạch như repo public ngay từ commit đầu, để có thể đổi sang public bất cứ lúc nào. Repo chứa code, không chứa nội dung bài hay thông tin hạ tầng: **[Đề xuất]**
- Trong repo: server, giao diện, script đóng gói, test, Dockerfile, compose mẫu, một bài mẫu ngắn tự viết.
- Không đưa vào repo: trang bài, kịch bản podcast, tóm tắt, thẻ (dựa trên khóa học có bản quyền của người khác, chưa rà soát); audio; `data/`; mọi file `.env`; tên miền, tên VM, email. Tài liệu thiết kế đưa vào repo sau khi đã bỏ các thông tin này.
- Thư mục nội dung đặt ngoài repo, đường dẫn đặt qua biến môi trường, chép lên VM cùng với audio.
- Cấu hình thật nằm trên VM trong file quyền 600.
- Không dùng self-hosted runner, vì repo public cho phép người ngoài kích hoạt code trên runner. CI chạy trên máy GitHub; deploy thủ công.
- Trước mỗi lần đổi repo sang public: quét secret toàn bộ lịch sử, và tìm danh sách tên riêng giữ ngoài repo. Lịch sử public coi như không thu hồi được.


**Server.** FastAPI, uvicorn và SQLite. Giao diện dùng HTML và JavaScript thuần; thêm React khi thực sự cần. **[Đề xuất]**

**Bảo mật.** Xem mục 5A. Mọi mục trong đó là điều kiện để mở ra Internet.

**Trang bài.** `scripts/package_content.py` đóng gói các bài và thay `window.claude` bằng lớp shim gọi API của server. Mỗi bài thêm link quay về app và báo kết quả quiz cho server.

**Nội dung mới của mỗi bài**, nằm cạnh trang bài trong thư mục nguồn:

```
BaiNN-Ten/app/summary.md     tóm tắt, 4 đến 6 ý
BaiNN-Ten/app/cards.json     thẻ đã duyệt: id ổn định, câu hỏi, đáp án
```

Claude soạn hai file này từ nội dung bài, tạo một bản nháp `cards.draft.json`; người dùng đọc và đổi tên thành `cards.json` để duyệt. Script đóng gói từ chối bài không có `cards.json`. Mỗi bài khoảng 10 đến 15 thẻ. Đối chiếu con số và công thức trong thẻ với trang bài. **[Đề xuất]**

**Dữ liệu theo từng người** (SQLite):

```
card_state(user, card_id, due, stability, difficulty, reps, lapses, last_review, state)
review_log(user, card_id, rating, reviewed_at)
listen_pos(user, episode, seconds, updated_at)
wrong_card(user, card_id, lesson, question, answer, created_at)
lesson_progress(user, lesson, status, track, updated_at)
```

**Mở thẻ và trạng thái bài.** Thẻ của bài chỉ vào `card_state` khi người dùng bấm "Bắt đầu buổi học" ở bài đó, để người mới không bị dội toàn bộ thẻ. Thẻ mới đến hạn ngay. Trạng thái `in_progress` khi bắt đầu, `done` khi xong màn hình Kết thúc lần đầu; không tự quay lại `in_progress`. **[Đề xuất]**

**Hai bản podcast.** `episode` có dạng `<lesson>:short` và `<lesson>:long`, mỗi bản nhớ vị trí riêng. `lesson_progress.track` lưu bản đang nghe gần nhất; trang đầu hiện bản đó. Manifest của gói khai báo tên file và thời lượng từng bản. **[Đề xuất]**

**Thẻ từ câu sai.** Câu quiz có id ổn định, ví dụ `b02-q3`. Script đóng gói trích câu hỏi và đáp án từ dữ liệu trong trang bài ra `quiz.json` cho server. Không cần sửa logic quiz của trang bài: trang vẫn lưu trạng thái qua shim `PUT /api/doc/<tên>`, server so các câu trả lời mới trong tài liệu đó với `quiz.json`, chọn sai thì tạo `wrong_card` đến hạn ngay. Làm sai lại cùng một câu không tạo thêm thẻ trùng. Đã có thẻ thì việc làm đúng hay sai trong quiz sau đó không đổi lịch; lịch chỉ do bước flashcard quyết định. **[Đề xuất]**

**Công thức.** Tóm tắt và thẻ viết bằng ký tự Unicode, không dùng LaTeX. Câu trả lời của ô Hỏi trong app dùng marked, DOMPurify và MathJax bản đi kèm, như trang bài; không dùng hàm parse Markdown tự viết trong bản mẫu. **[Đề xuất]**

**FSRS.** Dùng thư viện `fsrs` của Python với tham số mặc định. Múi giờ tính ngày đến hạn là `Asia/Ho_Chi_Minh`. Dừng giữa chừng thì lần sau làm tiếp các thẻ còn đến hạn. **[Đề xuất]**

**Chuyển bước.** Bước Nghe lưu vị trí khoảng 10 giây một lần, khi tạm dừng và khi rời trang. Nếu vị trí còn dưới 15 giây so với hết bài thì lần sau nghe từ đầu. **[Đề xuất]**

**Tiến độ cũ.** Tiến độ trên artifact claude.ai không chuyển sang. **[Đề xuất]**

**Mô hình.** Ô Hỏi gọi OpenRouter, mô hình mặc định `deepseek/deepseek-v4.1-flash`, đổi được qua `AI_MODEL`. **[Đề xuất]**

## 5A. Bảo mật khi mở ra Internet

Không hệ thống nào đảm bảo tuyệt đối không bị hack. Mục tiêu là: người lạ không chạm được vào app, và nếu app bị xâm nhập thì thiệt hại chỉ nằm trong app học, không lan sang app khác hay VM. **[Đề xuất]**

**Lớp 1, đăng nhập do app tự làm.** Mỗi người có tài khoản riêng; không dùng Cloudflare Access. **[Chủ dự án]**
- Không có đăng ký công khai. Quản trị tạo tài khoản bằng lệnh trên VM, lệnh in mật khẩu tạm một lần. Lần đăng nhập đầu phải đổi mật khẩu.
- Không có quên mật khẩu qua email. Quản trị cấp lại mật khẩu tạm bằng lệnh; việc này xóa mọi phiên của người đó.
- Mật khẩu băm Argon2id với m=19456 KiB, t=2, p=1. Dài tối thiểu 15 ký tự, tối đa ít nhất 64, không bắt buộc loại ký tự, không cắt ngắn, từ chối mật khẩu phổ biến theo danh sách đi kèm.
- Đăng nhập sai bị giới hạn theo IP và theo cặp (tài khoản, IP), với thời gian chờ tăng dần, không khóa vĩnh viễn; thêm trần theo tài khoản ở ngưỡng cao để chặn dò từ nhiều IP. Cách này tránh người ngoài làm chủ tài khoản bị khóa từ xa. Sai thông tin luôn trả `401` với cùng một câu; vượt ngưỡng trả `429`, áp dụng cả cho tài khoản không tồn tại. Tài khoản không tồn tại vẫn chạy băm để thời gian trả lời tương đương.
- Kiểm tra giới hạn trước khi băm; tối đa 2 phép băm chạy cùng lúc để tránh tràn RAM.
- Phiên có cờ phải đổi mật khẩu chỉ gọi được đổi mật khẩu và đăng xuất; mọi route khác trả `403`. Lỗi mật khẩu phổ biến hiện trên trang đổi mật khẩu.
- IP thật lấy từ `cf-connecting-ip` chỉ khi IP nguồn đúng là IP của container tunnel, phân giải từ tên service. App và tunnel nằm trên một mạng Docker riêng, không container nào khác vào được.

**Lớp 2, phiên đăng nhập.**
- ID phiên ngẫu nhiên 256 bit, chỉ lưu bản băm SHA-256 trong SQLite. Tạo ID mới khi đăng nhập và đổi mật khẩu; đổi mật khẩu xóa các phiên khác; đăng xuất xóa ở server.
- Cookie `__Host-session`, `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`.
- Hết hạn sau 7 ngày không dùng và tối đa 30 ngày. Dài hơn ví dụ của OWASP vì đây là app học rủi ro thấp, dùng trên điện thoại và không có dữ liệu nhạy cảm. Có lệnh để quản trị xóa toàn bộ phiên của một người. **[Đề xuất]**
- Middleware kiểm tra phiên trên mọi request, trừ trang đăng nhập và file tĩnh của trang đó. Mặc định từ chối. Thời điểm dùng cuối chỉ ghi vào SQLite tối đa mỗi giờ một lần, để không ghi trên mỗi request audio.
- Hết phiên khi đang học thì đưa về đăng nhập, giữ tiến độ đã lưu.
- Bổ sung sau nếu cần: TOTP. Không làm ở bản đầu vì app rủi ro thấp và mật khẩu đã dài; đổi lại, mật khẩu là lớp bảo vệ duy nhất ở cổng vào.

**Lớp 3, ứng dụng.**
- Mọi thay đổi dữ liệu dùng POST hoặc PUT với JSON, kiểm tra `Origin` đúng tên miền của app, giới hạn kích thước body.
- Dữ liệu luôn lọc theo người dùng của phiên, không lấy từ dữ liệu trình duyệt gửi; câu SQL dùng tham số.
- File tĩnh chỉ phục vụ từ danh sách do script đóng gói tạo ra, không liệt kê thư mục, không theo symlink. Audio và trang bài cũng phải có phiên hợp lệ.
- Câu trả lời AI là dữ liệu không tin cậy: chạy qua DOMPurify trước khi hiển thị.
- Header: `Content-Security-Policy` với `default-src 'self'` và không cho script inline. Trang app không dùng thuộc tính `on*`. Trang bài hiện không có `on*` và chỉ có vài khối script, nên script đóng gói chuyển các khối đó ra file riêng theo đúng thứ tự, shim nạp đồng bộ đầu `<head>`. `style-src` cho `'unsafe-inline'` nếu trang bài và MathJax cần. Font và thư viện tự host. Cùng với đó là `frame-ancestors 'none'`, `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`.
- Không có trang lỗi lộ stack trace. Tắt `/docs` và `/openapi.json`.

**Lớp 4, ô Hỏi.**
- Server tự đặt model, prompt hệ thống và `max_tokens`. Ô Hỏi trong app gửi `{lesson, question}`, server tự nạp `summary.md` và thẻ của bài làm ngữ cảnh. Trang bài đang tự ghép prompt ở trình duyệt, nên `POST /api/ask` cũng nhận `{lesson, input}` với trần độ dài; người đã đăng nhập vì thế có thể hỏi nội dung bất kỳ trong hạn mức, chấp nhận được với nhóm nhỏ.
- Chưa có khóa OpenRouter riêng thì ô Hỏi báo chưa bật; không mượn khóa của app khác.
- AI không có tool và không đọc được dữ liệu nào ngoài nội dung gửi kèm, nên prompt injection không tiếp cận được dữ liệu người khác. Prompt hệ thống không chứa bí mật.
- Giới hạn câu hỏi theo phút và theo ngày cho mỗi người, ở server.
- Khóa OpenRouter riêng cho app, có trần chi tiêu thấp ở phía OpenRouter, không dùng chung với app khác.
- Gửi `provider: {"zdr": true}`. Tài liệu OpenRouter không nói rõ khi không có nhà cung cấp đạt điều kiện thì sao, nên phải test bằng khóa thật; nếu lỗi thì trả lỗi rõ ràng, không gửi lại không có ZDR. Nếu model mặc định không có endpoint ZDR thì đổi model qua `AI_MODEL`. Test tự động dùng API giả; gọi thật chỉ trong smoke test sau deploy.
- Log không chứa nội dung câu hỏi, câu trả lời hay khóa.

**Lớp 5, container và VM.**
- Chạy uid riêng. `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges`, `tmpfs` cho `/tmp`, giới hạn RAM, CPU, số process.
- Mạng Docker riêng, không có cổng host, không mount Docker socket, không mount gì ngoài dữ liệu của app. Audio mount chỉ đọc. Khóa nằm trong file quyền 600, không nằm trong image.
- **Hạn chế đã biết:** user trong nhóm `docker` tương đương root trên VM, nên các lớp trên chỉ cách ly tiến trình app. Người có quyền deploy vẫn đọc được dữ liệu của các app khác trên máy này.
- Container tự khởi động lại; lỗi ở app không ảnh hưởng app khác.

**Lớp 6, chuỗi cung ứng và repo.**
- Ghim phiên bản phụ thuộc bằng lockfile có hash, ghim digest của image, ghim phiên bản `cloudflared`.
- CI chạy test và `pip-audit`; bật Dependabot và secret scanning; không commit secret; `main` có branch protection nếu org cho phép.

**Lớp 7, theo dõi.**
- Log ghi tên người dùng, đường dẫn, mã trạng thái, các lần đăng nhập sai, xoay vòng bằng log của Docker. Không ghi mật khẩu hay ID phiên. Trần chi tiêu đặt ở OpenRouter, app không tự cảnh báo.
- Khi lộ khóa hoặc nghi bị xâm nhập: thu hồi khóa OpenRouter và credential của tunnel; xóa mọi phiên; cấp lại mật khẩu; ghi cách làm vào `LESSONS_LEARNED.md`.

**Trước khi mở ra Internet:** một reviewer mới, không biết lý do thiết kế, đọc lại phần bảo mật và thử tấn công bản chạy thật. Bản sửa lỗi cũng được xem lại.

## 6. Bài kiểm tra bắt buộc

Tự động, chạy trước mỗi lần deploy:
1. Không có phiên hợp lệ thì không vào được trang, audio hay API. Thử thiếu cookie, cookie giả, phiên hết hạn, phiên đã đăng xuất, phiên cũ sau khi đổi mật khẩu, và người chưa đổi mật khẩu tạm. Đăng nhập sai liên tục bị chặn; lỗi giống nhau với tài khoản có và không có; cookie có đủ thuộc tính; không thấy mật khẩu hay ID phiên dạng rõ trong database và log.
2. Hai người không thấy tiến độ và thẻ của nhau, kể cả khi đổi tham số trong request.
3. Origin lạ bị từ chối; `/docs`, file nguồn, dữ liệu và đường dẫn có `..` đều không truy cập được; các header bảo mật có mặt; đầu ra AI có `<script>` không chạy; giới hạn câu hỏi có hiệu lực.
4. FSRS: chấm Quên làm thẻ đến hạn sớm hơn chấm Dễ.
5. Làm sai quiz tạo đúng một thẻ, và thẻ hiện ở bài sau.
6. Ô Hỏi trả lời có công thức hiển thị đúng; dùng câu trả lời thật, xem `LESSONS_LEARNED.md`.
7. Audio tua được và nghe lại đúng chỗ.
8. Không tràn ngang ở 400px trên mọi màn hình.

Thủ công, trước khi cấp tài khoản cho team:
- Trên điện thoại thật bằng 4G: đăng nhập, đổi mật khẩu tạm, làm trọn buổi học, khóa màn hình trong lúc nghe podcast, và thử khi phiên hết hạn giữa chừng (app phải đưa về đăng nhập mà không mất tiến độ).
- Từ một container khác trên VM, gọi thẳng vào app mà không có phiên: phải bị từ chối, và header `cf-connecting-ip` giả không làm thay đổi IP dùng để giới hạn đăng nhập.
- Kiểm tra cả iPhone Safari nếu trong team có người dùng iPhone.

Đo bộ nhớ thực tế của container bằng `docker stats`, vì các số trước đây chỉ là ước tính.

## 7. Cần có trước khi triển khai

Chủ dự án cung cấp:
- Khóa OpenRouter riêng có trần chi tiêu, để bật ô Hỏi.

Quyền admin VM và chứng chỉ Cloudflare để tạo tunnel được giữ ngoài repo, xem `docs/operations.md`.

## 8. Thứ tự xây

0. Trong repo đã tạo: chép code, tách nội dung và cấu hình thật ra ngoài repo.
1. Dựng server FastAPI tối thiểu với đăng nhập, phiên, Lớp 3 và test bảo mật ở mục 6, chưa có tính năng.
2. Dựng tunnel ở tên miền thật, chưa cấp tài khoản cho ai ngoài người dùng, trang chỉ có "Đã vào được"; thử từ điện thoại và thử gọi thẳng container.
3. Soạn tóm tắt và thẻ cho bài 1, bài 2; người dùng duyệt.
4. Xây trang đầu, 3 bước, FSRS, thẻ từ câu sai.
5. Reviewer mới kiểm tra bảo mật như mục 5A. Chủ dự án dùng thử 1 đến 2 tuần trên điện thoại thật.
6. Sửa theo phản hồi rồi cấp tài khoản cho team.
