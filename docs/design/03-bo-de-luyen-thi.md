# Bộ đề luyện thi: thiết kế

Trạng thái: **đã qua phản biện (DeepSeek, GLM, agy, một builder), đã xây xong.**

Trong tài liệu, **[Chủ dự án]** là điều người dùng đã quyết định. **[Đề xuất]** là quyết định của người viết, chủ dự án có thể đổi.

## 1. Mục đích

[Chủ dự án] Người dùng tự soạn bộ đề trắc nghiệm kiểu thi chứng chỉ, hiện bằng Gemini Canvas, làm hết các bộ, khi cần bật chế độ luyện tập để biết ngay đúng sai. Bộ nào hay thì muốn share cho đồng nghiệp làm trên app, giống như share bài học. Đề do người dùng tự soạn, không phải câu thi thật.

[Chủ dự án] Đề có thể được soạn bằng Gemini, Claude hay ChatGPT, không phụ thuộc AI nào.

Thành công nghĩa là:
- Bộ đề Gemini mà chủ dự án đang có lên được app mà không phải gõ lại. File đó là một trang HTML gồm 3 bộ, mỗi bộ 60 câu (161 câu chọn một, 19 câu chọn hai), 105 phút, ngưỡng đậu 78%.
- Một đồng nghiệp được share mở ra làm được trên máy tính và điện thoại, xem kết quả theo từng lĩnh vực, rồi ôn lại đúng những câu đã sai.

## 2. Phạm vi

### Có

- Bộ đề nằm trong package, cạnh bài học. Package chỉ có bộ đề cũng hợp lệ.
- Hai chế độ khi bắt đầu làm: Thi thử và Luyện tập.
- Trang kết quả, mục Ôn câu sai, giải thích sâu bằng AI, giọng đọc, chỉnh cỡ chữ, tạm dừng giờ.
- Tải lên một file bộ đề `.json` duy nhất, không cần đóng gói.
- Nhánh bộ đề trong skill hiện có, và một đoạn hướng dẫn copy được cho Gemini, ChatGPT.
- Thống kê từng câu cho tác giả, gộp chung và ẩn danh.

### Không làm ở bản này

- Soạn hay sửa câu hỏi ngay trên app. Tác giả sửa file rồi tải lại.
- Câu tự luận, kéo thả, điền chỗ trống. Chỉ có chọn một và chọn nhiều đáp án.
- Bảng xếp hạng, so điểm giữa người làm.
- Giọng đọc của Gemini hay dịch vụ ngoài.

### Không được xảy ra

- Người làm thấy đáp án trước khi được phép, kể cả bằng cách đọc mã nguồn, xem request mạng hay gọi API trực tiếp.
- Mục ôn câu sai sinh ra hàng loạt bộ đề rác. [Chủ dự án] "Đừng cho tạo quá nhiều, sợ rác."
- Khóa API của AI xuất hiện trong trình duyệt, như cách file Gemini gọi thẳng API từ trang.
- Đổi máy hay tải lại trang thì mất bài đang làm.
- Đề sai đáp án mà tác giả không có cách nào phát hiện.

## 3. Khái niệm

- **Bộ đề:** một danh sách câu hỏi, có thời gian và ngưỡng đậu. Thuộc một package.
- **Câu:** một câu hỏi chọn một hoặc chọn nhiều, có lời giải.
- **Lượt làm:** một lần một người làm một bộ đề, ở một chế độ. Lưu trên server.
- **Ôn câu sai:** với mỗi người và mỗi bộ đề, tập các câu người đó đang sai.

## 4. Định dạng bộ đề

[Đề xuất] Các trường bám sát dữ liệu mà Gemini đã tự sinh trong file của chủ dự án, để AI nào cũng xuất ra được mà ít phải dạy.

Trong package:

```
package.json            thêm "tests": ["<test-id>", ...]
tests/<test-id>.json
lessons/...             như hiện nay, có thể không có
```

