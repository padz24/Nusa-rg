PROMPT IMPLEMENTASI 5 FITUR ADVANCE NUSA-RG

KONTEKS PROYEK

Anda sedang mengembangkan NUSA-RG, asisten pemrograman CLI berbasis Python yang dirancang untuk Termux pada Android ARM64.

Dokumentasi utama:

- README.md
- README.id.md
- AGENS.md

Arsitektur yang sudah ada mencakup:

- CLI menggunakan Click.
- CoreEngine untuk mengatur alur kerja asisten.
- Local Project RAG dengan SQLite FTS5 dan peringkat BM25.
- API client yang kompatibel dengan OpenAI Chat Completions.
- Dukungan model lokal melalui llama.cpp dan model GGUF.
- Provider catalogue, fallback provider, dan streaming jawaban.
- Session Store untuk menyimpan percakapan.
- Command runner tanpa melewati shell.
- Konfigurasi YAML dan keystore untuk kredensial.
- Logging, audit, sanitasi keluaran perintah, dan pengamanan prompt injection.
- Renderer Markdown untuk terminal.

Versi dasar yang didokumentasikan adalah 1.3.0. Jangan mengasumsikan struktur source code, nama class, signature fungsi, atau perilaku implementasi tanpa memeriksa repository yang sebenarnya.

ATURAN WAJIB UNTUK SEMUA FITUR

1. Periksa struktur proyek, modul terkait, konfigurasi, pola arsitektur, dan tes yang sudah ada sebelum mengubah kode.
2. Implementasikan fitur di dalam arsitektur yang tersedia. Jangan membuat aplikasi kedua atau mengganti CoreEngine tanpa alasan teknis yang kuat.
3. Pertahankan kompatibilitas Python 3.10+, Termux Android ARM64, mode API, mode lokal, streaming, failover, sesi, dan command runner.
4. Gunakan dependensi yang ringan dan ramah Termux. Utamakan standard library dan dependensi yang sudah ada. Jangan menambah library berat tanpa justifikasi.
5. Jangan membuat command, class, API, atau format penyimpanan palsu yang hanya tampak bekerja dalam dokumentasi.
6. Jangan menghapus atau melemahkan kontrol keamanan yang sudah ada.
7. Semua operasi filesystem harus memvalidasi path, menangani kegagalan dengan jelas, dan menghindari kehilangan data pengguna.
8. Jangan pernah menjalankan perintah, menerapkan patch, atau menghapus data hanya karena model menyarankannya. Operasi yang mengubah proyek harus mengikuti persetujuan eksplisit pengguna.
9. Tambahkan unit test dan integration test yang relevan, termasuk kasus error, input tidak valid, dan kondisi batas.
10. Jangan mengubah hasil tes menjadi hard-coded pass atau menonaktifkan tes yang gagal untuk membuat suite tampak berhasil.
11. Perbarui README.md, README.id.md, dan AGENS.md agar dokumentasi mencerminkan implementasi sebenarnya.
12. Pertahankan gaya terminal, warna, emblem, penanganan error, dan konvensi penamaan yang sudah dipakai proyek.
13. Jalankan tes yang relevan. Jika lingkungan tidak memungkinkan tes tertentu dijalankan, jelaskan keterbatasannya secara spesifik.
14. Periksa "git diff" sebelum menyelesaikan pekerjaan. Jangan menimpa perubahan pengguna yang sudah ada.

Untuk setiap fitur, lakukan pekerjaan secara nyata: inspeksi, desain yang sesuai dengan source code, implementasi, pengujian, dokumentasi, dan pemeriksaan akhir. Jangan berhenti pada rencana atau pseudocode jika repository dan lingkungan memungkinkan implementasi.

---

FITUR 1 — PROOF-FIRST ANSWER

Tujuan

Tingkatkan NUSA-RG agar jawaban tentang kode proyek dilengkapi bukti yang bisa diverifikasi. Asisten harus membedakan fakta yang ditemukan dalam source code, inferensi, dan informasi yang belum diketahui.

Fitur yang harus dibuat

A. Bukti untuk jawaban

Ketika RAG mengambil snippet, pertahankan metadata sumber, setidaknya:

