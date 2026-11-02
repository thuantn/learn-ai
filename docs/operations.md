# Vận hành

App chạy bằng Docker Compose trên một VM, đi ra Internet qua Cloudflare Tunnel, không mở cổng trên host. Tên miền và địa chỉ VM giữ ngoài repo.

## Credentials

Không credential nào nằm trong repo, image hay log.

| Thứ | Nằm ở đâu | Đi qua đâu |
|---|---|---|
| Mật khẩu người dùng | Chỉ người đó biết, server lưu bản băm Argon2id | HTTPS tới app |
| Mật khẩu tạm | Lệnh `add-user` in ra một lần | Người quản trị tự đưa cho người dùng; app không gửi email |
| Token tunnel | `.env` quyền 600 trên VM | SFTP qua SSH từ máy quản trị |
| Khóa AI (`AI_API_KEY`) | `.env` trên VM | Server gọi nhà cung cấp AI; không xuống trình duyệt |
| Khóa liên kết bài (`LINK_SECRET`) | `.env` trên VM | Ký URL `/s/<token>/...` cho trang bài trong sandbox; không xuống trình duyệt |
| Khóa SSH của user deploy | Máy quản trị, ngoài repo và ngoài thư mục đồng bộ đám mây | Không rồi máy |
| Mật khẩu admin VM | Máy quản trị | Chỉ dùng cho SSH và stdin của `sudo` lúc tạo user |

Quy tắc:
- Giữ các file này ngoài thư mục đồng bộ như OneDrive.
- Không gửi credential cho model phản biện. Prompt phản biện chỉ chứa nội dung tài liệu.
- Xóa file chứa mật khẩu tạm sau khi người dùng đã đổi mật khẩu.
- Trên Windows, `chmod` trong Git Bash không có tác dụng thật. Quyền của file phụ thuộc ACL của thư mục home.

## Deploy lần đầu

1. Tạo tunnel và bản ghi DNS trên máy có chứng chỉ Cloudflare, rồi lấy token:
   ```
   cloudflared tunnel create learn-ai
   cloudflared tunnel route dns learn-ai <tên miền>
   cloudflared tunnel token learn-ai
   ```
2. Trên VM, tạo user riêng trong nhóm `docker`, khóa mật khẩu, chỉ cho đăng nhập bằng khóa SSH.
3. Chép code từ `git archive HEAD`, nội dung đã đóng gói vào `~/learn-ai/content`, và package bài học đã kiểm tra vào `~/learn-ai/packages`. Tạo `data/` và `backups/` thuộc user đó.
4. Tạo `.env` quyền 600 theo `README.md`. Thêm `LINK_SECRET` ngẫu nhiên 32 byte trở lên để ký URL sandbox.
5. Chạy:
   ```
   docker compose up -d --build
   docker compose exec app python -m app.cli add-user <email>
   ```
6. Kiểm tra từ Internet, không chỉ xem container healthy. Xem mục Kiểm tra.

## Cập nhật

- **Code:** chép bản mới, `docker compose up -d --build`.
- **Nội dung:** chép thư mục đóng gói mới vào `content/`, rồi `docker compose restart app`. App chỉ đọc `manifest.json` lúc khởi động, nên không restart thì bài mới không hiện.
- **Package sandbox:** chép package đã kiểm tra vào `packages/`, rồi `docker compose restart app`. App đọc `packages/package.json` lúc tạo URL sandbox.

## Tài khoản

```
python -m app.cli add-user <email>        tạo tài khoản, in mật khẩu tạm
python -m app.cli reset-password <email>  cấp mật khẩu tạm mới, xóa mọi phiên
python -m app.cli end-sessions <email>    xóa mọi phiên
python -m app.cli remove-user <email>     xóa tài khoản và dữ liệu
python -m app.cli list-users
```

Chạy trong container bằng `docker compose exec app`.

## Bật ô Hỏi

Thêm `AI_API_KEY` vào `.env`, rồi `docker compose up -d`. Dùng khóa riêng có trần chi tiêu, không dùng chung với app khác. Thử bằng khóa thật xem model mặc định có endpoint ZDR không; không có thì đổi `AI_MODEL`, không tắt `AI_ZDR`.

## Kiểm tra sau deploy

- Trang đầu chuyển về đăng nhập, response có CSP, HSTS, `nosniff`.
- Người chưa đăng nhập không lấy được `/api/*` và trang bài.
- Cookie là `__Host-session`, `Secure`, `HttpOnly`, `SameSite=Strict`.
- Audio trả `206`, tua được.
- Trang bài hiện công thức và báo đã lưu vào tài khoản.
- `docker port` của app không có gì. App khác trên VM vẫn healthy. Đo `docker stats`.
- `tests/e2e_browser.py` chạy trên máy với nội dung thật. Chỉ dùng tài khoản thử trên bản thật và xóa sau đó.

## Lỗi đã gặp

- **Tunnel không lên, log báo `failed to dial to edge with quic`:** mạng chặn QUIC. Compose đã đặt `--protocol http2`.
- **Build lỗi mạng hoặc kết nối treo trong container:** VM có MTU thấp. Đặt `MTU=1280` trong `.env`; build dùng `network: host`.
- **Console báo CSP chặn `cloudflareinsights`:** Cloudflare tự chèn script thống kê. Vô hại; tắt Web Analytics ở zone nếu muốn hết.

## Sao lưu và khôi phục

App sao lưu database lúc khởi động và mỗi 24 giờ vào `backups/`, giữ 14 bản. Khôi phục: dừng app, chép bản sao lưu thành `data/learn.db`, xóa `learn.db-wal` và `learn.db-shm` nếu có, rồi khởi động lại.

## Khi nghi bị lộ

1. Thu hồi khóa AI ở nhà cung cấp.
2. Xóa tunnel cũ hoặc đổi token, deploy lại `.env`.
3. `end-sessions` và `reset-password` cho người liên quan.
4. Thay khóa SSH của user deploy.
5. Ghi lại nguyên nhân vào `LESSONS_LEARNED.md`, không ghi giá trị secret.