`package.json`: `lessons` và `tests` mỗi cái có thể rỗng, không được rỗng cả hai. Tối đa 20 bộ đề. Id bộ đề không trùng id bài trong cùng package.

`tests/<test-id>.json`:

| Trường | Bắt buộc | Ghi chú |
|---|---|---|
| `title` | có | tối đa 200 ký tự |
| `description` | không | tối đa 1.000 ký tự |
| `lang` | không | `vi` hoặc `en`, mặc định `vi`. Dùng cho giọng đọc |
| `time_limit_minutes` | không | 0 hoặc không có là không giới hạn, tối đa 600 |
| `pass_percent` | không | 1–100, mặc định 70 |
| `items` | có | 1–200 câu |

Mỗi câu trong `items`:

| Trường | Bắt buộc | Ghi chú |
|---|---|---|
| `id` | có | chữ thường, số, gạch nối. Không trùng trong bộ đề; hai bộ đề được dùng cùng id. Giữ nguyên qua các phiên bản |
| `domain` | không | lĩnh vực chính, dùng để chia điểm. Tối đa 100 ký tự. So không phân biệt hoa thường; không có thì vào nhóm "Khác" |
| `type` | có | `single` hoặc `multi` |
| `question` | có | tối đa 4.000 ký tự, Markdown |
| `options` | có | 2–8 lựa chọn, mỗi lựa chọn `id` (một chữ hoa A–H, không trùng), `text` (tối đa 1.000 ký tự), `why` (không bắt buộc, tối đa 1.000 ký tự: vì sao đúng hoặc sai) |
| `correct` | có | danh sách id lựa chọn đúng. `single`: đúng 1. `multi`: từ 2 trở lên. Số phải chọn suy ra từ danh sách này |
| `explanation` | có | lời giải chung, Markdown, tối đa 4.000 ký tự |
| `best_practice` | không | tối đa 1.000 ký tự |
| `docs` | không | tối đa 5 link `https` |
| `shuffle` | không | `false` để giữ nguyên thứ tự lựa chọn, mặc định `true` |

Mỗi file tối đa 5 MB. Toàn bộ đề của một package cộng lại tối đa 16 MB, vì đề được chép vào database. Bộ kiểm tra dùng chung cho `learnpkg.py` và server, báo lỗi theo từng câu, ghi rõ id bộ đề và id câu. Bộ kiểm tra cũng:
- từ chối ký tự vô hình, như lesson hiện nay;
- từ chối link không phải `https` trong `docs` và trong Markdown;
- cảnh báo khi chữ trong câu, lựa chọn, `why` hoặc lời giải nhắc tới tên lựa chọn (A, B, "Cả A và B") mà câu đó vẫn xáo;
- cảnh báo khi một bộ đề có hơn 12 lĩnh vực.

[Đề xuất] Trường `scenario` trong file Gemini gộp vào `question`. `requiredCount` bỏ, vì suy ra được từ `correct`. Lĩnh vực ghép kiểu "Case Management & Incident Handling" chỉ lấy phần chính: file của chủ dự án có 37 tên lĩnh vực cho 180 câu, giữ nguyên thì bảng điểm vụn và vô dụng.

**Một file `.json` tải thẳng lên:** [Đề xuất] một file là một package chỉ có bộ đề, gồm `slug`, `title`, `topic`, `description` như `package.json`, và `tests`: danh sách bộ đề, mỗi bộ có thêm `id` cùng các trường ở bảng trên.
- Hộp Tải lên nhận một hoặc nhiều file `.json` cùng `slug`, hoặc dán chữ JSON vào ô. Trình duyệt ghép chúng thành một file rồi gửi, nên người dùng Gemini, ChatGPT không phải tự ghép.
- Server tách file đó thành `package.json` và `tests/*.json` trong thư mục tạm, rồi đi tiếp đúng đường tải zip hiện có: hạn mức, ổ đĩa, xác nhận thay đổi. Không có đường tải riêng.
- Tải lại cùng `slug` thì thành bản mới, theo luật tải lên hiện có: id bộ đề hay id câu biến mất thì tác giả phải xác nhận.
- Package có cả bài học thì vẫn đóng gói zip như hiện nay.