- Path relatif file.
- Baris awal dan akhir.
- Isi snippet.
- Informasi relevansi yang memang tersedia dari retriever.

Ketika menjawab pertanyaan tentang proyek, tampilkan rujukan yang sesuai, misalnya:

"src/auth.py:12-18"

Pastikan rentang baris benar-benar sesuai dengan source code. Jangan membuat nomor baris, nama file, atau kutipan yang tidak ditemukan.

B. Pisahkan fakta dari inferensi

Jawaban harus membedakan:

- Ditemukan: didukung langsung oleh kode atau dokumentasi.
- Inferensi: merupakan kesimpulan berdasarkan bukti yang tersedia.
- Belum diketahui: bukti yang tersedia belum cukup untuk memastikan jawaban.

Jangan memaksa setiap jawaban umum mempunyai sitasi kode. Aktifkan perilaku pembuktian terutama untuk pertanyaan yang berkaitan dengan proyek terindeks.

C. Deteksi bukti tidak memadai

Jika hasil retrieval kosong, ambigu, atau tidak mencukupi:

- Nyatakan keterbatasannya.
- Hindari mengarang implementasi.
- Tawarkan pencarian tambahan atau minta informasi yang diperlukan.
- Jangan menampilkan label keyakinan numerik yang tidak didukung metode pengukuran yang nyata.

D. Integrasi arsitektur

Periksa RAG retriever, prompt composer, CoreEngine, LLM client, streaming renderer, dan renderer Markdown yang tersedia.

Rujukan harus tetap benar saat streaming, jawaban tidak di-streaming, mode lokal, provider eksternal, dan failover digunakan.

Gunakan satu sumber metadata bukti yang konsisten agar format rujukan tidak dibuat secara terpisah oleh tiap provider.

E. Pengujian dan penerimaan

Buat tes untuk:

1. Jawaban menggunakan path dan rentang baris yang benar.
2. Tidak ada sitasi palsu ketika file tidak ditemukan.
3. Hasil retrieval kosong ditangani dengan jujur.
4. Jawaban membedakan bukti langsung dan inferensi.
5. Format tetap bekerja dengan streaming dan mode non-streaming.
6. Jalur provider cadangan tidak menghilangkan metadata yang diperlukan.

Acceptance criteria

Fitur selesai jika pertanyaan tentang fungsi yang ada dalam proyek dapat dijawab dengan rujukan sumber yang valid; bukti yang tidak tersedia tidak dikarang; dan tes baru lulus tanpa merusak perilaku chat yang sudah ada.

---

FITUR 2 — NUSA CODE GENOME

Tujuan

Tambahkan kemampuan untuk memahami struktur dan hubungan kode proyek, tidak sekadar mencari teks menggunakan SQLite FTS5.

Code Genome harus membantu pengguna menemukan simbol, dependensi, pemanggil fungsi, dan kemungkinan dampak perubahan.

Fitur yang harus dibuat

A. Symbol index

Mulai dengan analisis statis Python menggunakan "ast" dari standard library.

Ekstrak informasi yang relevan, seperti:

- Modul dan file.
- Class.
- Fungsi dan metode.
- Import.
- Nomor baris definisi.
- Hubungan yang dapat disimpulkan dengan aman dari pemanggilan fungsi dan referensi yang ditemukan.

Jangan mengeksekusi kode proyek untuk membangun indeks.

Buat skema penyimpanan yang konsisten dengan arsitektur NUSA-RG. Bila menambahkan tabel SQLite atau indeks baru, sediakan mekanisme inisialisasi dan pembaruan skema yang aman.

Pertahankan indeks FTS5 yang sudah ada. Jangan mengganti RAG yang berfungsi hanya untuk membuat fitur baru.

B. Perintah CLI

Tambahkan subcommand berikut atau bentuk yang sesuai dengan konvensi CLI yang sudah ada:

"nusa-rg map"

Menampilkan ringkasan struktur proyek yang terindeks.

"nusa-rg map --symbol verify_password"

Menemukan definisi simbol dan informasi struktur yang benar-benar diketahui.

"nusa-rg impact src/auth.py"

Menampilkan file dan simbol yang berpotensi terdampak oleh perubahan.

Sebelum menentukan nama dan signature command, periksa pola Click dalam repository dan hindari konflik dengan command yang sudah ada.

