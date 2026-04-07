Tùy chọn: đặt ffmpeg vào thư mục này trước khi chạy dev hoặc build portable.

Cách 1 — chỉ một file: copy ffmpeg.exe thẳng vào resources\ffmpeg\

Cách 2 — giải nén nguyên thư mục (ví dụ gyan.dev essentials):
  resources\ffmpeg\ffmpeg-2026-04-01-git-…-essentials_build\bin\ffmpeg.exe
  App và PyInstaller đều tự tìm …\bin\ffmpeg.exe (ưu tiên thư mục con sort tên mới nhất).

Sau khi build portable, ffmpeg.exe được copy cạnh PackRecorder.exe — máy đích không cần cài ffmpeg.

Tải bản Windows: https://www.gyan.dev/ffmpeg/builds/

Nếu bỏ qua: app tìm ffmpeg trong PATH hoặc ô «Đường dẫn ffmpeg» trong Cài đặt.