## 5. Làm bài

[Đề xuất] Trang làm bài là giao diện của app, không chạy trong sandbox như trang bài học. Nội dung đề là dữ liệu chứ không phải mã, nên app tự vẽ được.

**Vì đề hiện ngay trong trang của app, chữ của tác giả phải qua một bộ lọc chặt hơn ô Hỏi:** chỉ cho phép đoạn văn, xuống dòng, đậm, nghiêng, code, khối code, danh sách, trích dẫn, bảng và link. Không có `class`, `id`, `style`, không ảnh, không SVG, không audio, video. Bản DOMPurify hiện tại mặc định cho phép thẻ `style`, và CSP của app có `unsafe-inline`, nên bộ lọc mặc định không đủ. Bấm link trong đề mở hộp hỏi trước như trang bài học, chỉ nhận `https`. Đề không dùng MathJax ở bản này. Chữ giới hạn ngắn như lĩnh vực, tiêu đề, lựa chọn thì chỉ hiện bằng `textContent`.

- **Bắt đầu:** chọn Thi thử hoặc Luyện tập. Đang có lượt dở ở chế độ đó thì mặc định là Tiếp tục; Làm lại phải bấm riêng và xác nhận. Mỗi người, mỗi bộ đề, mỗi chế độ có tối đa một lượt dở. Lượt ôn câu sai tính riêng.
- **Thứ tự:** xáo câu và xáo lựa chọn ở mỗi lượt, trừ câu `shuffle: false`. Thứ tự lưu theo lượt. Lựa chọn hiện theo vị trí mới, A, B, C… theo thứ tự hiển thị.
- **Lưu:** mỗi câu lưu riêng lên server ngay khi chọn, kể cả câu chọn nhiều mới chọn một phần, kèm cờ xem lại. Lưu lỗi thì hiện "Chưa lưu" và tự thử lại; chưa lưu xong thì chưa nộp được. Tải lại, đổi máy hay trở lại tab thì lấy trạng thái từ server. Hai máy cùng mở thì lần lưu sau cùng thắng, theo từng câu.
- **Thi thử:** không biết đúng sai cho tới khi nộp. Không có ô Hỏi cho tới khi nộp. Câu chưa làm được bỏ qua; khi nộp app liệt kê các câu chưa làm và cờ, rồi hỏi xác nhận. Câu chưa làm tính là sai.
- **Luyện tập:** chọn xong bấm Kiểm tra. Server trả về đúng sai, đáp án đúng, lời giải và `why` của từng lựa chọn. Đã kiểm tra thì không đổi được câu đó. Có giờ đếm lên để tham khảo, không giới hạn.
- **Chọn nhiều:** Kiểm tra cần đúng số lựa chọn suy ra từ `correct`, và câu ghi rõ "chọn 2". Chấm kiểu được hết hoặc mất hết.
- **Đánh dấu xem lại:** gắn cờ một câu. Lưới số câu cho biết câu nào đã làm, câu nào gắn cờ. Trên điện thoại lưới nằm trong khung kéo lên, để không che đề.
- **Giờ:** server tính giờ từ lúc bắt đầu, trừ các lần dừng. Đồng hồ trên trang chỉ để hiển thị. Hạn giờ có 5 giây trừ hao đường truyền.
- **Hết giờ:** trang đang mở thì tự nộp. App không có tác vụ nền, nên bất cứ lần đọc hay ghi nào vào một lượt Thi thử đã quá giờ cũng tự chốt lượt đó bằng các câu đã lưu, tính thời điểm nộp bằng đúng lúc hết giờ. Đóng máy rồi hôm sau mở lại vẫn thấy kết quả, không bị kẹt.
- **Tạm dừng:** [Chủ dự án] có. Áp dụng cả hai chế độ, không giới hạn số lần, không giới hạn thời gian. [Đề xuất] Khi dừng, đề bị che và server từ chối lưu, kiểm tra, nộp. Trang kết quả ghi số lần và tổng thời gian đã dừng. Đóng trang mà không bấm dừng thì giờ vẫn chạy, như đi thi thật.
- **Cỡ chữ:** nút chữ nhỏ hơn, chữ lớn hơn, nhớ theo từng máy bằng `localStorage`, như nền sáng tối hiện có.
- **Giọng đọc:** [Đề xuất] dùng giọng có sẵn trong trình duyệt (Web Speech). Đọc câu hỏi rồi các lựa chọn, theo `lang` của bộ đề, có nút dừng. Máy không có giọng hợp ngôn ngữ thì ẩn nút và nói rõ lý do. Không gửi gì ra ngoài.
- **Báo sai câu này:** mở rộng phần góp ý hiện có để nhận bộ đề và id câu.