C. Analisis dampak

Untuk suatu file atau simbol:

- Cari referensi langsung yang dapat ditemukan.
- Tampilkan relasi import atau pemanggilan yang memiliki bukti.
- Tunjukkan file tes yang relevan jika berhasil diidentifikasi.
- Bedakan relasi yang terdeteksi dari relasi yang baru berupa dugaan.
- Berikan path dan nomor baris untuk setiap hasil.

Jangan mengklaim graph lengkap apabila analisis dinamis, reflection, atau pemanggilan melalui string membuat hubungan tertentu tidak dapat dideteksi.

D. Pembaruan indeks

Integrasikan Code Genome dengan alur indeksasi yang sudah ada.

Perubahan file harus dapat memperbarui informasi simbol tanpa merusak indeks ketika proses terhenti. Gunakan pendekatan transaksional dan penanganan error yang konsisten.

Untuk versi awal, dukung Python dengan baik. Rancang ekstensi bahasa lain secara modular tanpa mengklaim bahasa tersebut sudah didukung sebelum parser-nya diimplementasikan.

E. Efisiensi

- Manfaatkan metadata file dan strategi incremental indexing yang sudah tersedia.
- Hindari membaca file tidak relevan atau binary.
- Ikuti konfigurasi ignore directories dan ignore globs.
- Jangan mengeksekusi kode pengguna.
- Hindari ketergantungan berat pada perangkat Android.

F. Pengujian dan penerimaan

Buat tes untuk:

1. Deteksi fungsi, class, dan import.
2. Nomor baris yang benar.
3. File yang diubah, dihapus, atau tidak lagi valid.
4. File syntax error yang tidak boleh membuat keseluruhan indeks rusak.
5. Path tidak valid dan simbol yang tidak ditemukan.
6. Relasi yang ambigu.
7. Integrasi dengan "nusa-rg index" yang sudah tersedia.
8. Perilaku indeks setelah inisialisasi ulang atau proses terhenti.

Acceptance criteria

Pengguna dapat memeriksa struktur proyek, mencari simbol, dan melihat analisis dampak berbasis bukti melalui terminal. Analisis tidak mengeksekusi source code dan tidak merusak indeks RAG yang sudah ada.

---

FITUR 3 — PRIVACY FIREWALL

Tujuan

Buat lapisan kebijakan privasi yang memeriksa konteks sebelum meninggalkan perangkat, khususnya ketika NUSA-RG mengirim prompt ke provider eksternal atau beralih ke provider cadangan.

Fitur ini harus memperkuat keamanan yang sudah ada, bukan menggantikannya.

Fitur yang harus dibuat

A. Kebijakan privasi terpusat

Tambahkan konfigurasi yang kompatibel dengan konfigurasi lama. Contoh berikut merupakan usulan struktur, bukan asumsi bahwa struktur ini sudah ada:

privacy:
  secret_detection: true
  redact_secrets: true
  local_only:
    - ".env"
    - "private/**"
    - "secrets/**"
  confirm_sensitive_context: true

Periksa pola konfigurasi yang digunakan NUSA-RG sebelum menentukan nama field final.

Konfigurasi lama harus tetap dapat dimuat dengan aman dan nilai default harus terdokumentasi.

B. Pemindaian sebelum pengiriman

Sebelum request eksternal dikirim:

1. Identifikasi sumber setiap bagian konteks.
2. Periksa apakah path masuk kebijakan local-only.
3. Pindai kemungkinan API key, token, private key, dan pola rahasia umum.
4. Terapkan redaksi yang mempertahankan struktur konteks seperlunya.
5. Blokir pengiriman jika kebijakan melarangnya.
6. Berikan ringkasan yang aman mengenai alasan pemblokiran atau redaksi.

Jangan hanya memindai prompt utama. Pertimbangkan retrieved snippets, riwayat percakapan, dan keluaran command runner yang akan masuk ke konteks.

C. Pengendalian provider

Kebijakan harus ditegakkan sebelum pemilihan atau pemanggilan setiap provider eksternal, termasuk provider fallback.

Provider cadangan tidak boleh menjadi jalur untuk melewati larangan pengiriman data.

