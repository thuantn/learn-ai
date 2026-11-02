# Kết quả chạy thử sandbox (bước 2 của spec)

Ngày 02/11/2026. Trang bài của tác giả chạy trong iframe `sandbox="allow-scripts"`, phục vụ qua `/s/<token>/...`, nói chuyện với app qua `MessagePort`.

## Quyết định

Đi tiếp, dùng cùng hostname. Không cần hostname riêng cho trang bài. Điều kiện còn mở là thử trên điện thoại thật, phải xong trước khi cấp tài khoản cho team.

## Đã đo

| Kiểm tra | Chrome | WebKit (Playwright) | Điện thoại thật |
|---|---|---|---|
| `tests/e2e_sandbox.py`, gồm trang độc | không lỗi | không lỗi | chưa thử |
| Trang đọc cookie, gọi `/api/*`, gọi ra ngoài, gửi form, mở cửa sổ | bị chặn | bị chặn | chưa thử |
| Iframe tự điều hướng ra ngoài | không tới được bên ngoài, app gỡ khung và báo | như Chrome | chưa thử |
| WebRTC | `state: new`, 0 candidate | ghi trong lượt chạy | chưa thử |
| Công thức, font, máy tính tương tác, quiz qua cầu nối | chạy | chạy | chưa thử |
| Audio tua được | chạy, kể cả qua tunnel trên bản thật | chạy | chưa thử |
| Mở trực tiếp trang bài trong tab (`Sec-Fetch-Dest` khác `iframe`) | 403 | 403 | chưa thử |
| Khung đầy chiều rộng ở 360, 390, 1024, 1440 px, không cuộn ngang | đạt | đạt | chưa thử |

Playwright WebKit không phải Safari thật, nên cột giữa chưa thay được iPhone.

## Trên bản đang chạy

Kiểm tra từ Internet với tài khoản thử, đã xóa sau khi xong: trang bài mở qua `/s/`, có công thức, báo đã lưu vào tài khoản, audio tua được qua tunnel, `lesson.json` trả 404, người chưa đăng nhập bị chuyển về đăng nhập. RAM của app khoảng 60 MB.

## Khác với thiết kế

- `--no-access-log`: URL `/s/<token>/...` chứa token, nên uvicorn không ghi access log. Việc này khác với lớp ghi log đường dẫn trong `01-app-ban-dau.md`. Đăng nhập và lỗi vẫn được ghi.
- Cầu nối gom `doc.set` tối đa một lần mỗi 2 giây, và giới hạn xin mở link 3 lần mỗi 10 giây, để trang xấu không làm phiền được người học.

## Việc còn mở

Thử trên iPhone Safari và Android Chrome bằng 4G. Nếu không đạt, phương án dự phòng trong spec vẫn còn: hostname riêng qua tunnel, giữ nguyên sandbox.