## 5a. Khi tác giả tải bản mới

[Đề xuất] Mỗi bộ đề có các **bản đề** không đổi. Bản mới chỉ được thêm khi nội dung thật sự khác. Lượt làm ghi nó thuộc bản nào, nên không phải chép đề vào từng lượt. Bản không còn lượt nào dùng và không phải bản hiện tại thì được dọn đi.

- **Lượt đang làm:** làm và nộp trên bản đã bắt đầu. Không bị hủy giữa chừng.
- **Kết quả cũ:** giữ nguyên như đã chấm, xem lại đúng đề lúc đó.
- **Thống kê cho tác giả:** mỗi câu có một mã đáp án, tính từ danh sách lựa chọn và `correct`. Sửa đáp án thì thống kê của câu đó bắt đầu lại; sửa lỗi chính tả thì không.
- **Ôn câu sai:** câu vẫn ở trong mục, từ giờ chấm theo bản mới. Mã đáp án đổi thì đếm lại từ đầu. Câu bị xóa thì rời khỏi mục.

## 5b. Đáp án đã thấy rồi thì sao

[Đề xuất] Không theo dõi "đã từng thấy". Luật nằm ở từng API và từng lượt:
- Lượt Thi thử chưa nộp: không API nào trả đáp án, lời giải hay `why` của lượt đó.
- Lượt Luyện tập và lượt ôn: chỉ trả cho câu đã bấm Kiểm tra trong lượt đó.
- Lượt đã nộp: xem lại được hết, kể cả khi đang làm lượt khác.

Người làm vẫn có thể Luyện tập trước để biết đáp án rồi mới Thi thử, hoặc mở kết quả cũ. Đây là đề tự ôn nội bộ, nên điểm Thi thử chỉ có nghĩa khi người làm tự trung thực; khóa thêm chỉ gây phiền mà không ngăn được ai nhớ đáp án. Mọi phản biện đã nêu điểm này; đây là quyết định có chủ ý.

## 6. Kết quả

- Điểm, phần trăm, Đậu hay Chưa đậu theo `pass_percent`, thời gian làm.
- Điểm theo từng `domain`: số đúng trên số câu và phần trăm, sắp phần yếu nhất lên đầu.
- Xem lại từng câu: người làm chọn gì, đáp án đúng, lời giải, `why` của từng lựa chọn, best practice, link tài liệu. Lọc được: tất cả, chỉ câu sai, câu gắn cờ.
- Nút Hỏi về câu này, Ôn câu sai, Làm lại.
- Lịch sử các lượt của người đó với bộ đề: ngày, chế độ, điểm.

## 7. Ôn câu sai

[Chủ dự án] Tổng hợp câu sai thành một bộ để ôn riêng, nhưng không để sinh nhiều.