Perilaku fallback ketika konteks sensitif ditolak harus jelas. Jangan otomatis mengalihkan data terlarang ke provider lain.

Mode model lokal harus tetap dapat digunakan ketika kebijakan dan implementasinya mengizinkan proses lokal tersebut.

D. Keamanan penyimpanan dan log

- Jangan menulis rahasia ke log, audit log, atau pesan error.
- Jangan menyimpan plaintext secret detection report.
- Hindari menampilkan ulang secret dalam terminal.
- Jangan berasumsi redaksi dapat mendeteksi semua rahasia.
- Jangan pernah mengklaim semua data sensitif pasti terdeteksi.
- Pertahankan mekanisme masking, keystore, dan pembatasan izin file yang sudah ada.

E. Path dan kegagalan

Uji path relatif, path absolut, symlink, glob, traversal path, serta file yang tidak lagi tersedia.

Jika sistem tidak bisa memastikan apakah konteks aman dikirim, terapkan kebijakan fail-closed untuk operasi eksternal yang dibatasi, dengan error yang jelas dan cara pemulihan yang aman.

F. Pengujian dan penerimaan

Buat tes untuk:

1. Secret yang dikenali tidak muncul dalam payload eksternal setelah redaksi.
2. File local-only tidak terkirim ke provider eksternal.
3. Provider fallback tunduk pada kebijakan yang sama.
4. Keluaran command runner diperiksa sebelum dimasukkan ke prompt.
5. Riwayat sesi diperiksa ketika akan digunakan sebagai konteks.
6. Tidak ada secret di log dan pesan error.
7. Konfigurasi lama tetap kompatibel.
8. Kegagalan pemindaian menghasilkan perilaku aman yang terdokumentasi.

Gunakan provider dan transport palsu dalam tes agar tidak membutuhkan jaringan atau API key nyata.

Acceptance criteria

Tidak ada jalur pengiriman eksternal yang boleh melewati Privacy Firewall. Keputusan blokir dan redaksi dapat diuji, serta seluruh provider fallback mematuhi kebijakan yang sama.

---

FITUR 4 — GHOST PATCH

Tujuan

Buat sistem perbaikan kode yang menghasilkan patch untuk ditinjau dan diuji tanpa langsung mengubah source code asli.

Alurnya harus berupa: analisis → patch → review → pengujian → persetujuan → penerapan.

Fitur yang harus dibuat

A. Pembuatan patch

Tambahkan antarmuka yang sesuai dengan gaya CLI yang ada, dengan kemampuan konseptual seperti:

nusa-rg fix "perbaiki validasi password"
nusa-rg patch review
nusa-rg patch test
nusa-rg patch apply
nusa-rg patch discard

Periksa terlebih dahulu struktur command Click, mekanisme sesi, proyek aktif, dan command runner sebelum menetapkan bentuk finalnya.

Model diminta menghasilkan patch terstruktur, misalnya unified diff. Jangan mengizinkan model menulis langsung ke file asli hanya dengan mengembalikan teks bebas.

B. Validasi patch

Sebelum menyimpan atau menerapkan patch:

- Validasi format diff.
- Pastikan path target berada dalam proyek yang diizinkan.
- Tolak absolute path, path traversal, dan target yang tidak diizinkan.
- Periksa target file dan konteks perubahan.
- Tangani file baru, penghapusan file, dan perubahan binary secara eksplisit.
- Tolak patch yang tidak dapat diterapkan dengan jelas.
- Jangan menimpa perubahan pengguna yang tidak terkait.

C. Staging terisolasi

Gunakan mekanisme yang sesuai, misalnya direktori kerja sementara yang aman atau Git worktree jika memenuhi kebutuhan proyek.

Jangan mengasumsikan semua pengguna memakai Git.

Pengujian patch harus dilakukan pada salinan terisolasi, bukan dengan mengubah source code aktif secara diam-diam.

Jangan menyalin secret ke lokasi yang kurang aman. Bersihkan direktori sementara sesuai kebijakan dan lakukan cleanup dengan penanganan error.

D. Review

Tampilkan:

- File yang berubah.
- Ringkasan perubahan.
- Diff sebelum dan sesudah.
- Tes yang akan dijalankan.
- Status validasi.
- Peringatan jika perubahan berisiko atau cakupannya terlalu besar.