[Đề xuất] Không tạo bộ đề mới. Mỗi người có đúng **một mục Ôn câu sai cho mỗi bộ đề**, tự cập nhật:
- **Vào:** câu đã chọn đáp án mà sai, ở lượt Thi thử đã nộp hoặc khi bấm Kiểm tra trong Luyện tập. Câu bỏ trống không vào, để một lượt nộp sớm không làm đầy mục.
- **Ra:** đúng 2 lần, cách nhau ít nhất 12 giờ. Tính ở mọi chế độ. Trả lời sai thì đếm lại từ đầu.
- **Ôn:** một lượt chỉ gồm các câu đang trong mục, xáo thứ tự, chấm như Luyện tập. Tiến độ lưu ngay từng câu khi bấm Kiểm tra, nên ôn dở 5 câu trên điện thoại vẫn được tính. Lượt ôn không tính vào lịch sử điểm.
- Mục trống thì nút Ôn câu sai ẩn đi. Trang đầu hiện số câu đang chờ ôn, cạnh số thẻ ôn hiện có.

Câu sai của bộ đề không thành flashcard. [Đề xuất] Câu 4 lựa chọn không hợp với dạng thẻ hỏi đáp, và người dùng muốn ôn chúng như một bộ đề.

## 8. Cho tác giả

- **Thống kê từng câu:** số người đã làm, tỉ lệ sai, lựa chọn sai hay bị chọn nhất. [Đề xuất] Mỗi người chỉ tính **lần trả lời đầu tiên** với mã đáp án hiện tại, ở Thi thử đã nộp hay Luyện tập, không tính lượt ôn và không tính câu bỏ trống. Làm lại mười lần cũng chỉ tính một, vì lần đầu mới cho biết đề có vấn đề hay không.
- Chỉ hiện khi đã có ít nhất 3 người khác nhau làm câu đó, vì team nhỏ thì ngưỡng cao hơn sẽ không bao giờ tới. Không tính chính tác giả, không cho biết ai làm.
- Câu có tỉ lệ sai cao thì xếp lên đầu danh sách: thường do đáp án sai hoặc đề mơ hồ.
- Góp ý "Báo sai câu này" hiện trong danh sách góp ý hiện có, kèm tên bộ đề và id câu. Cách này chạy được ngay từ người làm đầu tiên.

## 9. Giải thích sâu bằng AI

- Dùng ô Hỏi hiện có, cùng điều kiện: package được admin duyệt, qua nhà cung cấp đã cài ở `/admin`, ZDR như hiện nay, cùng trần lượt hỏi.
- **Không gửi cả bộ đề cho AI.** Nút **Hỏi về câu này** gửi id lượt, id câu và câu hỏi của người học (tối đa 2.000 ký tự). Server tự lấy đúng câu đó: đề, lựa chọn, đáp án, lời giải, `why`, đặt trong khối dữ liệu có ranh giới như bài học hiện nay.
- Server chỉ trả lời khi câu đó được phép xem đáp án trong lượt đó, theo mục 5b. Ẩn nút là chưa đủ.
- Mỗi câu một hội thoại riêng, lưu theo người. Không có ô hỏi tự do về cả bộ đề, vì khi đó AI phải đọc mọi đáp án.
- Duyệt: admin đọc được cả bộ đề, và mã duyệt của package tính cả bộ đề. Đề đổi thì package về lại danh sách chờ duyệt, như bài học. Package chỉ có bộ đề được xin duyệt.

## 10. Soạn đề bằng AI