Pengguna harus bisa membatalkan patch tanpa mengubah file asli.

E. Pengujian

Jalankan tes hanya melalui alur eksplisit yang disetujui pengguna.

Gunakan command runner dan proteksi yang sudah ada. Jangan menyisipkan input model ke shell. Jangan memperluas izin eksekusi hanya demi menjalankan patch.

Batasi timeout dan output tes sesuai konfigurasi proyek.

Laporkan secara terpisah:

- Tes yang belum dijalankan.
- Tes yang lulus.
- Tes yang gagal.
- Tes yang tidak dapat dijalankan.
- Keterbatasan sandbox jika ada.

Jangan menyebut patch aman atau berhasil hanya karena diff valid.

F. Penerapan patch

"patch apply" harus membutuhkan tindakan eksplisit pengguna.

Sebelum penerapan, pastikan file target tidak berubah sejak proses review. Jika berubah, hentikan proses dan minta pembuatan ulang atau review baru.

Penerapan harus menjaga perubahan yang tidak terkait, menangani kegagalan secara aman, serta tidak menghapus data pengguna.

Jangan mengklaim transaksi atomik untuk seluruh perubahan multi-file jika implementasinya tidak benar-benar menyediakan jaminan tersebut.

G. Pengujian dan penerimaan

Buat tes untuk:

1. Patch valid dan patch malformed.
2. Path traversal dan absolute path.
3. Konflik akibat perubahan pengguna.
4. Patch yang gagal diterapkan.
5. Kegagalan tes.
6. Cleanup direktori sementara.
7. Persetujuan dan pembatalan.
8. File baru dan file yang dihapus.
9. Kegagalan di tengah penerapan.
10. Penerapan patch tanpa Git jika mode tersebut didukung.

Acceptance criteria

Tidak ada patch yang diterapkan otomatis hanya karena model menyarankannya. Pengguna bisa meninjau dan menguji perubahan terlebih dahulu, membatalkannya, serta menerapkannya secara eksplisit tanpa kehilangan perubahan yang sudah ada.

---

FITUR 5 — MEMORY OF FAILURE

Tujuan

Bangun memori debugging lokal yang menyimpan hasil percobaan perbaikan sehingga NUSA-RG dapat memanfaatkan pengalaman sebelumnya dan mengurangi pengulangan percobaan yang gagal.

Fitur ini berbeda dari Session Store. Session Store menyimpan percakapan, sedangkan Memory of Failure menyimpan catatan debugging terstruktur yang dapat dicari lintas sesi.

Fitur yang harus dibuat

A. Model data

Simpan catatan terstruktur yang sesuai dengan arsitektur penyimpanan NUSA-RG, dengan field konseptual seperti:

- ID catatan.
- Identitas proyek yang tidak bergantung pada path absolut saja.
- Sidik jari error yang dinormalisasi.
- Jenis error.
- Versi atau commit proyek jika tersedia.
- Hipotesis yang dicoba.
- Ringkasan perubahan atau patch.
- Tes yang dijalankan.
- Hasil tes.
- Status keberhasilan yang telah diverifikasi.
- Timestamp.
- Metadata minimum yang diperlukan untuk retrieval.

Rancang penyimpanan dan migrasinya setelah memeriksa pola SQLite dan state directory yang sudah ada.

Jangan menyimpan semua isi source code atau seluruh konteks prompt hanya demi membangun memori.

B. Perekaman kegagalan

Setelah pengguna menjalankan debugging atau Ghost Patch, tawarkan pencatatan hasil yang relevan.

Catat percobaan gagal dengan status eksplisit. Bedakan:

- Percobaan gagal.
- Percobaan belum diuji.
- Percobaan terinterupsi.
- Solusi terverifikasi berhasil.

Jangan menyimpulkan suatu solusi berhasil hanya karena model mengklaimnya. Status berhasil harus didukung bukti, seperti tes yang lulus dan hubungan yang jelas dengan perubahan terkait.

C. Error fingerprint

Buat normalisasi error yang mengurangi variasi tidak relevan, misalnya nomor alamat memori atau nilai dinamis tertentu, tanpa menghapus informasi penting yang dapat membedakan dua error berbeda.