- **Claude (app, web, Code):** thêm nhánh bộ đề vào skill `creating-learn-packages`, không làm skill riêng. Định dạng nằm trong `references/practice-test-format.md`. `learnpkg.py validate` nhận cả thư mục package lẫn một file `.json`.
- **Gemini, ChatGPT và AI khác:** trong hộp Tải lên có nút "Hướng dẫn cho AI khác", copy một đoạn hướng dẫn gồm định dạng và một ví dụ. Người dùng dán vào AI kèm tài liệu nguồn hoặc file đề cũ, AI trả về JSON. Đoạn hướng dẫn nhắc AI tự kiểm tra từng đáp án, giải thích cả lựa chọn sai, và nhắc tới nội dung lựa chọn thay vì chữ cái.
- **File lớn:** 180 câu kèm lời giải dài hơn một lần trả lời của nhiều AI. Đoạn hướng dẫn cho AI chuyển từng bộ một, cùng `slug`. Người dùng chọn cả ba file cùng lúc khi tải lên.
- **Bắt buộc trước khi coi là xong:** đưa file 180 câu của chủ dự án qua đúng đường này với ít nhất một AI, tải lên, làm thử trọn một lượt mỗi chế độ. So số câu, đáp án đúng và loại câu với file gốc bằng máy, không đếm tay. Đề thật không đưa vào repo.

## 11. Giao diện

- Thư viện và trang đầu hiện bộ đề trong package, với số câu, thời gian, điểm cao nhất của người xem.
- Package chỉ có bộ đề: không có bước Nghe, Flashcard; mở ra là danh sách bộ đề. Tham gia qua link thì vào thẳng package đó, không vào trang "Chưa có bài học nào". Các chỗ hiện đang giả định package có ít nhất một bài đều phải xử lý: `check_package`, `_read_unpacked`, `removed_ids`, `/api/packages`, `/api/join`, `has_content`, trang duyệt của admin, trang đầu, Thư viện.
- Trong lúc làm bài, ẩn dock nghe và thanh nổi dưới đáy, để không che nút Kiểm tra, Tiếp, Nộp và không lộ nút Hỏi. Trên điện thoại có một thanh gọn: câu X/60, giờ, Tạm dừng, lưới câu.
- Theo đúng giao diện tối hiện có của app, kiểm tra ở 360 px và trên WebKit. Lựa chọn là nút lớn bấm được cả dòng, cao ít nhất 44 px.

## 12. Dữ liệu

- `package_tests`: bộ đề hiện tại của package, chỉ tóm tắt để liệt kê, không có đáp án: key, package, thứ tự, tiêu đề, số câu, thời gian, ngưỡng đậu, bản hiện tại.
- `test_revision`: id, key bộ đề, mã nội dung, toàn bộ đề. Không đổi sau khi tạo. **Không dùng lại `package_lessons` hay `lesson_for`, vì các hàm đó trả cả đáp án.** Dữ liệu gửi cho trình duyệt đi qua một hàm riêng chỉ lấy phần được phép.
- `test_attempt`: id ngẫu nhiên không đoán được, người làm, bộ đề, bản đề, chế độ (`exam`, `practice`, `review`), thứ tự câu và lựa chọn, giờ bắt đầu, tổng thời gian dừng, số lần dừng, lúc đang dừng, lúc nộp, điểm.
- `test_answer`: mỗi câu của một lượt một dòng: câu đang chọn, cờ, và sau khi chấm thì đúng hay sai, mã đáp án, thời điểm.
- `test_first_answer`: lần trả lời đầu của mỗi người với mỗi mã đáp án (chỉ ghi khi chấm một câu có chọn ở lượt không phải `review`, bằng `INSERT ... ON CONFLICT DO NOTHING`). Thống kê cho tác giả tính duy nhất từ bảng này, nên Làm lại hay hủy lượt (xóa `test_attempt` và `test_answer`) không làm mất lần trả lời đầu hay làm lệch số.
- `test_pool`: người, bộ đề, id câu, mã đáp án, lúc vào, số lần đúng liên tiếp, lần đúng gần nhất.
- Id bộ đề mang tiền tố package như mọi bảng tiến độ khác, id câu nằm dưới bộ đề. Mọi API đều lọc theo người đang đăng nhập.
- Hội thoại Hỏi dùng `ask_message`, khóa gồm package, bộ đề và câu.
- Xóa package hay xóa tài khoản thì xóa theo, bằng `ON DELETE CASCADE`, không cần thêm vào `purge_rows`. Bị thu hồi quyền hoặc bỏ package khỏi thư viện thì tiến độ ở lại như mọi tiến độ khác, để được share lại thì thấy lại và thống kê của tác giả không tụt; chỉ hội thoại Hỏi mất khi bỏ khỏi thư viện, như hiện nay.

## 13. Bắt buộc kiểm tra

- Theo mục 5b, không API nào trả đáp án, lời giải hay `why` khi lượt đó chưa cho phép. Kiểm tra bằng request thẳng tới API, không qua giao diện, kể cả ô Hỏi, và kiểm tra cả dữ liệu đề gửi xuống lúc bắt đầu lượt.
- Không đọc hay ghi được lượt của người khác, kể cả khi biết id.
- Lượt quá giờ đã đóng máy: mở lại thấy kết quả chấm từ các câu đã lưu, và bắt đầu được lượt mới.
- Lúc đang dừng, server từ chối lưu, kiểm tra, nộp.
- Tải bản mới khi đang có lượt dở: lượt đó làm và nộp được trên bản cũ; kết quả cũ không đổi; thống kê của câu đã sửa bắt đầu lại.
- Câu trả lời gửi sau hạn giờ, cho câu đã kiểm tra, cho lượt đã nộp hay lượt của người khác đều bị từ chối.
- Xáo thứ tự khác nhau giữa hai lượt; làm tiếp sau khi tải lại vẫn đúng thứ tự.
- Luật vào, ra của Ôn câu sai: câu bỏ trống không vào, 2 lần đúng cách nhau dưới 12 giờ thì chưa ra, sai thì đếm lại.
- Thống kê không hiện khi dưới 3 người, không lộ ai làm, làm lại không làm lệch số.
- Package chỉ có bộ đề: tải lên, share, tham gia qua link, xin duyệt ô Hỏi, xóa.
- File bộ đề độc hại: HTML, `<style>`, SVG và script trong chữ, link `javascript:`, ký tự vô hình, file quá lớn, 200+ câu, id trùng, `correct` trỏ tới lựa chọn không có. Kiểm tra trong trình duyệt thật rằng đồng hồ và nút của app vẫn nguyên.
- Package chỉ có bộ đề và package có cả hai đều qua được cả đường tải lên zip lẫn `.json`.
- Kiểm tra trên Chrome và WebKit, ở 360 px và màn hình rộng, kèm xem ảnh chụp.
- File 180 câu của chủ dự án đi trọn đường ở mục 10.

## 13a. Cấu hình đã có, phải giữ

CSP chặt (`script-src` chỉ `/static/`), không thư viện từ CDN, mọi chữ từ tác giả hiển thị qua `textContent` hoặc bộ hiển thị Markdown đã lọc. Migration theo `PRAGMA user_version`, sao lưu trước khi đổi.

## 14. Thứ tự xây

1. Định dạng, bộ kiểm tra, nhận bộ đề trong zip và qua `.json`.
2. Lượt làm, chấm điểm, giờ, các API không lộ đáp án.
3. Trang làm bài và trang kết quả.
4. Ôn câu sai.
5. Hỏi về câu này, giọng đọc, cỡ chữ.
6. Thống kê và góp ý cho tác giả.
7. Skill, đoạn hướng dẫn cho AI khác, chuyển thử file 180 câu.

Mỗi bước tự đứng được, có test và deploy được riêng.

## 15. Cần chủ dự án xác nhận ngoài kỹ thuật

Không có. Hai điều nên biết khi đọc: tạm dừng không giới hạn và đáp án xem lại được (mục 5, 5b) đều làm điểm Thi thử phụ thuộc vào sự trung thực của người làm.

## 16. Để builder tự quyết

Bố cục chi tiết của trang làm bài và trang kết quả trong khuôn giao diện hiện có, tên API, cách lưu thứ tự xáo, phím tắt, nội dung chính xác của đoạn hướng dẫn cho AI khác.