Hindari penggabungan fingerprint yang terlalu agresif. Simpan metadata pendukung yang memungkinkan hasil yang mirip tetap dibedakan.

Jangan menggunakan hash sebagai bukti bahwa dua masalah pasti identik.

D. Retrieval memori

Saat pengguna mengajukan masalah baru:

1. Cari catatan dengan fingerprint atau deskripsi error yang relevan.
2. Perhatikan proyek, versi, dan konteks.
3. Tampilkan percobaan sebelumnya beserta hasilnya.
4. Sertakan hanya catatan yang relevan ke prompt.
5. Beri label jelas bahwa itu pengalaman historis, bukan kebenaran universal.

Contoh keluaran:

MEMORY OF FAILURE

Error serupa ditemukan.

Percobaan sebelumnya:
- Hipotesis: perubahan algoritma hashing
- Hasil: gagal
- Bukti: test_auth.py::test_login

Rekomendasi:
Jangan mengulang perubahan yang sama tanpa bukti baru.

Catatan:
Masalah sekarang belum tentu identik dengan kasus terdahulu.

E. CLI

Tambahkan perintah untuk melihat, mencari, dan mengelola catatan memori dengan mengikuti konvensi CLI repository.

Contoh konseptual:

nusa-rg memory list
nusa-rg memory search "authentication failure"
nusa-rg memory show <id>
nusa-rg memory delete <id>

Tambahkan konfirmasi yang tepat untuk operasi destruktif dan gunakan ID yang tervalidasi.

F. Privasi

- Simpan memori secara lokal secara default.
- Jangan memasukkan secret ke dalam fingerprint atau ringkasan.
- Hormati Privacy Firewall jika telah tersedia.
- Batasi izin berkas sesuai mekanisme keamanan NUSA-RG.
- Jangan mengirim isi memori ke provider eksternal tanpa mengikuti kebijakan pengiriman konteks yang berlaku.
- Sediakan cara menghapus catatan dan seluruh memori terkait proyek secara terkontrol.

G. Pengujian dan penerimaan

Buat tes untuk:

1. Error yang sama menghasilkan pencarian yang relevan.
2. Error mirip tidak otomatis dianggap identik.
3. Catatan gagal tidak ditampilkan sebagai solusi terverifikasi.
4. Status keberhasilan memerlukan bukti.
5. Retrieval lintas sesi.
6. Isolasi catatan antarproyek.
7. Penghapusan catatan.
8. Sanitasi secret.
9. Perubahan skema penyimpanan dan pemulihan error.
10. Tes offline tanpa API key atau akses jaringan.

Acceptance criteria

NUSA-RG mampu menemukan catatan debugging sebelumnya dan menggunakan hasilnya sebagai konteks tambahan. Sistem secara eksplisit membedakan kegagalan, percobaan yang belum diverifikasi, dan solusi yang terbukti bekerja.

---

LANGKAH AKHIR UNTUK SETIAP FITUR

Setelah implementasi selesai:

1. Jalankan tes baru dan tes regresi yang relevan.
2. Periksa hasil linting atau pemeriksaan tipe yang memang sudah digunakan proyek.
3. Pastikan semua command baru terhubung dengan entry point CLI yang benar.
4. Pastikan tidak ada dependensi baru yang membuat instalasi Termux ARM64 rusak.
5. Periksa "git diff" dan perubahan file yang tidak terkait.
6. Perbarui README.md, README.id.md, dan AGENS.md.
7. Pastikan contoh command dalam dokumentasi benar-benar sesuai dengan implementasi.
8. Laporkan fitur yang selesai, file yang diubah, perubahan konfigurasi atau skema, tes yang dijalankan, hasil tes aktual, dan keterbatasan yang belum teratasi.

Jangan mengklaim seluruh test suite lulus jika hanya sebagian tes yang dijalankan. Jangan menandai Acceptance Criteria sebagai terpenuhi tanpa hasil yang mendukungnya.

Prioritas implementasi: Proof-First Answer → Code Genome → Privacy Firewall → Ghost Patch → Memory of Failure.

Pertahankan desain modular NUSA-RG dan pastikan semua fitur dapat digunakan bersama, bukan menjadi lima implementasi terpisah yang saling bertentangan.
